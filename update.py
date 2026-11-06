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
    || (STRSTARTS(?title, "Council Decision (CFSP)") && !CONTAINS(SUBSTR(?title, 1, 90), "amending"))
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


def kind_of(title):
    if "European Parliament and of the Council" in title[:130]:
        return "EU law"
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


def headline(title):
    """Readable headline from the official title (used when no AI headline is available)."""
    s = subject_of(title)
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


def target_data():
    gge = eurostat("env_air_gge", geo="EU27_2020", unit="MIO_T", airpol="GHG")
    net = {y: round(v + gge["CRF1D1A"].get(y, 0), 1) for y, v in gge["TOTXMEMO"].items()}
    base = net[1990]
    ren = next(iter(eurostat("nrg_ind_ren", geo="EU27_2020", nrg_bal="REN", unit="PC").values()))

    def pace(series, start, target, target_year):
        ys = sorted(series)
        ly = ys[-1]
        done = series[ly] - start
        need = target - start
        real_rate = (series[ly] - series[ly - 10 if ly - 10 in series else ys[0]]) / min(10, ly - ys[0])
        need_rate = (target - series[ly]) / (target_year - ly)
        return {"progress": round(max(0, min(1, done / need)) * 100), "last_year": ly,
                "real_rate": round(real_rate, 2), "need_rate": round(need_rate, 2)}

    sectors = {name: gge[c] for c, name in (("CRF1A1", "Power plants"), ("CRF1A3", "Transport"), ("CRF1A4", "Buildings"),
                                             ("CRF2", "Industry"), ("CRF3", "Farming"), ("CRF5", "Waste")) if c in gge}
    return {
        "ghg2030": {
            "unit": "Mt CO₂e", "label": "EU net greenhouse gas emissions", "source": "Eurostat env_air_gge",
            "series": net, "start": base, "goal": round(base * 0.45, 1), "goal_year": 2030,
            "later": [{"year": 2040, "value": round(base * 0.10, 1), "label": "−90% (2040)"}, {"year": 2050, "value": 0, "label": "Net zero (2050)"}],
            "sectors": sectors, **pace(net, base, base * 0.45, 2030)},
        "ren2030": {
            "unit": "%", "label": "Share of renewables in EU energy use", "source": "Eurostat nrg_ind_ren",
            "series": ren, "start": ren[min(ren)], "goal": 42.5, "goal_year": 2030, "later": [],
            **pace(ren, ren[min(ren)], 42.5, 2030)},
    }


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

    # targets each decision feeds into
    for d in decisions:
        low = subject_of(d["title"]).lower()
        d["targets"] = [t["id"] for t in cfg["targets"]
                        if d["section"] == t["section"] and any(k.lower() in low for k in t["keywords"])]

    print("Eurostat: targets")
    tdata = target_data()
    targets = [{**t, **tdata[t["id"]]} for t in cfg["targets"]]

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
