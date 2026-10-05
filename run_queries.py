import csv, json
from datetime import datetime, timezone
import requests

URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "mkr1/1.0",}


def run(query):
    r = requests.get(URL, params={"query": query, "format": "json"},
                     headers=HEADERS, timeout=120)
    data = r.json()
    cols = data["head"]["vars"]
    rows = [{c: b.get(c, {}).get("value", "") for c in cols}
            for b in data["results"]["bindings"]]
    return cols, rows


def save(name, cols, rows):
    with open(name, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main():
    for n in (1, 2, 3):
        q = open(f"q{n}.rq", encoding="utf-8").read()
        cols, rows = run(q)
        save(f"q{n}.csv", cols, rows)
        print(f"q{n}.csv: {len(rows)} rows")

    with open("meta.json", "w", encoding="utf-8") as f:
        json.dump({"retrieved_at": datetime.now(timezone.utc).isoformat()}, f)


if __name__ == "__main__":
    main()