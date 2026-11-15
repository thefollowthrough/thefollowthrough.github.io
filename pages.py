#!/usr/bin/env python3
"""Builds plain HTML pages that search engines can read and that look good when shared:
one page per decision (decision/<CELEX>.html), one per section (section/<id>.html), the goals
page (goals.html), plus sitemap.xml and robots.txt.

The interactive site (index.html + app.js) stays the main experience: every page here links to it.
Run automatically at the end of update.py; can also be run on its own: python3 pages.py
"""
import html
import json
import os
import re
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
MONTHS = "January February March April May June July August September October November December".split()
WHO = {"EU law": "Passed by the European Parliament and the Council",
       "Council act": "Adopted by the Council of the EU",
       "Foreign policy decision": "Foreign-policy decision by EU governments",
       "Foreign policy update": "EU governments changed an earlier foreign-policy decision"}
e = lambda s: html.escape(str(s or ""), quote=True)


def dlong(s):
    y, m, d = s[:10].split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]} {y}"


def eurlex(celex):
    return f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"


def milestones(d):
    ms = {d["date"]: "Adopted"}
    for i, x in enumerate(d.get("in_force", [])):
        ms.setdefault(x, "Enters into force" if i == 0 else "Next stage starts to apply")
    for x in d.get("deadlines", []):
        ms.setdefault(x, "Deadline (transposition, review or report)")
    return sorted(((k, v) for k, v in ms.items() if k < "9999"))


EU27 = {"AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia", "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark",
        "EE": "Estonia", "FI": "Finland", "FR": "France", "DE": "Germany", "EL": "Greece", "HU": "Hungary", "IE": "Ireland",
        "IT": "Italy", "LV": "Latvia", "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta", "NL": "Netherlands", "PL": "Poland",
        "PT": "Portugal", "RO": "Romania", "SK": "Slovakia", "SI": "Slovenia", "ES": "Spain", "SE": "Sweden"}


def score(d, targets, today):
    if d.get("ended"):
        x = d["ended"]
        return None, "No longer in force", ((f"It stopped applying on {dlong(x['date'])}." if x.get("date") else "It no longer applies.")
                                            + (f" It was replaced by {x['by_ref']}." if x.get("by") else ""))
    if d.get("targets") and d["targets"][0] in targets:
        t = targets[d["targets"][0]]
        return t["progress"], "Goal progress", f"Europe is {t['progress']}% of the way to the goal this decision serves: “{t['short']}”."
    ms = milestones(d)
    passed = sum(1 for k, _ in ms if k <= today)
    if len(ms) < 3 or d["kind"] == "Foreign policy update":   # a percentage would mean nothing: give a status
        later = next(((k, v) for k, v in ms if k > today), None)
        if later:
            return None, "Not yet in force", f"Adopted on {dlong(d['date'])}. {later[1].split(' (')[0]} on {dlong(later[0])}."
        eif = (d.get("in_force") or [None])[0]
        return None, ("In force" if eif else "Adopted"), (f"In force since {dlong(eif)}." if eif else f"Adopted on {dlong(d['date'])}.")
    pct = round(passed / len(ms) * 100)
    nxt = next(((k, v) for k, v in ms if k > today), None)
    why = (f"{passed} of {len(ms)} legal milestones reached. Next: {nxt[1].lower()} on {dlong(nxt[0])}."
           if nxt else ("Its only legal milestone has been reached." if len(ms) == 1 else f"All {len(ms)} legal milestones have been reached."))
    return pct, "Rollout", why


def dek(d, today):
    if d.get("summary"):
        return d["summary"]
    s = f"{WHO.get(d['kind'], 'Adopted')} on {dlong(d['date'])}."
    if d["kind"] == "Foreign policy update":
        base = (d["links"].get("changes") or [None])[0]
        return s + (f" It changes {base['ref']}." if base else "") + " Updates like this usually add or remove names, extend a deadline or change a budget: the official text says which."
    future = [(k, v) for k, v in milestones(d) if k > today]
    if future:
        k, v = future[0]
        s += f" Next step: {v.split(' (')[0].lower()} on {dlong(k)}"
        s += f", with {len(future) - 1} more milestone{'s' if len(future) > 2 else ''} after that." if len(future) > 1 else "."
    elif d.get("in_force"):
        end = (d.get("ended") or {}).get("date")
        s += f" It applied from {dlong(d['in_force'][0])} to {dlong(end)}." if end else f" In force since {dlong(d['in_force'][0])}."
    n = d.get("links_n", {}).get("based_on", len(d["links"].get("based_on", [])))
    if n:
        s += f" {n} follow-up action{'s' if n > 1 else ''} so far."
    return s


def photo_for(d, photos, section_fallback=True):
    pool = (photos.get("topics") or {}).get(d.get("topic")) or (photos.get(d["section"]) if section_fallback else None) or []
    if not pool:
        return None
    h = 7
    for ch in d["id"]:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return pool[h % len(pool)]


def img_url(p):
    return p["url"].replace("/1920px-", "/1280px-")


HERO = None   # hemicycle photo of the day, set in build()


def page(cfg, *, title, description, path, body, image=None, og_type="website", jsonld=None, css_v="19"):
    site = cfg["site"]
    base = site["url"].rstrip("/")
    url = f"{base}/{path}" if path else f"{base}/"
    image = image or f"{base}/og-image.png"
    ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:site_name" content="{e(site['name'])}">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{e(image)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/icon-192.png" sizes="192x192" type="image/png">
<link rel="icon" href="/favicon.ico" sizes="32x32">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="alternate" type="application/rss+xml" title="{e(site['name'])}" href="/feed.xml">
<link rel="stylesheet" href="/fonts.css?v={css_v}">
<link rel="stylesheet" href="/style.css?v={css_v}">
<style>
.static {{ max-width: 820px; margin: 0 auto; padding-bottom: 40px; }}
.static h1.hl {{ font-size: clamp(30px, 4.6vw, 46px); }}
.static .facts {{ list-style: none; padding: 0; margin: 22px 0; border-top: 1px solid var(--rule); }}
.static .facts li {{ display: flex; justify-content: space-between; gap: 18px; padding: 10px 0; border-bottom: 1px solid var(--rule); font: 500 14.5px/1.4 var(--sans); }}
.static .facts b {{ text-align: right; }}
.static .go {{ display: inline-block; background: var(--eu); color: #fff; font: 700 15px/1 var(--sans); padding: 15px 20px; border-radius: 4px; margin: 6px 0 20px; }}
.static .go:hover {{ background: #142a70; }}
.static .score {{ font: 800 44px/1 var(--serif-d); }}
.static ul.links {{ padding-left: 18px; }} .static ul.links li {{ margin: 6px 0; }}
.static ul.links a, .static p a {{ text-decoration: underline; text-underline-offset: 3px; }}
.static .official {{ font-size: 15px; color: var(--ink2); background: #f2eee4; padding: 14px 16px; border-left: 3px solid var(--rule-strong); }}
.static h2 {{ font: 800 13px/1 var(--sans); text-transform: uppercase; letter-spacing: .1em; margin: 30px 0 12px; padding-bottom: 8px; border-bottom: 2px solid var(--rule-strong); }}
.static .row-list a {{ display: block; padding: 10px 0; border-bottom: 1px solid var(--rule); }}
.static .row-list .hl {{ font-size: 19px; margin: 4px 0; }}
</style>
{ld}
<script data-goatcounter="https://thefollowthrough.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="hero" style="background-image:url('{e(HERO["url"]) if HERO else ""}')">
  <a href="/" class="seal" aria-label="The Follow-Through, front page"><img src="/seal.svg" alt="TFT seal"></a>
  <div class="plate title-plate"><a href="/" class="brand">{e(site['name'])}</a><div class="tagline">{e(site['tagline'])}</div></div>
  <div class="plate nav-plate"><nav class="sections"><div class="wrap"><a href="/">Front page</a><a href="/goals.html">Scorecard</a><a href="/coming.html">Coming up</a><a href="/#/search">Search</a>{''.join(f'<a href="/section/{s["id"]}.html">{e(s["name"])}</a>' for s in cfg["sections"])}</div></nav></div>
  {f'<div class="hero-credit">Photo: {e(HERO["author"])} / <a href="{e(HERO["source"])}" rel="noopener">{e(HERO["licence"])}</a></div>' if HERO else ""}
</header>
<main id="main" class="wrap static" style="padding-top:34px">
{body}
</main>
<footer class="foot"><div class="wrap"><div class="brand small">{e(site['name'])}</div>
<p>An independent tracker of EU decisions, built from the EU's official journal (EUR-Lex) and Eurostat statistics. Not affiliated with the European Union.</p>
<p><a href="/about.html" style="text-decoration:underline">About, sources and legal notice</a> · <a href="{ISSUES}" style="text-decoration:underline" rel="noopener">Report an error</a> · <a href="/feed.xml" style="text-decoration:underline">RSS feed</a> · Texts: CC BY-NC 4.0</p></div></footer>
</body>
</html>
"""


def decision_page(d, data, cfg, by_topic, today):
    targets = {t["id"]: t for t in data["targets"]}
    sec = {s["id"]: s for s in cfg["sections"]}[d["section"]]
    pct, label, why = score(d, targets, today)
    p = photo_for(d, data["photos"])
    desc = dek(d, today)
    rows = [("Adopted", dlong(d["date"])), ("Type", d["kind"]),
            ("Official reference", f'<a href="{eurlex(d["id"])}" rel="noopener">{e(d["ref"])}</a>')]
    if d.get("in_force"):
        rows.append(("In force", dlong(d["in_force"][0])))
    for k, v in milestones(d):
        if k > today:
            rows.append((v.split(" (")[0], dlong(k)))
    facts = "".join(f"<li><span>{e(a)}</span><b>{b if a == 'Official reference' else e(b)}</b></li>" for a, b in rows)
    extra = ""
    if d.get("ended"):
        x = d["ended"]
        by = (f' It was replaced by <a href="{eurlex(x["by"])}" rel="noopener">{e(x["by_ref"])}</a>.' if x.get("by") else "")
        extra += f'<p class="official"><b>No longer in force</b>{" since " + dlong(x["date"]) if x.get("date") else ""}.{by}</p>'
    if d.get("eu_summary"):
        x = d["eu_summary"]
        extra += (f'<h2>Summary</h2><p>{e(x["aim"])}</p>'
                  f'<p><a href="{e(x["url"])}" rel="noopener">Full summary on EUR-Lex</a></p>')
    if d.get("nat") is not None:
        cs = d["nat"].get("countries") or {}
        due = d["nat"].get("due")
        open_ = [x for x in d.get("infr") or [] if x["open"]]
        missing = [EU27[c] for c in sorted(EU27, key=EU27.get) if c not in cs]
        extra += (f'<h2>Across the 27 countries</h2><p><b>{len(cs)} of 27</b> countries have notified national measures to the European Commission.'
                  + (f' The deadline for national laws {"was" if due <= today else "is"} {dlong(due)}.' if due else "")
                  + (f' Not notified yet: {e(", ".join(missing))}.' if missing and len(missing) < 27 else "") + "</p>")
        if open_:
            extra += ('<p>Open infringement cases: ' + e("; ".join(f'{EU27.get(x["c"], x["c"])} ({x["stage"].lower()}, since {dlong(x["since"])})'
                                                              for x in sorted(open_, key=lambda x: EU27.get(x["c"], "")))) + ".</p>")
        extra += '<p class="caption">Sources: national transposition measures on EUR-Lex; European Commission infringement register.</p>'
    follow = d["links"].get("based_on", []) + d["links"].get("amended_by", [])
    follow_html = ("<h2>What came next</h2><ul class=\"links\">" + "".join(
        f'<li>{dlong(x["date"])}: <a href="{eurlex(x["id"])}" rel="noopener">{e(x.get("label") or x["id"])}</a></li>' for x in follow[:12]) + "</ul>") if follow else ""
    same = [x for x in by_topic.get(d.get("topic"), []) if x["id"] != d["id"]][:5] if d.get("topic") else []
    related = ("<h2>Related decisions</h2><div class=\"row-list\">" + "".join(
        f'<a href="/decision/{x["id"]}.html"><span class="kicker">{e(dlong(x["date"]))}</span><div class="hl">{e(x["headline"])}</div></a>' for x in same) + "</div>") if same else ""
    photo_html = (f'<img src="{e(img_url(p))}" alt="{e(p["title"])}" style="aspect-ratio:16/9;margin:18px 0 0">'
                  f'<div class="caption">Photo: {e(p["author"])} / <a href="{e(p["source"])}" rel="noopener">{e(p["licence"])}</a>, via Wikimedia Commons</div>') if p else ""
    base = cfg["site"]["url"].rstrip("/")
    body = f"""<div class="crumbs"><a href="/">Front page</a> › <a href="/section/{sec['id']}.html">{e(sec['name'])}</a></div>
<span class="kicker">{e(sec['name'])}<span class="k2">{e(d['kind'])} · {e(d['ref'])}</span></span>
<h1 class="hl">{e(d['headline'])}</h1>
<p class="dek" style="font-size:19px">{e(desc)}</p>
{photo_html}
<p style="margin-top:26px"><span class="kicker">{e("Status" if pct is None else label)}</span><br><span class="score">{e(label) if pct is None else f"{pct}%"}</span></p>
<p>{e(why)}</p>
<a class="go" href="/#/decision/{e(d['id'])}">See the progress chart, decision map and timeline →</a>
<ul class="facts">{facts}</ul>
<h2>The official title</h2>
<p class="official">{e(d['title'])}</p>
{extra}
{follow_html}
{related}"""
    ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": d["headline"][:110],
          "description": desc, "datePublished": d["date"], "dateModified": data["updated"],
          "image": [img_url(p) if p else f"{base}/og-image.png"],
          "author": {"@type": "Organization", "name": cfg["site"]["name"], "url": base + "/"},
          "publisher": {"@type": "Organization", "name": cfg["site"]["name"],
                        "logo": {"@type": "ImageObject", "url": f"{base}/icon-512.png"}},
          "isBasedOn": eurlex(d["id"]), "mainEntityOfPage": f"{base}/decision/{d['id']}.html"}
    return page(cfg, title=f"{d['headline']} | {cfg['site']['name']}", description=desc,
                path=f"decision/{d['id']}.html", body=body, image=img_url(p) if p else None, og_type="article", jsonld=ld)


def section_page(s, data, cfg):
    lst = [d for d in data["decisions"] if d["section"] == s["id"]]
    items, month = [], ""
    for d in lst:
        m = f"{MONTHS[int(d['date'][5:7]) - 1]} {d['date'][:4]}"
        if m != month:
            items.append(f"<h2>{m}</h2>")
            month = m
        items.append(f'<a href="/decision/{d["id"]}.html"><span class="kicker">{e(dlong(d["date"]))}<span class="k2">{e(d["kind"])}</span></span><div class="hl">{e(d["headline"])}</div></a>')
    body = f"""<div class="crumbs"><a href="/">Front page</a> › {e(s['name'])}</div>
<h1 class="hl">{e(s['name'])}</h1>
<p class="dek">{e(s.get('about', ''))}</p>
<p class="muted" style="font:500 14px var(--sans)">Every decision since {dlong(s.get('since') or data['since'])}: {len(lst)} in all, newest first. <a href="/#/section/{s['id']}">Open the interactive version →</a></p>
<div class="row-list">{''.join(items)}</div>"""
    return page(cfg, title=f"{s['name']}: every EU decision tracked | {cfg['site']['name']}",
                description=f"All {len(lst)} EU {s['name'].lower()} decisions since {dlong(data['since'])}, and whether each one is delivering.",
                path=f"section/{s['id']}.html", body=body)


def goals_page(data, cfg):
    cards = []
    for t in data["targets"]:
        cards.append(f"<li><span><b>{e(t['title'])}</b><br><small>Set by: {e(t.get('basis', ''))}</small></span><b>{t['progress']}% of the way</b></li>")
    body = f"""<div class="crumbs"><a href="/">Front page</a> › The Scorecard</div>
<h1 class="hl">The Scorecard</h1>
<p class="dek">The EU has set itself numbers to hit by 2030. We check each one against the latest official statistics from Eurostat, every day. <a href="/#/goals">See the charts →</a></p>
<ul class="facts">{''.join(cards)}</ul>"""
    return page(cfg, title=f"The Scorecard: is the EU on track for its 2030 goals? | {cfg['site']['name']}",
                description="Ten EU targets for 2030, from emissions to road deaths, checked daily against Eurostat data.",
                path="goals.html", body=body)


ISSUES = "https://github.com/thefollowthrough/thefollowthrough.github.io/issues"


def coming_page(data, cfg):
    secs = {s["id"]: s["name"] for s in cfg["sections"]}
    items = "".join(
        f'<a href="{e(x["url"])}" rel="noopener"><span class="kicker">{e(secs.get(x["section"], "EU law"))}<span class="k2">{e(x["ref"])} · {e(x["stage_label"])}</span></span>'
        f'<div class="hl">{e(x["headline"])}</div>'
        + (f'<span class="muted" style="font:500 13px var(--sans)">Parliament votes on {dlong(x["next_vote"])}</span>' if x.get("next_vote") else "")
        + "</a>" for x in data.get("coming", []))
    body = f"""<div class="crumbs"><a href="/">Front page</a> › Coming up</div>
<h1 class="hl">Coming up: EU laws in the works</h1>
<p class="dek">Laws still being negotiated between the European Parliament and EU governments, how far each one has got, and the next vote. <a href="/#/coming">Open the interactive version →</a></p>
<div class="row-list">{items}</div>"""
    return page(cfg, title=f"Coming up: EU laws in the works | {cfg['site']['name']}",
                description="Every EU law still being negotiated, its stage and the next vote in the European Parliament.",
                path="coming.html", body=body)


def about_page(data, cfg):
    body = f"""<div class="crumbs"><a href="/">Front page</a> › About</div>
<h1 class="hl">About The Follow-Through</h1>
<p class="dek">An independent, non-commercial tracker of EU decisions and of their implementation, based on official sources.</p>

<h2>What we do</h2>
<p>Every day, a program reads the EU's official journal and lists the main decisions taken since December 2019 (the last two years for foreign-policy decisions): laws passed by the European Parliament and the Council, Council regulations and directives, and foreign-policy decisions such as sanctions, missions and military aid. For each one we show its legal milestones (entry into force, deadlines), what came next (follow-up acts, reports, amendments, repeal), the EU's own plain-language summary when one exists, for directives which of the 27 countries have reported their national laws and whether the Commission has opened infringement cases, and, when it serves a measurable EU target, how far Europe is from that target according to official statistics.</p>
<p>The Follow-Through is <b>not affiliated with the European Union</b> or any of its institutions, and is not funded by any of them.</p>

<h2>How we score</h2>
<p><b>Goal progress</b>: when a decision serves a numbered EU target (for example, cutting greenhouse gas emissions by 55% by 2030), the score shows how far Europe has come between a starting year and the goal, using Eurostat data. “On track” compares the pace of the last ten years with the pace needed to reach the goal in time. See <a href="/goals.html">the Scorecard</a>.</p>
<p><b>Rollout</b>: otherwise, the score is the share of the decision's legal milestones that have already passed. It says whether a decision is in force, not whether it works.</p>

<h2>Sources</h2>
<ul class="links">
<li><b>Decisions</b>: EUR-Lex and the Publications Office of the European Union (Cellar database). © European Union. Reused under Commission Decision 2011/833/EU on the reuse of Commission documents.</li>
<li><b>National laws</b>: national transposition measures notified by EU countries, published on EUR-Lex. © European Union.</li>
<li><b>Official summaries</b>: Summaries of EU legislation, EUR-Lex. © European Union.</li>
<li><b>Infringement cases</b>: the European Commission's register of infringement decisions. © European Union.</li>
<li><b>Laws in negotiation</b>: European Parliament open data. © European Union.</li>
<li><b>Statistics</b>: Eurostat. © European Union.</li>
<li><b>Map</b>: Natural Earth (public domain).</li>
<li><b>Photographs</b>: Wikimedia Commons, each under the free licence and author named under the photo and in the page footer.</li>
</ul>

<h2>Limits and corrections</h2>
<p>Everything here is produced automatically, including the headlines, which are written by rules from the official titles. Mistakes are possible. This site is for general information only and is not legal advice: the official texts on EUR-Lex are the only authentic versions, and every decision page links to them.</p>
<p><b>Spotted an error, or want a photo removed?</b> Tell us by opening an issue on our public GitHub page: <a href="{ISSUES}" rel="noopener">github.com/thefollowthrough/thefollowthrough.github.io/issues</a> (a free GitHub account is needed). We correct errors as quickly as we can.</p>

<h2>Privacy</h2>
<ul class="links">
<li>No cookies, no advertising, no tracking across sites, no account to create.</li>
<li>We count visits with <a href="https://www.goatcounter.com" rel="noopener">GoatCounter</a>, an open-source tool that sets no cookie and stores no IP address or personal data. It records only the page visited, the referring site, the browser, the screen size and the country, in anonymous totals. The searches you type on this site are not sent.</li>
<li>Fonts are served from this site: your browser does not contact Google to display the page.</li>
<li>The site is hosted by GitHub Pages. Like any web host, GitHub records technical data such as IP addresses in its server logs (see the <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement" rel="noopener">GitHub privacy statement</a>).</li>
<li>Photographs are loaded from Wikimedia's servers, which therefore receive your IP address (see the <a href="https://foundation.wikimedia.org/wiki/Policy:Privacy_policy" rel="noopener">Wikimedia privacy policy</a>).</li>
<li>The “Share” button uses your device's own sharing menu or copies the link: nothing is sent to us.</li>
</ul>

<h2>Reusing our work</h2>
<p>Our texts (headlines, summaries, analyses) are published under the <a href="https://creativecommons.org/licenses/by-nc/4.0/" rel="noopener">Creative Commons BY-NC 4.0</a> licence: you may share and adapt them for non-commercial purposes, as long as you credit “The Follow-Through” with a link to this site. Commercial use requires our permission. EU data and the photographs keep their own licences, listed above.</p>

<h2 lang="fr">Mentions légales</h2>
<div lang="fr">
<p><b>Éditeur</b> : ce site est édité par un particulier, à titre non professionnel, qui a choisi de rester anonyme conformément à l'article 6, III, 2 de la loi n° 2004-575 du 21 juin 2004 pour la confiance dans l'économie numérique (LCEN). Ses coordonnées ont été communiquées à l'hébergeur.</p>
<p><b>Hébergeur</b> : GitHub, Inc., 88 Colin P. Kelly Jr. Street, San Francisco, CA 94107, États-Unis — <a href="https://support.github.com" rel="noopener">support.github.com</a>. Établissement européen : GitHub B.V., Prins Bernhardplein 200, 1097 JB Amsterdam, Pays-Bas.</p>
<p><b>Contact et signalements</b> : par une « issue » sur <a href="{ISSUES}" rel="noopener">la page GitHub du site</a>. Tout contenu illicite peut aussi être signalé à l'hébergeur.</p>
<p><b>Données personnelles</b> : le site ne dépose aucun cookie et ne collecte aucune donnée personnelle. La mesure d'audience (GoatCounter) est anonyme : sans cookie, sans conservation de l'adresse IP, elle ne produit que des statistiques globales et est donc exemptée de consentement. Voir la rubrique « Privacy » ci-dessus pour les données techniques traitées par l'hébergeur et par Wikimedia.</p>
<p><b>Propriété intellectuelle</b> : textes sous licence Creative Commons BY-NC 4.0 ; données de l'Union européenne © Union européenne ; photographies sous les licences libres indiquées pour chacune.</p>
<p><b>Indépendance</b> : site indépendant, sans lien avec l'Union européenne ni avec ses institutions.</p>
</div>"""
    return page(cfg, title=f"About and legal notice | {cfg['site']['name']}",
                description="Who we are, how we score EU decisions, our sources, how to report an error, privacy, and legal notice.",
                path="about.html", body=body)


def rss(data, cfg, today, limit=60):
    """feed.xml: the latest decisions as an RSS 2.0 feed (routine foreign-policy updates left out)."""
    from email.utils import format_datetime
    from datetime import datetime, timezone
    base = cfg["site"]["url"].rstrip("/")
    secs = {s["id"]: s["name"] for s in cfg["sections"]}
    pub = lambda s: format_datetime(datetime.fromisoformat(s[:10] + "T12:00:00").replace(tzinfo=timezone.utc))
    items = []
    for d in [x for x in data["decisions"] if x["kind"] != "Foreign policy update"][:limit]:
        url = f"{base}/decision/{d['id']}.html"
        items.append(f"""    <item>
      <title>{e(d.get('lead_hl') or d['headline'])}</title>
      <link>{e(url)}</link>
      <guid isPermaLink="true">{e(url)}</guid>
      <pubDate>{pub(d['date'])}</pubDate>
      <category>{e(secs.get(d['section'], ''))}</category>
      <description>{e(d.get('lead_dek') or dek(d, today))}</description>
    </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{e(cfg['site']['name'])}</title>
    <link>{base}/</link>
    <atom:link href="{base}/feed.xml" rel="self" type="application/rss+xml"/>
    <description>{e(cfg['site']['tagline'])} New EU decisions, and whether they deliver.</description>
    <language>en</language>
    <lastBuildDate>{pub(data['updated'])}</lastBuildDate>
    <image><url>{base}/icon-192.png</url><title>{e(cfg['site']['name'])}</title><link>{base}/</link></image>
{chr(10).join(items)}
  </channel>
</rss>
"""


def build(data=None, cfg=None):
    data = data or json.load(open(os.path.join(HERE, "data.json"), encoding="utf-8"))
    cfg = cfg or json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    today = date.today().isoformat()
    base = cfg["site"]["url"].rstrip("/")
    global HERO
    heads = data.get("photos", {}).get("masthead") or []
    HERO = heads[(date.today() - date(1970, 1, 1)).days % len(heads)] if heads else None
    by_topic = {}
    for d in data["decisions"]:
        by_topic.setdefault(d.get("topic"), []).append(d)

    os.makedirs(os.path.join(HERE, "decision"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "section"), exist_ok=True)
    keep = set()
    for d in data["decisions"]:
        if not re.fullmatch(r"[0-9A-Za-z_.-]+", d["id"]):
            continue
        name = f"{d['id']}.html"
        keep.add(name)
        with open(os.path.join(HERE, "decision", name), "w", encoding="utf-8") as f:
            f.write(decision_page(d, data, cfg, by_topic, today))
    for name in os.listdir(os.path.join(HERE, "decision")):   # decisions older than two years drop out
        if name.endswith(".html") and name not in keep:
            os.remove(os.path.join(HERE, "decision", name))
    for s in cfg["sections"]:
        with open(os.path.join(HERE, "section", f"{s['id']}.html"), "w", encoding="utf-8") as f:
            f.write(section_page(s, data, cfg))
    with open(os.path.join(HERE, "goals.html"), "w", encoding="utf-8") as f:
        f.write(goals_page(data, cfg))
    with open(os.path.join(HERE, "coming.html"), "w", encoding="utf-8") as f:
        f.write(coming_page(data, cfg))
    with open(os.path.join(HERE, "about.html"), "w", encoding="utf-8") as f:
        f.write(about_page(data, cfg))

    urls = [(f"{base}/", data["updated"], "daily", "1.0"), (f"{base}/goals.html", data["updated"], "daily", "0.8"),
            (f"{base}/coming.html", data["updated"], "daily", "0.8"),
            (f"{base}/about.html", data["updated"], "monthly", "0.4")]
    urls += [(f"{base}/section/{s['id']}.html", data["updated"], "daily", "0.7") for s in cfg["sections"]]
    urls += [(f"{base}/decision/{d['id']}.html", d["date"], "weekly", "0.6") for d in data["decisions"] if f"{d['id']}.html" in keep]
    with open(os.path.join(HERE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        f.write("".join(f"  <url><loc>{e(u)}</loc><lastmod>{m}</lastmod><changefreq>{c}</changefreq><priority>{p}</priority></url>\n" for u, m, c, p in urls))
        f.write("</urlset>\n")
    with open(os.path.join(HERE, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(rss(data, cfg, today))
    with open(os.path.join(HERE, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n")
    print(f"Pages: {len(keep)} decisions, {len(cfg['sections'])} sections, sitemap with {len(urls)} URLs")


if __name__ == "__main__":
    build()
