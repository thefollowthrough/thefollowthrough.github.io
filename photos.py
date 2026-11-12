#!/usr/bin/env python3
"""Finds free-licensed photos on Wikimedia Commons for each section and writes photos.json
(with author + licence, which the site displays as credits). Run once; re-run to refresh."""
import json, os, re, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "TheFollowThrough/0.1 (prototype news site about EU decisions)"}
OK_LICENCES = ("CC BY", "CC0", "Public domain", "CC-BY", "PD")

QUERIES = {
    "masthead": ["European Parliament hemicycle Strasbourg 2023"],
    "commission": ["Berlaymont building Brussels"],
    "council": ["Europa building Brussels Council"],
    "climate": ["offshore wind farm", "solar park photovoltaic Germany"],
    "economy": ["euro coins and banknotes", "European Central Bank Frankfurt"],
    "digital": ["data center server racks", "semiconductor wafer"],
    "world": ["container ship port Rotterdam", "container terminal Hamburg"],
    "defence": ["Eurofighter Typhoon", "Leopard 2 tank"],
    "justice": ["Court of Justice of the European Union Luxembourg", "Schengen border crossing"],
    "health": ["Operating-room 2", "pharmacy medicines shelves", "laboratory pipette"],
    "farming": ["wheat field harvest combine", "fishing boats harbour Brittany"],
    "transport": ["TGV high speed train", "Airbus A320 landing"],
    "social": ["construction workers building site Germany", "university lecture hall students", "Brussels street crowd"],
}


def search(q, n=10):
    u = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(dict(
        action="query", format="json", generator="search", gsrsearch="filetype:bitmap " + q,
        gsrnamespace=6, gsrlimit=n, prop="imageinfo", iiprop="url|extmetadata|size", iiurlwidth=1600))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
                return list(json.load(r).get("query", {}).get("pages", {}).values())
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(10 * (attempt + 1))
    return []


def clean(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


BLOCK = ("Singapore", "1923", "Gecamines", "Boudin", "Shinkansen", "AirAsia", "Duga", "Airacobra", "Palmer", "CATHEDRAL")


def main():
    import sys
    path = os.path.join(HERE, "photos.json")
    out = json.load(open(path)) if os.path.exists(path) else {}
    only = sys.argv[1:]
    for key, queries in QUERIES.items():
        # The front-page hemicycle photos (masthead) were hand-picked: only re-search them if asked by name.
        if (only and key not in only) or (not only and key == "masthead"):
            out[key] = [x for x in out.get(key, []) if not any(b in x["title"] for b in BLOCK)]
            continue
        picks = []
        for q in queries:
            for p in search(q):
                ii = p["imageinfo"][0]
                m = ii.get("extmetadata", {})
                lic = clean(m.get("LicenseShortName", {}).get("value"))
                if any(b in p["title"] for b in BLOCK) or any(x["source"] == ii["descriptionurl"] for x in picks):
                    continue
                if ii["width"] < 1400 or ii["width"] < ii["height"] * 1.2 or not lic.startswith(OK_LICENCES):
                    continue
                picks.append({
                    "url": ii.get("thumburl", ii["url"]).split("?")[0],
                    "title": p["title"].replace("File:", "").rsplit(".", 1)[0],
                    "author": clean(m.get("Artist", {}).get("value"))[:80] or "Wikimedia Commons",
                    "licence": lic,
                    "source": ii["descriptionurl"],
                })
                if len(picks) >= 3:
                    break
            time.sleep(3)
        out[key] = picks
        print(key, len(picks))
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
