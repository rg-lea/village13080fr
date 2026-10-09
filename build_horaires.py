#!/usr/bin/env python3
"""
build_horaires.py : convertit les flux GTFS officiels en horaires.json
pour les lignes 11, 14 (Aix lebus) et 51 (Métropole lecar) à Luynes.

Usage :
    python3 build_horaires.py --aix mamp-aix_gtfs.zip --c13 mamp-c13_gtfs.zip --out horaires.json

Aucune dépendance (bibliothèque standard uniquement).
À relancer à CHAQUE nouveau flux GTFS (le flux Aix lebus ne couvre que quelques semaines).
Le script affiche des contrôles ; s'il détecte une anomalie bloquante il s'arrête (code 1).
"""
import argparse, csv, io, json, sys, zipfile, datetime as dt
from collections import defaultdict

# --------------------------------------------------------------------------
# CONFIGURATION : lignes et arrêts affichés sur la page
# Chaque arrêt = libellé affiché + identifiants GTFS (un par sens de circulation) + lien carte
# --------------------------------------------------------------------------
MAPS = {
    "Luynes Mail": "https://maps.app.goo.gl/7YHA2EncEDmiJQqW6",
    "Vidal": "https://maps.app.goo.gl/gCKQckD5KYwEmAS36",
    "De Green": "https://maps.app.goo.gl/54zypF3waE71VnoM9",
    "Chapuis": "https://maps.app.goo.gl/QxjE9nNMKUwbGwJr6",
    "Luynes Centre": "https://maps.app.goo.gl/PFT6rarWiZgSFJ339",
    "Luynes Sud": "https://maps.app.goo.gl/KhoZg1ALiYoCXphD9",
    "Luynes Lycée": "https://maps.app.goo.gl/UB7mktNzSCVLASL97",
    "Frères Gris": "https://maps.app.goo.gl/MqXqFNQHvY16Qhx28",
    "Bon Rencontre": "https://maps.app.goo.gl/Xn5vu9GRrxoGheNt6",
    "La Blaque": "https://maps.app.goo.gl/esiQdrzLZQDFjfye7",
    "Rampelin": "https://maps.app.goo.gl/PC8vGg6FvD2v8t2d8",
    "Trois Pigeons": "https://maps.app.goo.gl/xFXMhJzH1rbQXgkr5",
    "P+R Arena": "https://maps.app.goo.gl/jsm4p2o5HyyGsS4h9",
}
S_CHAPUIS = ("Chapuis", ["26383", "22504"])
S_CENTRE = ("Luynes Centre", ["37657", "37656"])
S_SUD = ("Luynes Sud", ["25914", "24649"])
S_LYCEE = ("Luynes Lycée", ["22132", "22514"])
S_FG = ("Frères Gris", ["23801", "20842"])
S_BR = ("Bon Rencontre", ["26382", "21663"])
S_BL = ("La Blaque", ["22130", "21670"])
S_RAMP = ("Rampelin", ["23302", "25537"])
S_3P = ("Trois Pigeons", ["23304", "21356"])

LINES = {
    "11": dict(feed="aix", route="AIX-11", prefix="AIX-", realtime=True,
               stops=[("Luynes Mail", ["21285"]), ("Vidal", ["40257", "20547"]),
                      ("De Green", ["25658", "20286"]), S_CHAPUIS, S_CENTRE, S_SUD, S_LYCEE]),
    "14": dict(feed="aix", route="AIX-14", prefix="AIX-", realtime=True,
               stops=[S_FG, S_BR, S_BL, S_CHAPUIS, S_CENTRE, S_SUD, S_LYCEE, S_RAMP, S_3P,
                      ("P+R Arena", ["28182", "20493"])]),
    "51": dict(feed="c13", route="C13-51", prefix="MAMP-", realtime=False,
               stops=[S_FG, S_BR, S_BL, S_CHAPUIS, S_SUD, S_LYCEE, S_RAMP, S_3P]),
}
FEEDS = {"aix": "Aix lebus (Aix-en-Bus)", "c13": "Métropole lecar"}


def fail(msg):
    print("ERREUR BLOQUANTE :", msg, file=sys.stderr)
    sys.exit(1)


def read_csv(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))


def ymd(s):
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))


def hms_to_min(s):
    h, m, sec = (int(x) for x in s.split(":"))
    if sec != 0:
        print(f"  ! secondes non nulles ({s}) : arrondi à la minute inférieure")
    return h * 60 + m


def easter(y):
    a = y % 19; b, c = divmod(y, 100); d, e = divmod(b, 4)
    f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7; m = (a + 11 * h + 22 * l) // 451
    mo, da = divmod(h + l - 7 * m + 114, 31)
    return dt.date(y, mo, da + 1)


def fr_holidays(y):
    e = easter(y); d = dt.timedelta
    return {dt.date(y, 1, 1): "Jour de l'an", e + d(1): "Lundi de Pâques", dt.date(y, 5, 1): "Fête du travail",
            dt.date(y, 5, 8): "Victoire 1945", e + d(39): "Ascension", e + d(50): "Lundi de Pentecôte",
            dt.date(y, 7, 14): "Fête nationale", dt.date(y, 8, 15): "Assomption", dt.date(y, 11, 1): "Toussaint",
            dt.date(y, 11, 11): "Armistice", dt.date(y, 12, 25): "Noël"}


def load_feed(path):
    z = zipfile.ZipFile(path)
    info = next(read_csv(z, "feed_info.txt"))
    cal = {r["service_id"]: r for r in read_csv(z, "calendar.txt")}
    cdates = defaultdict(dict)  # service -> {date: type}
    try:
        for r in read_csv(z, "calendar_dates.txt"):
            cdates[r["service_id"]][ymd(r["date"])] = int(r["exception_type"])
    except KeyError:
        pass
    return z, info, cal, cdates


def service_active(sid, day, cal, cdates):
    exc = cdates.get(sid, {}).get(day)
    if exc == 1: return True
    if exc == 2: return False
    c = cal.get(sid)
    if not c: return False
    if not (ymd(c["start_date"]) <= day <= ymd(c["end_date"])): return False
    return c[["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][day.weekday()]] == "1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aix", required=True); ap.add_argument("--c13", required=True)
    ap.add_argument("--out", default="horaires.json")
    ap.add_argument("--from-date", help="AAAA-MM-JJ (défaut : hier)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.from_date) if a.from_date else dt.date.today() - dt.timedelta(days=1)

    feeds = {k: load_feed(p) for k, p in (("aix", a.aix), ("c13", a.c13))}
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "sources": {}, "lines": {}}
    for k, (z, info, cal, cd) in feeds.items():
        out["sources"][k] = dict(name=FEEDS[k], feed_start=info["feed_start_date"], feed_end=info["feed_end_date"],
                                 feed_version=info.get("feed_version", ""))
        print(f"[{k}] {FEEDS[k]} : flux du {info['feed_start_date']} au {info['feed_end_date']} (v{info.get('feed_version','')})")

    for lid, cfg in LINES.items():
        z, info, cal, cd = feeds[cfg["feed"]]
        trips = {r["trip_id"]: r for r in read_csv(z, "trips.txt") if r["route_id"] == cfg["route"]}
        if not trips: fail(f"ligne {lid} : aucune course pour {cfg['route']}")
        services = {t["service_id"] for t in trips.values()}
        feed_end = ymd(info["feed_end_date"]); feed_start = ymd(info["feed_start_date"])

        # --- calendrier : jours où au moins un service de la ligne circule
        first = min(feed_start, min(ymd(cal[s]["start_date"]) for s in services if s in cal))
        last = max(feed_end, today)
        active = {}
        d = max(first, today)
        while d <= feed_end:
            active[d] = sorted(s for s in services if service_active(s, d, cal, cd))
            d += dt.timedelta(days=1)
        days_with = [d for d, s in active.items() if s]
        if not days_with: fail(f"ligne {lid} : aucun jour de service à partir de {today}")
        valid_from, valid_to = min(days_with), max(days_with)
        # La fin de validité est la dernière date réellement publiée pour la ligne.
        active = {d: s for d, s in active.items() if valid_from <= d <= valid_to}
        used = sorted({s for v in active.values() for s in v})
        sidx = {s: f"s{i}" for i, s in enumerate(used)}

        # --- horaires
        want = {}  # stop_id -> (label)
        for label, ids in cfg["stops"]:
            for i in ids: want[cfg["prefix"] + i] = label
        rows = defaultdict(list)  # trip_id -> [(seq, stop_id, dep, pickup)]
        for r in read_csv(z, "stop_times.txt"):
            if r["trip_id"] in trips:
                rows[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"], r["departure_time"], r["pickup_type"] or "0"))
        heads = []
        def hidx(h):
            if h not in heads: heads.append(h)
            return heads.index(h)
        data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # label->dir->svc->[[min,head]]
        dircount = defaultdict(lambda: defaultdict(int))
        refs = defaultdict(dict)  # label -> direction -> identifiant GTFS de l'arrêt (pour le temps réel)
        for tid, t in trips.items():
            seq = sorted(rows[tid]); last_seq = seq[-1][0]
            if t["service_id"] not in sidx: continue
            for sq, sid, dep, pk in seq:
                if sid in want and sq != last_seq and pk != "1":
                    data[want[sid]][t["direction_id"]][sidx[t["service_id"]]].append([hms_to_min(dep), hidx(t["trip_headsign"])])
                    dircount[t["direction_id"]][t["trip_headsign"]] += 1
                    refs[want[sid]][t["direction_id"]] = sid
        for l in data.values():
            for dd in l.values():
                for v in dd.values(): v.sort()
        dirs = {d: max(c, key=c.get) for d, c in dircount.items()}

        # --- sets de services par jour
        sets, sname, days = {}, {}, {}
        for d, ss in active.items():
            key = ",".join(sidx[s] for s in ss)
            if key not in sname:
                sname[key] = f"k{len(sname)}"; sets[sname[key]] = [sidx[s] for s in ss]
            days[d.isoformat()] = sname[key]

        stops = []
        for label, ids in cfg["stops"]:
            if label not in data: fail(f"ligne {lid} : arrêt « {label} » absent des horaires (identifiants GTFS à revoir)")
            stops.append({"label": label, "map": MAPS[label], "ref": refs[label],
                          "d": {d: v for d, v in data[label].items()}})
        out["lines"][lid] = {"feed": cfg["feed"], "realtime": cfg["realtime"], "from": valid_from.isoformat(),
                             "to": valid_to.isoformat(), "heads": heads, "dirs": dirs, "sets": sets, "days": days,
                             "stops": stops}

        # --- contrôles
        n = sum(len(v) for s in stops for dd in s["d"].values() for v in dd.values())
        print(f"[ligne {lid}] valable du {valid_from} au {valid_to} | {len(used)} services | {n} passages | sens {dirs}")
        for label, _ in cfg["stops"]:
            tot = sum(len(v) for dd in data[label].values() for v in dd.values())
            print(f"    {label:<14} {tot:>5} passages (tous services confondus)")
        hol = {}
        for y in {valid_from.year, valid_to.year}: hol.update(fr_holidays(y))
        for h, name in sorted(hol.items()):
            if valid_from <= h <= valid_to:
                explicit = any(h in cd.get(s, {}) for s in services)
                print(f"    ⚠ jour férié {h} ({name}) dans la période : "
                      + ("exception prévue dans le flux" if explicit else
                         "AUCUNE exception dans le flux -> le calendrier standard s'applique, à vérifier auprès du réseau"))
        empty = [d for d, s in active.items() if not s]
        if empty: print(f"    ℹ jours sans service dans la période : {', '.join(map(str, empty))}")

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"-> {a.out} écrit ({len(json.dumps(out, separators=(',', ':'))) // 1024} Ko)")


if __name__ == "__main__":
    main()
