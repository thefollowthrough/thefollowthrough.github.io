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


def score(d, targets, today):
    if d.get("targets") and d["targets"][0] in targets:
        t = targets[d["targets"][0]]
        return t["progress"], "Goal progress", f"Europe is {t['progress']}% of the way to the goal this decision serves: “{t['short']}”."
    ms = milestones(d)
    passed = sum(1 for k, _ in ms if k <= today)
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
        s += f" In force since {dlong(d['in_force'][0])}."
    n = len(d["links"].get("based_on", []))
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


def page(cfg, *, title, description, path, body, image=None, og_type="website", jsonld=None, css_v="7"):
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
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;0,800;0,900;1,600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
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
</head>
<body>
<header class="masthead"><div class="wrap"><a href="/" class="brand">{e(site['name'])}</a><div class="tagline">{e(site['tagline'])}</div></div></header>
<nav class="sections"><div class="wrap"><a href="/">Front page</a><a href="/goals.html">Scorecard</a>{''.join(f'<a href="/section/{s["id"]}.html">{e(s["name"])}</a>' for s in cfg["sections"])}</div></nav>
<main class="wrap static">
{body}
</main>
<footer class="foot"><div class="wrap"><div class="brand small">{e(site['name'])}</div>
<p>An independent tracker of EU decisions, built from the EU's official journal (EUR-Lex) and Eurostat statistics. Not affiliated with the European Union.</p></div></footer>
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
    follow = d["links"].get("based_on", []) + d["links"].get("amended_by", [])
    follow_html = ("<h2>What came next</h2><ul class=\"links\">" + "".join(
        f'<li>{dlong(x["date"])}: <a href="{eurlex(x["id"])}" rel="noopener">{e(x.get("label") or x["id"])}</a></li>' for x in follow[:12]) + "</ul>") if follow else ""
    same = [x for x in by_topic.get(d.get("topic"), []) if x["id"] != d["id"]][:5] if d.get("topic") else []
    related = ("<h2>Related decisions</h2><div class=\"row-list\">" + "".join(
        f'<a href="/decision/{x["id"]}.html"><span class="kicker">{e(dlong(x["date"]))}</span><div class="hl">{e(x["headline"])}</div></a>' for x in same) + "</div>") if same else ""
    photo_html = (f'<img src="{e(img_url(p))}" alt="{e(p["title"])}" style="aspect-ratio:16/9;margin:18px 0 0">'
                  f'<div class="caption">Photo: {e(p["author"])} / <a href="{e(p["source"])}" rel="noopener">{e(p["licence"])}</a>, via Wikimedia Commons</div>') if p else ""
    base = cfg["site"]["url"].rstrip("/")
    body = f"""<div class="crumbs" style="margin-top:20px"><a href="/">Front page</a> › <a href="/section/{sec['id']}.html">{e(sec['name'])}</a></div>
<span class="kicker">{e(sec['name'])}<span class="k2">{e(d['kind'])} · {e(d['ref'])}</span></span>
<h1 class="hl">{e(d['headline'])}</h1>
<p class="dek" style="font-size:19px">{e(desc)}</p>
{photo_html}
<p style="margin-top:26px"><span class="kicker">{e(label)}</span><br><span class="score">{pct}%</span></p>
<p>{e(why)}</p>
<a class="go" href="/#/decision/{e(d['id'])}">See the progress chart, decision map and timeline →</a>
<ul class="facts">{facts}</ul>
<h2>The official title</h2>
<p class="official">{e(d['title'])}</p>
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
    body = f"""<div class="crumbs" style="margin-top:20px"><a href="/">Front page</a> › {e(s['name'])}</div>
<h1 class="hl">{e(s['name'])}</h1>
<p class="dek">Every {e(s['name'].lower())} decision the EU has taken since {dlong(data['since'])}: {len(lst)} in all, newest first. <a href="/#/section/{s['id']}">Open the interactive version →</a></p>
<div class="row-list">{''.join(items)}</div>"""
    return page(cfg, title=f"{s['name']}: every EU decision tracked | {cfg['site']['name']}",
                description=f"All {len(lst)} EU {s['name'].lower()} decisions since {dlong(data['since'])}, and whether each one is delivering.",
                path=f"section/{s['id']}.html", body=body)


def goals_page(data, cfg):
    cards = []
    for t in data["targets"]:
        cards.append(f"<li><span><b>{e(t['title'])}</b><br><small>Set by: {e(t.get('basis', ''))}</small></span><b>{t['progress']}% of the way</b></li>")
    body = f"""<div class="crumbs" style="margin-top:20px"><a href="/">Front page</a> › The Scorecard</div>
<h1 class="hl">The Scorecard</h1>
<p class="dek">The EU has set itself numbers to hit by 2030. We check each one against the latest official statistics from Eurostat, every day. <a href="/#/goals">See the charts →</a></p>
<ul class="facts">{''.join(cards)}</ul>"""
    return page(cfg, title=f"The Scorecard: is the EU on track for its 2030 goals? | {cfg['site']['name']}",
                description="Ten EU targets for 2030, from emissions to road deaths, checked daily against Eurostat data.",
                path="goals.html", body=body)


def build(data=None, cfg=None):
    data = data or json.load(open(os.path.join(HERE, "data.json"), encoding="utf-8"))
    cfg = cfg or json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    today = date.today().isoformat()
    base = cfg["site"]["url"].rstrip("/")
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

    urls = [(f"{base}/", data["updated"], "daily", "1.0"), (f"{base}/goals.html", data["updated"], "daily", "0.8")]
    urls += [(f"{base}/section/{s['id']}.html", data["updated"], "daily", "0.7") for s in cfg["sections"]]
    urls += [(f"{base}/decision/{d['id']}.html", d["date"], "weekly", "0.6") for d in data["decisions"] if f"{d['id']}.html" in keep]
    with open(os.path.join(HERE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        f.write("".join(f"  <url><loc>{e(u)}</loc><lastmod>{m}</lastmod><changefreq>{c}</changefreq><priority>{p}</priority></url>\n" for u, m, c, p in urls))
        f.write("</urlset>\n")
    with open(os.path.join(HERE, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n")
    print(f"Pages: {len(keep)} decisions, {len(cfg['sections'])} sections, sitemap with {len(urls)} URLs")


if __name__ == "__main__":
    build()
