"""Verify bibliographic DOIs against Crossref (sequential, polite). Output: crossref_records.json.

    python docs/literature/verify_dois.py
"""
import json
import os
import time
import urllib.error
import urllib.request

DOIS = [
    "10.1016/j.trc.2013.08.014", "10.1109/TITS.2019.2901791", "10.1145/3357384.3357902", "10.1109/TITS.2020.3008612",
    "10.1371/journal.pone.0172395", "10.1609/aaai.v32i1.11797", "10.1609/aaai.v30i1.10295", "10.1145/3292500.3330949",
    "10.1145/3219819.3220096", "10.1609/aaai.v34i04.5744", "10.1016/j.eswa.2022.116830", "10.32473/flairs.v35i.130584",
    "10.1609/aaai.v32i1.11694", "10.1016/j.trc.2020.102828", "10.1109/ITSC.2018.8569938", "10.1109/TITS.2013.2255286",
    "10.1145/3357384.3357900", "10.1007/s10462-021-09996-w", "10.1007/s10994-023-06412-y", "10.1109/ITSC48978.2021.9564847",
    "10.1038/nature14236", "10.1109/TVT.2017.2760820", "10.3390/s25051302",
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crossref_records.json")


def fetch(doi):
    url = "https://api.crossref.org/works/{}?mailto=research@example.org".format(doi)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "doi-check/1.0"}), timeout=30) as r:
                m = json.load(r)["message"]
            year = (m.get("published-print") or m.get("published-online") or m.get("issued"))["date-parts"][0][0]
            return {"doi": doi, "found": True, "title": (m.get("title") or [""])[0],
                    "authors": [a.get("family", a.get("name", "")) for a in m.get("author", [])],
                    "container": (m.get("container-title") or [""])[0], "year": year, "volume": m.get("volume"),
                    "issue": m.get("issue"), "page": m.get("page") or m.get("article-number"), "type": m.get("type")}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"doi": doi, "found": False, "error": "404 not in Crossref"}
            time.sleep(3 * (attempt + 1))
        except Exception as e:  # network
            time.sleep(3 * (attempt + 1))
            last = str(e)
    return {"doi": doi, "found": False, "error": "unreachable"}


def main():
    res = []
    for d in DOIS:
        res.append(fetch(d))
        r = res[-1]
        print(d, "|", r.get("year"), "|", r.get("title", r.get("error"))[:110], "|", ", ".join(r.get("authors", [])[:4]))
        time.sleep(1.2)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
