import csv, json, re, sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from rdflib import Graph, Literal, Namespace, RDF, RDFS, XSD
# встановлюємо неймспейс
EX = Namespace("http://example.org/mkr/")

# заміна пробілів на "_"
def under(s):
    return re.sub(r"\s+", "_", s.strip())

# обробка двох форматів дат
def parse_date(s):
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def main(csv_path, params_path, out_path):
    params = json.load(open(params_path, encoding="utf-8"))
    budget = Decimal(str(params["budget_threshold_eur"]))
    long_min = int(params["long_flight_min"])

    flights = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            fid = row["flight_id"].strip().upper()
            if not fid:
                continue
            rec = {
                "airline": row["airline"].strip(),
                "from_city": row["from_city"].strip().title(),
                "from_country": row["from_country"].strip().title(),
                "to_city": row["to_city"].strip().title(),
                "to_country": row["to_country"].strip().title(),
                "date": parse_date(row["dep_date"] or ""),
                "dur": (row["duration_min"] or "").strip(),
                "price": (row["price_eur"] or "").strip(),
                "note": (row["note"] or "").strip(),
            }
            # якщо рейс вже є - заповнюємо тільки пусті поля
            if fid in flights:
                for k in rec:
                    if not flights[fid].get(k) and rec[k]:
                        flights[fid][k] = rec[k]
            else:
                flights[fid] = rec

    g = Graph()
    g.bind("ex", EX)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)
    g.bind("rdf", RDF)

    # класи
    for c in ("Flight", "Airline", "City", "Country"):
        g.add((EX[c], RDF.type, RDFS.Class))
    g.add((EX.BudgetFlight, RDF.type, RDFS.Class))
    g.add((EX.LongFlight, RDF.type, RDFS.Class))
    g.add((EX.BudgetFlight, RDFS.subClassOf, EX.Flight))
    g.add((EX.LongFlight, RDFS.subClassOf, EX.Flight))

    # властивості: domain/range
    props = {
        "operatedBy":      (EX.Flight, EX.Airline),
        "departsFrom":     (EX.Flight, EX.City),
        "arrivesAt":       (EX.Flight, EX.City),
        "locatedIn":       (EX.City,   EX.Country),
        "departureDate":   (EX.Flight, XSD.date),
        "durationMin":     (EX.Flight, XSD.integer),
        "priceEur":        (EX.Flight, XSD.decimal),
        "hasDelayMinutes": (EX.Flight, XSD.integer),
        "fromBusyCountry": (EX.Flight, XSD.boolean),
        "reportedBy":      (RDF.Statement, RDFS.Resource),
    }
    for p in props:
        d, r = props[p]
        g.add((EX[p], RDF.type, RDF.Property))
        g.add((EX[p], RDFS.domain, d))
        g.add((EX[p], RDFS.range, r))

    # перевірка зайнятої країни
    cnt = {}
    for r in flights.values():
        c = r["from_country"]
        cnt[c] = cnt.get(c, 0) + 1
    busy = set()
    for c in cnt:
        if cnt[c] >= 2:
            busy.add(c)

    for fid in sorted(flights):
        r = flights[fid]
        fl = EX["flight/" + under(fid)]
        airline = EX["airline/" + under(r["airline"])]
        c_from = EX["city/" + under(r["from_city"])]
        c_to = EX["city/" + under(r["to_city"])]

        price = None
        if r["price"]:
            try:
                price = Decimal(r["price"])
            except InvalidOperation:
                price = None

        dur = None
        if r["dur"]:
            dur = int(r["dur"])

        # типи рейсів
        types = []
        if price is not None and price <= budget:
            types.append(EX.BudgetFlight)
        if dur is not None and dur >= long_min:
            types.append(EX.LongFlight)
        if not types:
            types.append(EX.Flight)
        for t in types:
            g.add((fl, RDF.type, t))

        g.add((fl, EX.operatedBy, airline))
        g.add((airline, RDF.type, EX.Airline))
        g.add((airline, RDFS.label, Literal(r["airline"], lang="en")))

        # міста і країни для обох кінців
        ends = [
            (c_from, r["from_city"], r["from_country"]),
            (c_to,   r["to_city"],   r["to_country"]),
        ]
        for node, city, country in ends:
            cn = EX["country/" + under(country)]
            g.add((node, RDF.type, EX.City))
            g.add((node, RDFS.label, Literal(city, lang="en")))
            g.add((node, EX.locatedIn, cn))
            g.add((cn, RDF.type, EX.Country))
            g.add((cn, RDFS.label, Literal(country, lang="en")))

        g.add((fl, EX.departsFrom, c_from))
        g.add((fl, EX.arrivesAt, c_to))

        if r["date"]:
            g.add((fl, EX.departureDate, Literal(r["date"], datatype=XSD.date)))
        if dur is not None:
            g.add((fl, EX.durationMin, Literal(dur, datatype=XSD.integer)))
        if price is not None:
            g.add((fl, EX.priceEur, Literal(r["price"], datatype=XSD.decimal)))

        # пошук затримок
        m = re.search(r"delay=(\d+);by=([^;]+)", r["note"])
        if m:
            st = EX["stmt/" + under(fid) + "-delay"]
            g.add((st, RDF.type, RDF.Statement))
            g.add((st, RDF.subject, fl))
            g.add((st, RDF.predicate, EX.hasDelayMinutes))
            g.add((st, RDF.object, Literal(int(m.group(1)), datatype=XSD.integer)))
            src = EX["source/" + under(m.group(2))]
            g.add((st, EX.reportedBy, src))

        if r["from_country"] in busy:
            g.add((fl, EX.fromBusyCountry, Literal(True, datatype=XSD.boolean)))

    g.serialize(destination=out_path, format="turtle")
    print(len(flights), "flights,", len(g), "triples ->", out_path)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: python build_graph.py flights.csv params.json graph.ttl")
    main(sys.argv[1], sys.argv[2], sys.argv[3])