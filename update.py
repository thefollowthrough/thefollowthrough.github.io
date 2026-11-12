#!/usr/bin/env python3
"""The Follow-Through: data pipeline.

Pulls every major EU decision of the last two years from EUR-Lex (Cellar SPARQL), sorts each
into a section, collects its milestones and follow-up acts, and adds Eurostat data for the
targets we track. Writes data.json, which the site reads.

New decisions are picked up automatically each time this runs (e.g. once a day).

Optional: with ANTHROPIC_API_KEY set, Claude writes a catchy headline, a plain-English summary
and picks the section for each new decision (cached in ai_cache.json, so each costs once).

Run:  python3 update.py
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
TODAY = date.today()
P = "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
ENG = "<http://publications.europa.eu/resource/authority/language/ENG>"
RT = "http://publications.europa.eu/resource/authority/resource-type/"


def http_json(url, data=None, headers=None, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                raise
            print("  retry after error:", e)
            time.sleep(5 * (i + 1))


def sparql(q):
    body = urllib.parse.urlencode({"query": P + q}).encode()
    d = http_json(SPARQL, data=body, headers={"Accept": "application/sparql-results+json"})
    return [{k: v["value"] for k, v in b.items()} for b in d["results"]["bindings"]]


# ---------------------------------------------------------------- 1. decisions
def fetch_decisions(start, end):
    types = ",".join(f"<{RT}{t}>" for t in ("REG", "DIR", "DEC"))
    q = f"""SELECT ?celex ?date ?title
  (GROUP_CONCAT(DISTINCT STR(?dc); separator=" ") AS ?codes)
  (GROUP_CONCAT(DISTINCT STR(?eif); separator=" ") AS ?eifs)
  (GROUP_CONCAT(DISTINCT STR(?dl); separator=" ") AS ?deadlines)
WHERE {{
  ?w cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?date ; cdm:work_has_resource-type ?type .
  FILTER(?type IN ({types}))
  FILTER(?date >= "{start}"^^xsd:date && ?date < "{end}"^^xsd:date)
  FILTER(STRSTARTS(?celex, "3") && !CONTAINS(?celex, "("))
  ?e cdm:expression_belongs_to_work ?w ; cdm:expression_title ?title ; cdm:expression_uses_language {ENG} .
  FILTER(
    CONTAINS(SUBSTR(?title, 1, 130), "of the European Parliament and of the Council")
    || STRSTARTS(?title, "Council Regulation (EU)") || STRSTARTS(?title, "Council Directive (EU)")
    || STRSTARTS(?title, "Council Decision (CFSP)")
  )
  FILTER(!CONTAINS(?title, "Corrigendum"))
  OPTIONAL {{ ?w cdm:resource_legal_is_about_concept_directory-code ?dc }}
  OPTIONAL {{ ?w cdm:resource_legal_date_entry-into-force ?eif }}
  OPTIONAL {{ ?w cdm:resource_legal_date_deadline ?dl }}
}} GROUP BY ?celex ?date ?title"""
    return sparql(q)


def follow_ups(celexes):
    """Acts and documents linked to each decision after its adoption."""
    vals = " ".join(f'"{c}"^^xsd:string' for c in celexes)
    q = f"""SELECT ?parent ?rel ?celex ?date ?title WHERE {{
  VALUES ?parent {{ {vals} }}
  ?p cdm:resource_legal_id_celex ?parent .
  {{ ?w cdm:resource_legal_based_on_resource_legal ?p . BIND("based_on" AS ?rel) }}
  UNION {{ ?w cdm:resource_legal_amends_resource_legal ?p . BIND("amended_by" AS ?rel) }}
  UNION {{ ?p cdm:resource_legal_amends_resource_legal ?w . BIND("changes" AS ?rel) }}
  ?w cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?date .
  FILTER(!CONTAINS(?celex, "("))
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?w ; cdm:expression_title ?title ; cdm:expression_uses_language {ENG} . }}
}}"""
    return sparql(q)


# ---------------------------------------------------------------- 2. text helpers
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def subject_of(title):
    t = re.sub(r"\s*\(Text with EEA relevance\)\s*", " ", title).strip().rstrip(".")
    m = re.search(rf"\b\d{{1,2}} (?:{MONTHS}) \d{{4}}\s+(.*)$", t)
    return m.group(1) if m else t


def reference(title):
    m = re.search(r"(Regulation|Directive|Decision)(?: \((?:EU|CFSP|EU, Euratom)\))? (\d{4}/\d+)", title)
    return f"{m.group(1)} {m.group(2)}" if m else title[:40]


def is_update(title):
    """A foreign-policy decision that changes an earlier one (sanctions lists, mission mandates, aid budgets)."""
    return "(CFSP)" in title[:40] and bool(re.match(r"amending |updating ", subject_of(title), re.I))


def kind_of(title):
    if "European Parliament and of the Council" in title[:130]:
        return "EU law"
    if is_update(title):
        return "Foreign policy update"
    if "(CFSP)" in title[:40]:
        return "Foreign policy decision"
    return "Council act"


def tidy(s, n=105):
    s = re.sub(r"\s+", " ", s).strip(" ,;")
    s = re.split(r",? and (?:amending|repealing|correcting) |,? amending (?:Council )?(?:Regulation|Directive|Decision)s? ", s)[0]
    s = re.sub(r"^(?:the|a|an) ", "", s)
    if len(s) > n:
        s = s[:n].rsplit(" ", 1)[0] + "…"
    return s[0].upper() + s[1:] if s else s


REF = r"(?:Council |Commission )?(?:Implementing |Delegated )?(?:Regulations?|Directives?|Decisions?)(?: \((?:EU|EC|CFSP|EU, Euratom)\))?(?: No)? \d+(?:/\d+)*(?:/(?:EC|EU|EEC|CFSP))?(?:,? (?:and )?(?:\((?:EU|EC)\) )?(?:No )?\d+(?:/\d+)*(?:/(?:EC|EU|EEC))?)*"


# who the sanctions regimes are aimed at, in plain words (checked in this order)
SANCTION_TARGETS = [
    ("illegal recognition, occupation or annexation", "Russian-occupied areas of Ukraine"),
    ("annexation of Crimea", "Crimea and Sevastopol"),
    ("military support to Russia", "Iran over arms for Russia"),
    ("Belarus", "Belarus"),
    ("Transnistrian", "Transnistria's leaders"),
    ("Moldova", "those destabilising Moldova"),
    ("Russia’s destabilising activities", "Russia's hybrid attacks"),
    ("Russia's destabilising activities", "Russia's hybrid attacks"),
    ("situation in Russia", "Russia over human rights"),
    ("bodies in view of the situation in Ukraine", "former Ukrainian officials over stolen funds"),
    ("Ukraine", "Russia over the war in Ukraine"),
    ("human rights violations", "human rights abusers worldwide"),
    ("cyber-attacks", "cyber-attackers"),
    ("chemical weapons", "chemical weapons users"),
    ("ISIL", "ISIL (Da'esh) and Al-Qaeda"),
    ("Hamas", "Hamas and Palestinian Islamic Jihad"),
    ("terrorism", "terrorist groups"),
    ("Türkiye", "Türkiye over drilling off Cyprus"),
    ("Democratic People", "North Korea"),
    ("Republic of the Congo", "DR Congo"),
    ("Myanmar", "Myanmar"),
    ("Sudan", "Sudan"),
]


def update_headline(s):
    """Neutral headline for a decision that changes an earlier one: the title says what is changed, not how."""
    if "restrictive measures" in s or "specific measures to combat terrorism" in s:
        who = next((w for k, w in SANCTION_TARGETS if k.lower() in s.lower()), None)
        if not who:
            rest = s.split("restrictive measures", 1)[-1]
            rest = rest.rsplit("situation in ", 1)[-1] if "situation in " in rest else re.sub(r"^\s*(?:against|in view of|concerning|directed against) ", "", rest)
            m = re.match(r"\s*(?:the )?(.*?)(?: and the |,|$)", rest)
            who = tidy(m.group(1), 50) if m and m.group(1) else "an existing regime"
        return f"Sanctions update: {who}"
    if "European Peace Facility" in s:
        if re.search(r"establishing a European Peace Facility\s*$", s):
            return "Rules of the European Peace Facility (EU military aid fund) changed"
        m = re.search(r"(?:to support|support to|for the supply to|capacities of) (?:the )?(.*?)(?: with | in | of military|,|$)", s)
        return f"Military aid update: {tidy(m.group(1), 70) if m else 'European Peace Facility'}"
    m = re.search(r"Special Representative for (?:the )?(.*?)(?:,|$)", s)
    if m:
        return f"EU envoy update: {tidy(m.group(1), 70)}"
    if re.search(r"mission|operation", s, re.I):
        acr = re.findall(r"\((EU[^)]*)\)", s)
        m = re.search(r"((?:European Union|Union) [^,(]*?(?:[Mm]ission|[Oo]peration)[^,(]*)", s)
        name = acr[-1] if acr else tidy(re.sub(r"^(?:European )?Union ", "EU ", m.group(1)), 70) if m else "an EU mission"
        return f"Mission update: {name}"
    rest = re.sub(r"^(?:amending|updating) (?:Council )?(?:Joint Action|Decision|Common Position)s? (?:\(CFSP\) )?[\d/]+(?:/CFSP)?\s*", "", s)
    rest = re.sub(r"^(?:on|concerning) (?:a |an |the )?", "", rest)
    return "Foreign policy update: " + lower1(tidy(rest or s, 80))


def headline(title):
    """Readable headline from the official title (used when no AI headline is available)."""
    s = subject_of(title)
    if is_update(title):
        return update_headline(s)
    low = s.lower()
    rules = [
        (r"restrictive measures (?:in view of the situation in|in view of|in respect of|against|concerning) (?:the )?(.*?)(?: and the involvement| and |,|$)",
         lambda m: f"New sanctions round targets {tidy(m.group(1), 60)}"),
        (r"restrictive measures", lambda m: "EU updates its sanctions list"),
        (r"European Peace Facility to support (?:the )?(.*?)(?: with | in |$)",
         lambda m: f"Military aid: EU backs {tidy(m.group(1), 70)}"),
        (r"Globalisation Adjustment Fund.*?application from (\w+)(?:.*?/([A-Z][\w ]+?)(?: \d|$))?",
         lambda m: f"EU fund steps in for laid-off workers in {m.group(1)}" + (f" ({m.group(2).strip()})" if m.group(2) else "")),
        (r"Solidarity Fund to provide assistance to (.*?)(?: regarding| following| in |$)",
         lambda m: f"Disaster aid: EU sends money to {tidy(m.group(1), 50)}"),
        (r"financial assistance .*?available to (.*)", lambda m: f"EU money released to {tidy(m.group(1), 60)}"),
        (r"fixing for ([\d, and]+) the fishing opportunities", lambda m: f"Fishing quotas set for {m.group(1)}"),
        (r"fishing opportunities", lambda m: "Fishing quotas adjusted"),
        (r"tariff quotas|customs tariff duties", lambda m: "Customs duties adjusted for selected imports"),
        (r"^appointing (?:the )?(.*)", lambda m: f"EU names new {tidy(m.group(1), 80)}"),
        (r"^in support of (.*)", lambda m: f"EU backs {tidy(m.group(1), 90)}"),
        (r"^(?:on )?(?:a |an |the )?(European Union .*?mission.*)", lambda m: f"EU launches {tidy(m.group(1), 90)}"),
        (r"^(?:on )?(?:the )?conclusion(?:, on behalf of the (?:European )?Union,)? of (?:the )?(.*)", lambda m: f"EU seals {tidy(m.group(1), 90)}"),
        (r"^(?:on )?(?:the )?signing(?:, on behalf of the (?:European )?Union,)? of (?:the )?(.*)", lambda m: f"EU signs {tidy(m.group(1), 90)}"),
    ]
    for pat, fn in rules:
        m = re.search(pat, s, re.I)
        if m:
            return fn(m)
    m = re.match(r"amending .*? as regards (?:the )?(.*)", s, re.I)
    if m:
        return "Rules rewritten: " + tidy(re.sub(r"^(?:the )?(?:setting|establishment|introduction) of (?:a |an |the )?", "", m.group(1)), 95)
    if low.startswith("amending"):
        rest = re.sub(r"^amending " + REF + r"\s*", "", s)
        rest = re.sub(r"^(?:on|concerning|establishing|laying down|relating to) (?:a |an |the )?", "", rest)
        rest = re.split(r", (?:Council )?(?:Directive|Regulation|Decision) ", rest)[0]
        return "Rules rewritten: " + tidy(rest or s, 95)
    m = re.match(r"^(?:on )?establishing (?:a |an |the )?(.*)", s, re.I)
    if m:
        return "EU creates " + lower1(tidy(m.group(1), 95))
    m = re.match(r"^laying down (.*)", s, re.I)
    if m:
        return "EU sets " + lower1(tidy(m.group(1), 95))
    m = re.match(r"^(?:on|concerning|relating to) (?:the |a |an )?(.*)", s, re.I)
    if m:
        return ("New EU law: " if kind_of(title) == "EU law" else "EU decides: ") + lower1(tidy(m.group(1), 95))
    return tidy(s)


def lower1(s):
    words = s.split()
    proper = len(words) > 1 and words[1][:1].isupper()
    return s if not s or proper or s[:2].isupper() or s.startswith(("European", "Union", "EU ")) else s[0].lower() + s[1:]


# ---------------------------------------------------------------- 3. sections
def classify(title, codes, cfg):
    secs = {s["id"]: s for s in cfg["sections"]}
    hits = set()
    for c in codes:
        for s in cfg["sections"]:
            if any(c.startswith(x) for x in s["codes"]):
                hits.add(s["id"])
    if not hits:
        low = subject_of(title).lower()
        for s in cfg["sections"]:
            if any(k.lower() in low for k in s["keywords"]):
                hits.add(s["id"])
    if not hits:
        return None, []
    ordered = [p for p in cfg["priority"] if p in hits]
    # if the title clearly names a section, prefer it
    low = subject_of(title).lower()
    for p in ordered:
        if any(k.lower() in low for k in secs[p]["keywords"]):
            return p, ordered
    return ordered[0], ordered


def topic_of(headline, title, cfg):
    """Photo topic of a decision (config.json > photo_topics): the headline is checked first, then the full title."""
    for text in (headline, headline + " | " + subject_of(title)):
        for t in cfg.get("photo_topics", []):
            if re.search(t["match"], text, re.I):
                return t["id"]
    return None


# ---------------------------------------------------------------- 4. AI (optional)
def ai_enrich(d, cfg):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    sections = ", ".join(f'{s["id"]} ({s["name"]})' for s in cfg["sections"])
    prompt = f"""You write for "The Follow-Through", a news site that tracks whether EU decisions deliver.
Official title of an EU decision: {d['title']}

Reply with JSON only:
{{"headline": "catchy but accurate newspaper headline, max 12 words, no clickbait",
 "summary": "2 short sentences in plain English: what it does and who it affects",
 "section": "one id from: {sections}"}}"""
    body = json.dumps({"model": "claude-haiku-5-5", "max_tokens": 400,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    try:
        r = http_json("https://api.anthropic.com/v1/messages", data=body, tries=2, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        txt = r["content"][0]["text"]
        return json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
    except Exception as e:
        print("  (AI skipped:", e, ")")
        return None


# ---------------------------------------------------------------- 5. targets (Eurostat)
def eurostat(dataset, **params):
    params["format"] = "JSON"
    d = http_json(EUROSTAT + dataset + "?" + urllib.parse.urlencode(params))
    years = list(d["dimension"]["time"]["category"]["index"])
    var = next((k for k, s in zip(d["id"], d["size"]) if s > 1 and k != "time"), None)
    codes = list(d["dimension"][var]["category"]["index"]) if var else ["_"]
    n = len(years)
    return {c: {int(y): round(d["value"][str(i * n + j)], 2) for j, y in enumerate(years) if str(i * n + j) in d["value"]}
            for i, c in enumerate(codes)}


EU27 = ["BE", "BG", "CZ", "DK", "DE", "EE", "IE", "EL", "ES", "FR", "HR", "IT", "CY", "LV", "LT", "LU",
        "HU", "MT", "NL", "AT", "PL", "PT", "RO", "SI", "SK", "FI", "SE"]


def eurostat_cube(dataset, **params):
    """Raw Eurostat query returning {(code of each dimension...): value}, for multi-dimension needs."""
    q = urllib.parse.urlencode({**params, "format": "JSON"}, doseq=True)
    d = http_json(EUROSTAT + dataset + "?" + q)
    cats = [list(d["dimension"][k]["category"]["index"]) for k in d["id"]]
    out = {}
    for k, v in d["value"].items():
        i, idx = int(k), []
        for s in reversed(d["size"]):
            idx.append(i % s)
            i //= s
        out[tuple(c[j] for c, j in zip(cats, reversed(idx)))] = v
    return d["id"], out


def organic_share():
    """Eurostat stopped publishing the EU total after 2020, so we rebuild it from the 27 countries:
    organic hectares / farmland hectares (farmland = organic ha / organic share). A country missing
    a year keeps its latest known figures."""
    ids, cube = eurostat_cube("org_cropar", geo=EU27, crops="UAAXK0000", agprdmet="TOTAL", unit=["HA", "PC_UAA"])
    gi, ui, ti = ids.index("geo"), ids.index("unit"), ids.index("time")
    data = {}
    for key, v in cube.items():
        data.setdefault(key[gi], {}).setdefault(int(key[ti]), {})[key[ui]] = v
    years = sorted({y for g in data.values() for y in g})
    out, last = {}, {}
    for y in years:
        for g in EU27:
            row = data.get(g, {}).get(y, {})
            if row.get("HA") and row.get("PC_UAA"):
                last[g] = (row["HA"], row["HA"] * 100 / row["PC_UAA"])
        fresh = sum(1 for g in EU27 if data.get(g, {}).get(y, {}).get("HA"))
        if len(last) == 27 and fresh >= 24:   # only years most countries have reported
            out[y] = round(sum(a for a, _ in last.values()) / sum(b for _, b in last.values()) * 100, 2)
    return out


def pace(series, start, target, target_year):
    ys = sorted(series)
    ly = ys[-1]
    done = series[ly] - start
    need = target - start
    first = ly - 10 if ly - 10 in series else min(y for y in ys if y >= ly - 10)
    real_rate = (series[ly] - series[first]) / max(1, ly - first)
    need_rate = (target - series[ly]) / max(1, target_year - ly)
    return {"progress": round(max(0, min(1, done / need)) * 100), "last_year": ly,
            "real_rate": round(real_rate, 3), "need_rate": round(need_rate, 3)}


def target_data(cfg_targets):
    """Fetch the Eurostat series of every target in config.json and work out progress and pace."""
    out = {}
    for t in cfg_targets:
        spec = t["data"]
        try:
            sectors = None
            if spec.get("calc") == "ghg_net":
                gge = eurostat("env_air_gge", geo="EU27_2020", unit="MIO_T", airpol="GHG")
                series = {y: round(v + gge["CRF1D1A"].get(y, 0), 1) for y, v in gge["TOTXMEMO"].items()}
                sectors = {name: gge[c] for c, name in (("CRF1A1", "Power plants"), ("CRF1A3", "Transport"), ("CRF1A4", "Buildings"),
                                                         ("CRF2", "Industry"), ("CRF3", "Farming"), ("CRF5", "Waste")) if c in gge}
                source = "Eurostat env_air_gge"
            elif spec.get("calc") == "organic":
                series, source = organic_share(), "Eurostat org_cropar (EU total computed from the 27 countries)"
            else:
                series = next(iter(eurostat(spec["dataset"], geo="EU27_2020", **spec["filters"]).values()))
                source = "Eurostat " + spec["dataset"]
            scale = spec.get("scale", 1)
            series = {y: round(v * scale, 3) for y, v in series.items()}
            start = series[t["start_year"]]
            if "goal_change" in t:
                goal = start * (1 + t["goal_change"] / 100)
            elif "goal_delta" in t:
                goal = start + t["goal_delta"]
            else:
                goal = t["goal"]
            later = t.get("later", [])
            if t["id"] == "ghg2030":
                later = [{"year": 2040, "value": round(start * 0.10, 1), "label": "−90% (2040)"},
                         {"year": 2050, "value": 0, "label": "Net zero (2050)"}]
            out[t["id"]] = {"source": source, "series": series, "start": start, "goal": round(goal, 3),
                            "goal_year": 2030, "later": later, **pace(series, start, goal, 2030),
                            **({"sectors": sectors} if sectors else {})}
        except Exception as e:   # one broken dataset must not stop the daily update
            print(f"  target {t['id']} skipped: {e}")
    return out


# ---------------------------------------------------------------- main
def main():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    start = TODAY.replace(year=TODAY.year - cfg["site"]["years_back"])
    cache_path = os.path.join(HERE, "ai_cache.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}

    print("EUR-Lex: decisions since", start)
    rows, cur = [], start
    while cur <= TODAY:
        nxt = min(cur + timedelta(days=120), TODAY + timedelta(days=1))
        part = fetch_decisions(cur.isoformat(), nxt.isoformat())
        print(f"  {cur} → {nxt}: {len(part)}")
        rows += part
        cur = nxt
    seen, decisions = set(), []
    for r in sorted(rows, key=lambda r: r["date"], reverse=True):
        c = r["celex"]
        if c in seen:
            continue
        seen.add(c)
        codes = r.get("codes", "").replace("http://publications.europa.eu/resource/authority/dir-eu-legal-act/", "").split()
        section, also = classify(r["title"], codes, cfg)
        d = {"id": c, "date": r["date"], "title": r["title"], "ref": reference(r["title"]), "kind": kind_of(r["title"]),
             "headline": headline(r["title"]), "summary": None, "section": section, "also": also,
             "in_force": sorted(set(r.get("eifs", "").split())), "deadlines": sorted(set(r.get("deadlines", "").split()))}
        if c not in cache:
            ai = ai_enrich(d, cfg)
            if ai:
                cache[c] = ai
        if c in cache:
            d["headline"] = cache[c].get("headline") or d["headline"]
            d["summary"] = cache[c].get("summary")
            if cache[c].get("section") in {s["id"] for s in cfg["sections"]}:
                d["section"] = cache[c]["section"]
        d["topic"] = topic_of(d["headline"], d["title"], cfg)
        if d["section"]:
            decisions.append(d)
    json.dump(cache, open(cache_path, "w"), ensure_ascii=False, indent=1)

    print("EUR-Lex: follow-up acts for", len(decisions), "decisions")
    by_id = {d["id"]: d for d in decisions}
    for d in decisions:
        d["links"] = {"based_on": [], "amended_by": [], "changes": []}
    ids = list(by_id)
    for i in range(0, len(ids), 40):
        for r in follow_ups(ids[i:i + 40]):
            d = by_id[r["parent"]]
            item = {"id": r["celex"], "date": r["date"], "title": r.get("title", "")}
            if item["id"] not in {x["id"] for x in d["links"][r["rel"]]}:
                d["links"][r["rel"]].append(item)
    for d in decisions:
        for k in d["links"]:
            d["links"][k].sort(key=lambda x: x["date"], reverse=True)
            for x in d["links"][k]:
                x["label"] = headline(x["title"]) if x["title"] else x["id"]
                x["ref"] = reference(x["title"]) if x["title"] else x["id"]
                x["type"] = "act" if x["id"].startswith("3") else "document"

    print("Eurostat: targets")
    tdata = target_data(cfg["targets"])
    targets = [{**{k: v for k, v in t.items() if k not in ("data", "keywords")}, **tdata[t["id"]]}
               for t in cfg["targets"] if t["id"] in tdata]

    # targets each decision feeds into: same section + keyword in the title, best match first
    for d in decisions:
        low = subject_of(d["title"]).lower()
        hits = []
        for i, t in enumerate(cfg["targets"]):
            n = sum(1 for k in t["keywords"] if k.lower() in low)
            if n and d["section"] == t["section"] and t["id"] in tdata:
                hits.append((-n, i, t["id"]))
        d["targets"] = [x[2] for x in sorted(hits)]

    photos = json.load(open(os.path.join(HERE, "photos.json"))) if os.path.exists(os.path.join(HERE, "photos.json")) else {}
    out = {"site": cfg["site"], "updated": TODAY.isoformat(), "since": start.isoformat(),
           "sections": [{k: s[k] for k in ("id", "name", "kicker")} for s in cfg["sections"]],
           "targets": targets, "decisions": decisions, "photos": photos}
    with open(os.path.join(HERE, "data.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    per = {}
    for d in decisions:
        per[d["section"]] = per.get(d["section"], 0) + 1
    print(f"Done: {len(decisions)} decisions →", per)


if __name__ == "__main__":
    sys.exit(main())
