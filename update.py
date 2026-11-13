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
    t = re.sub(r"\s+", " ", title.replace("\xa0", " "))   # older titles use non-breaking spaces
    t = re.sub(r"\s*\(Text with EEA relevance\)\s*", " ", t).strip().rstrip(".")
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
    ("Russia’s destabilizing activities", "Russia's hybrid attacks"),
    ("Russia's destabilizing activities", "Russia's hybrid attacks"),
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


def sanction_target(s):
    """Plain-words name of who a sanctions regime targets, or None."""
    return next((w for k, w in SANCTION_TARGETS if k.lower() in s.lower()), None)


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
         lambda m: f"EU sanctions decision: {sanction_target(s) or tidy(m.group(1), 60)}"),
        (r"restrictive measures", lambda m: f"EU sanctions decision: {sanction_target(s)}" if sanction_target(s) else "EU sanctions decision"),
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


# ---------------------------------------------------------------- front-page headlines (no AI)
# The lead story of the day (Security & Defence, Migration, Trade) gets a proper newspaper headline
# and a short explanation. These templates only state what the official title says, plus short,
# stable background facts about some countries.
CONTEXT = {
    "Mauritania": "Mauritania borders Mali, where armed jihadist groups are active.",
    "Nigeria": "Nigeria is fighting armed jihadist groups in its north-east.",
    "Togo": "Jihadist violence from the Sahel has been spreading towards coastal West Africa.",
    "Togolese": "Jihadist violence from the Sahel has been spreading towards coastal West Africa.",
    "Benin": "Jihadist violence from the Sahel has been spreading towards coastal West Africa.",
    "Beninese": "Jihadist violence from the Sahel has been spreading towards coastal West Africa.",
    "Ivoire": "Jihadist violence from the Sahel has been spreading towards coastal West Africa.",
    "Moldova": "Moldova, an EU candidate country, borders Ukraine.",
    "Lebanon": "Lebanon borders Israel and Syria.",
    "Lebanese": "Lebanon borders Israel and Syria.",
    "Libya": "Libya has been split between rival governments for over a decade.",
    "Belarus": "Belarus let Russia use its territory to invade Ukraine in 2022.",
    "Congo": "Eastern Congo has seen heavy fighting involving the M23 armed group.",
}
LEAD_FIXED = [  # (pattern in the official subject, headline, explanation)
    (r"agile and rapid defence innovation", "EU launches AGILE to fast-track new defence technology",
     "A new EU programme is meant to get innovative defence products from the lab to the armed forces faster."),
    (r"Defence readiness and facilitating defence investments", "EU cuts red tape to speed up defence investment",
     "Parliament and governments changed several EU rules at once so that money can flow to defence projects more quickly."),
    (r"permit-granting processes for defence readiness", "EU fast-tracks permits for defence projects",
     "A new law shortens the paperwork for building factories, depots and other defence projects."),
    (r"intra-EU transfers of defence-related products", "EU makes it easier to move military equipment between its countries",
     "Simpler rules for sending defence products from one EU country to another."),
    (r"Security Action for Europe", "EU creates SAFE: €150 billion in loans to rearm Europe",
     "The EU will borrow on the markets and lend to member states that buy defence equipment together."),
    (r"European Defence Industry Programme", "EU launches a programme to boost Europe's arms industry",
     "Money and rules meant to help European companies produce more weapons and ammunition, faster."),
    (r"Ukraine Support Loan", "EU agrees a new support loan for Ukraine",
     "A group of EU countries set up a loan to keep Ukraine's state running and defended."),
    (r"Ukraine Facility", "EU changes the rules of its Ukraine aid fund",
     "Changes to the Ukraine Facility, the EU fund that pays for Ukraine's recovery and reforms."),
    (r"Space Threat Response Architecture", "EU sets up a system to respond to threats in space",
     "A framework for how the EU reacts when its satellites or space services are threatened."),
    (r"return of third-country nationals", "EU agrees one system to send back people with no right to stay",
     "A new EU law replaces 27 different national approaches with common rules for returning non-EU citizens who are staying illegally."),
    (r"safe countries of origin", "EU agrees a common list of 'safe countries' for asylum claims",
     "Asylum requests from people coming from countries on the list can be handled faster."),
    (r"safe third country", "EU rewrites the 'safe third country' rule for asylum",
     "The rule decides when an asylum seeker can be sent to another country outside the EU to have their claim examined."),
    (r"Talent Pool", "EU creates a Talent Pool to recruit workers from outside Europe",
     "An EU-wide platform to match employers with job seekers from non-EU countries."),
    (r"combatting corruption", "EU agrees common rules to fight corruption",
     "The same definitions and minimum penalties for corruption offences across the EU."),
    (r"suspension mechanism", "EU makes it easier to suspend visa-free travel",
     "New grounds for suspending visa-free travel for countries whose citizens can visit the EU without a visa."),
    (r"advance passenger information", "Airlines will have to share passenger data with border authorities",
     "Passenger details collected before flights will be sent to border and police authorities."),
    (r"victims of crime", "EU strengthens the rights of victims of crime",
     "Updated minimum standards for the support and protection of crime victims."),
    (r"Europol", "EU gives Europol a bigger role against migrant smuggling",
     "More support from the EU police agency for national police forces."),
    (r"identity cards", "EU tightens the security of ID cards",
     "Common security standards for national identity cards and residence documents."),
    (r"transfer of proceedings in criminal matters", "EU countries will be able to hand criminal cases to each other",
     "Rules for moving a prosecution to the EU country best placed to handle it."),
    (r"Customs Authority", "EU creates its own customs authority to police imports",
     "A single EU customs authority and a shared data hub will oversee the goods entering Europe, from container ships to small online parcels."),
    (r"overcapacity on the Union steel market", "EU shields its steel industry from cheap imports",
     "New limits on steel imports, as global overproduction pushes cheap steel onto the European market."),
    (r"safeguard clauses of the EU-Mercosur", "EU sets an emergency brake for imports under the Mercosur deal",
     "The rules for pausing tariff cuts if imports from South America hurt European producers."),
    (r"forced labour", "EU bans products made with forced labour",
     "Goods made with forced labour will be barred from the EU market, wherever they come from."),
    (r"generalised scheme of tariff preferences", "EU renews its trade perks for developing countries",
     "Lower tariffs for poorer countries' exports, tied to respect for human and labour rights."),
    (r"Growth Facility for the Republic of Moldova", "EU launches a reform and growth fund for Moldova",
     "EU money for Moldova, an EU candidate country, paid out as it carries out reforms."),
]


def context_for(text):
    return next((v for k, v in CONTEXT.items() if k in text), "")


def lead_text(d):
    """(headline, explanation) for the front page, or (None, None) when no template fits."""
    s = subject_of(d["title"])
    for pat, hl, why in LEAD_FIXED:
        if re.search(pat, s, re.I):
            return hl, why
    if d["kind"] == "Foreign policy update":
        return None, None
    m = re.search(r"European Peace Facility (?:to support|to strengthen the capacities of|for the supply to) (?:the )?(.*?)(?: with | in the | through |,|$)", s)
    if m:
        who = m.group(1).strip()
        c = re.search(r"(?:Armed Forces|Army|Navy) of (?:the )?(?:Republic of |Islamic Republic of |Federal Republic of )?(.+)", who)
        if c:
            name = c.group(1).strip()
            name = "the " + name if name in ("Philippines", "Democratic Republic of the Congo") else name
            who_txt = f"{name}'" + ("" if name.endswith("s") else "s") + " armed forces"
        else:
            who_txt = "the " + re.sub(r"Armed Forces", "armed forces", who)
        return (f"New EU military aid for {who_txt}",
                ("EU governments approved a new package under the European Peace Facility, the EU fund that pays for "
                 "equipment and training for partner armies. " + context_for(who)).strip())
    if "restrictive measures" in s:
        who = next((w for k, w in SANCTION_TARGETS if k.lower() in s.lower()), None)
        if who:
            return (f"EU adopts a new sanctions decision on {who}",
                    ("EU sanctions usually mean asset freezes and travel bans for the people and companies listed, and "
                     "sometimes trade bans. " + context_for(s)).strip())
    m = re.search(r"Special Representative for (?:the )?(.*?)(?:,|$)", s)
    if m and re.match(r"appointing", s, re.I):
        topic = tidy(m.group(1), 60)
        topic = "human rights" if topic.lower() == "human rights" else ("the " + topic if "for the " in m.group(0) else topic)
        return (f"EU names a new special envoy for {topic}",
                "EU Special Representatives speak for the EU in a region or on a theme, and report to the EU's foreign policy chief.")
    m = re.search(r"(European Union [^,(]*?(?:Mission|mission|Operation|operation)) in (?:the )?([A-Z][\w ]+?)(?: \(([^)]+)\))?\s*$", s)
    if m and not re.match(r"amending|extending", s, re.I):
        return (f"EU sends a new mission to {m.group(2)}",
                f"EU governments set up {m.group(3) or 'a new EU mission'}. The official text sets out its mandate, staff and budget. "
                + context_for(m.group(2)))
    m = re.search(r"macro-financial assistance to (?:the )?(.*?)(?:,|$)", s)
    if m:
        name = re.sub(r"^(?:Hashemite Kingdom of |Arab Republic of |Republic of )", "", m.group(1))
        return (f"EU lends money to {name}",
                "Macro-financial assistance: EU loans to a partner country in financial difficulty, paid out in stages as it carries out agreed reforms.")
    return None, None


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


# ---------------------------------------------------------------- coming up (European Parliament open data)
EP_API = "https://data.europarl.europa.eu/api/v2/procedures"
# the five steps a law goes through after the Commission proposes it (ordinary legislative procedure)
STAGES = ["Proposed by the Commission", "In committee at the Parliament", "Parliament has voted its position",
          "Negotiating with EU governments", "Deal reached, final votes to come"]
STAGE_OF = {"REFERRAL": 0, "COMMITTEE_TABLING_AMENDMENT": 1, "COMMITTEE_ADOPTING_OPINION": 1, "COMMITTEE_TABLING_OPINION": 1,
            "COMMITTEE_ADOPTING_REPORT": 1, "COMMITTEE_TABLING_REPORT": 1, "TABLING_PLENARY": 1, "PLENARY_DEBATE": 1,
            "PLENARY_VOTE": 2, "PLENARY_ADOPT_POSITION": 2, "PLENARY_AMEND": 2, "PLENARY_AMEND_PROPOSAL": 2,
            "PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS": 3, "PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS": 3,
            "INTERINSTITUTIONAL_NEGOTIATION": 3, "COMMITTEE_APPROVE_PROVISIONAL_AGREEMENT": 4, "PLENARY_AMEND_COUNCIL_POSITION": 4}


# lead committee of the European Parliament -> our section
COMMITTEE_SECTION = {"ENVI": "climate", "ITRE": "digital", "ECON": "economy", "BUDG": "economy", "CONT": "economy",
                     "JURI": "justice", "LIBE": "justice", "AFCO": "justice", "PETI": "justice", "IMCO": "health", "SANT": "health",
                     "TRAN": "transport", "AGRI": "farming", "PECH": "farming", "EMPL": "social", "REGI": "social",
                     "CULT": "social", "FEMM": "social", "AFET": "world", "INTA": "world", "DEVE": "world", "DROI": "world",
                     "SEDE": "defence"}


def tail(v):
    """last part of an EP code like 'def/ep-activities/PLENARY_VOTE' (some fields come as lists)."""
    v = v[0] if isinstance(v, list) and v else v
    return str(v or "").rsplit("/", 1)[-1]


def ep_json(url):
    return http_json(url, headers={"Accept": "application/ld+json", "User-Agent": "TheFollowThrough/0.3 (EU decisions tracker)"}, tries=3)


def parse_procedure(p, cfg):
    """One EP procedure -> a 'coming up' item, or None if it is already law, empty or stalled."""
    pid = p.get("process_id")
    events = sorted((str(a.get("activity_date", "")), tail(a.get("had_activity_type"))) for a in p.get("consists_of", []))
    kinds = {k for _, k in events}
    if kinds & {"SIGNATURE", "PUBLICATION_OFFICIAL_JOURNAL"} or not events:
        return None   # already law (it shows up in the decisions) or nothing happened yet
    title = (p.get("process_title") or {}).get("en")
    if not title:
        return None
    stage = max((STAGE_OF.get(k, 0) for _, k in events), default=0)
    last = events[-1][0]
    if stage < 4 and last < (TODAY - timedelta(days=730)).isoformat():
        return None   # stalled for two years
    nxt = sorted(str(a.get("activity_date", "")) for a in p.get("was_scheduled_in", [])
                 if str(a.get("activity_date", "")) >= TODAY.isoformat() and tail(a.get("had_activity_type")) == "PLENARY_VOTE")
    ref = p.get("label", pid)
    lead = [tail(x.get("participation_in_name_of")) for x in p.get("had_participation", [])
            if tail(x.get("participation_role")) == "RAPPORTEUR" and x.get("participation_in_name_of")]
    section = next((COMMITTEE_SECTION[c] for c in lead if c in COMMITTEE_SECTION), None) or classify(title, [], cfg)[0]
    hl = headline(title)
    return {"id": pid, "ref": ref, "title": title, "headline": hl, "section": section,
            "stage": stage, "stage_label": STAGES[stage], "started": events[0][0], "last": last,
            "next_vote": nxt[0] if nxt else None, "topic": topic_of(hl, title, cfg),
            "url": f"https://oeil.secure.europarl.europa.eu/oeil/en/procedure-file?reference={urllib.parse.quote(ref)}"}


def fetch_coming_up(cfg, first_year):
    """Laws still being negotiated (ordinary legislative procedure, not yet signed), with their stage and next vote."""
    out, seen = [], set()
    for year in range(first_year, TODAY.year + 1):
        ids = [x["process_id"] for x in ep_json(f"{EP_API}?process-type=COD&year={year}&format=application%2Fld%2Bjson&limit=500")["data"]]
        for pid in ids:
            if pid in seen:
                continue
            seen.add(pid)
            try:
                item = parse_procedure(ep_json(f"{EP_API}/{pid}?format=application%2Fld%2Bjson&language=en")["data"][0], cfg)
            except Exception as e:
                print("  skipped", pid, e)
                item = None
            if item:
                out.append(item)
            time.sleep(0.35)   # the Parliament's API limits the request rate
    out.sort(key=lambda x: (x["next_vote"] is None, x["next_vote"] or "", -x["stage"], x["last"]))
    return out


# ---------------------------------------------------------------- main
def main():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    start = TODAY.replace(year=TODAY.year - cfg["site"]["years_back"])   # default window (2 years)
    # sections can go further back ("since" in config.json), so that small sections are not nearly empty.
    # Foreign-policy decisions (sanctions, missions, military aid) always keep the default window.
    for s in cfg["sections"]:
        s["since"] = s.get("since") or start.isoformat()
    since = {s["id"]: s["since"] for s in cfg["sections"]}
    first = min(date.fromisoformat(v) for v in since.values())
    cache_path = os.path.join(HERE, "ai_cache.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}

    print("EUR-Lex: decisions since", first)
    rows, cur = [], first
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
        if d["section"] in ("defence", "justice", "world"):
            d["lead_hl"], d["lead_dek"] = lead_text(d)
        if d["section"] and d["date"] >= since[d["section"]] and not (
                d["kind"].startswith("Foreign policy") and d["date"] < start.isoformat()):
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
                x.pop("title", None)   # the site shows the short label; dropping the long title keeps data.json light
        d["links_n"] = {k: len(v) for k, v in d["links"].items()}   # true counts, even when the lists are cut
        for k in d["links"]:
            d["links"][k] = d["links"][k][:40]

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

    print("European Parliament: laws in negotiation")
    try:
        coming = fetch_coming_up(cfg, TODAY.year - 3)
        print(f"  {len(coming)} laws in negotiation")
    except Exception as e:   # if the Parliament's site is down, keep yesterday's list
        print("  coming up skipped:", e)
        old = os.path.join(HERE, "data.json")
        coming = json.load(open(old)).get("coming", []) if os.path.exists(old) else []
    photos = json.load(open(os.path.join(HERE, "photos.json"))) if os.path.exists(os.path.join(HERE, "photos.json")) else {}
    out = {"site": cfg["site"], "updated": TODAY.isoformat(), "since": first.isoformat(),
           "sections": [{k: s[k] for k in ("id", "name", "kicker", "about", "since") if k in s} for s in cfg["sections"]],
           "targets": targets, "decisions": decisions, "photos": photos, "coming": coming}
    with open(os.path.join(HERE, "data.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    try:   # readable pages for Google and for sharing (decision/, section/, sitemap.xml)
        import pages
        pages.build(out, cfg)
    except Exception as e:
        print("  pages skipped:", e)
    per = {}
    for d in decisions:
        per[d["section"]] = per.get(d["section"], 0) + 1
    print(f"Done: {len(decisions)} decisions →", per)


if __name__ == "__main__":
    sys.exit(main())
