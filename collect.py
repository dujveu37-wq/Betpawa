#!/usr/bin/env python3
"""BetPawa virtual football collector (stdlib only, uses curl).
Usage: python collect.py [START_ROUND_ID] [--max-minutes N]
START_ROUND_ID is only needed the first time; progress is kept in state.txt.
Every ~20 s it polls a few rounds ahead of the last finished one:
 - while a round is open for bets: remembers its odds (1X2, O/U 1.5/2.5/3.5)
 - while it is being played: reads the scores
 - when all matches reach minute 90: appends one row per match to dataset.csv
No raw files are kept; dataset.csv only grows. Field map inferred, not official."""
import re, csv, datetime, os, struct, subprocess, sys, time

URL = "https://www.betpawa.cm/api/sportsbook/virtual/v3/events/list/by-round/%d"
HDR = ["-H", "x-pawa-brand: betpawa-cameroon", "-H", "accept: application/x-protobuf",
       "-H", "x-pawa-language: fr", "-H", "devicetype: web"]
DATA_DIR = "data"
STATE = "state.txt"
COLS = ["round", "event_id", "league", "home", "away", "odds_1", "odds_X", "odds_2",
        "over_1.5", "under_1.5", "over_2.5", "under_2.5", "over_3.5", "under_3.5",
        "ft_home", "ft_away", "result"]

def rv(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1; r |= (c & 0x7f) << s; s += 7
        if c < 128: return r, i

def parse(b):
    i, out = 0, []
    while i < len(b):
        k, i = rv(b, i); f, w = k >> 3, k & 7
        if w == 0: v, i = rv(b, i)
        elif w == 2:
            l, i = rv(b, i); v = b[i:i+l]; i += l
        elif w == 1: v = b[i:i+8]; i += 8
        elif w == 5: v = b[i:i+4]; i += 4
        else: raise ValueError
        out.append((f, w, v))
    return out

def get(items, f): return [v for k, _, v in items if k == f]

def fetch(rid):
    r = subprocess.run(["curl", "-s", "--compressed", "-m", "20", *HDR, URL % rid],
                       capture_output=True)
    d = r.stdout
    if len(d) < 50 or d[:1] == b"{": return None
    try: return [parse(v) for f, _, v in parse(d) if f == 2]
    except Exception: return None

def auto_start():
    """Premier round pas encore commence, d'apres la liste 'actual' du site."""
    import re
    r = subprocess.run(["curl", "-s", "--compressed", "-m", "20", *HDR,
        "https://www.betpawa.cm/api/sportsbook/virtual/v2/seasons/list/actual"], capture_output=True)
    ids = sorted({int(x) for x in re.findall(rb"1[0-9]{6}", r.stdout)})
    if not ids: return None
    run = [ids[-1]]
    for x in reversed(ids[:-1]):
        if x == run[-1] - 1: run.append(x)
        else: break
    for rid in sorted(run):
        ev = fetch(rid)
        if ev and not any(get(e, 3) for e in ev): return rid
    return None

def read_event(e):
    """-> dict with ids, odds (if any), minute and FT score (if any)."""
    o = {"event_id": get(e, 1)[0].decode()}
    t = [parse(x) for x in get(e, 5)]
    o["home"], o["away"] = t[0][1][2].decode(), t[1][1][2].decode()
    o["league"] = parse(get(e, 12)[0])[1][2].decode()
    for mk in get(e, 7):
        m = parse(mk); mid = parse(get(m, 1)[0])[0][2].decode()
        for row in get(m, 2):
            for p in get(parse(row), 4):
                d = {k: v for k, _, v in parse(p)}
                od = round(struct.unpack("<d", d[4])[0], 2)
                if mid == "3743": o["odds_" + d[2].decode()] = od
                elif mid == "5000":
                    side = "over" if d[2] == b"Plus de" else "under"
                    o[f"{side}_{d[6].decode()}"] = od
    st = get(e, 3)
    if st:
        s = parse(st[0]); o["minute"] = int(parse(get(s, 1)[0])[0][2])
        for side in get(s, 2):
            sp = parse(side); team = parse(get(sp, 1)[0])[1][2].decode()
            for sc in get(sp, 2):
                p = parse(sc)
                if parse(get(p, 1)[0])[2][2] == b"FULL_TIME_EXCLUDING_OVERTIME":
                    o["ft_" + team.lower()] = int(get(p, 2)[0])
    return o

def writer_for_today(cur):
    day = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    if cur and cur[0] == day: return cur
    if cur: cur[2].close()
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, day + ".csv"); new = not os.path.exists(path)
    f = open(path, "a", newline=""); w = csv.DictWriter(f, COLS, extrasaction="ignore")
    if new: w.writeheader()
    return (day, w, f)

def liste():
    r = subprocess.run(["curl", "-s", "--compressed", "-m", "20", *HDR,
        "https://www.betpawa.cm/api/sportsbook/virtual/v2/seasons/list/actual"], capture_output=True)
    return sorted({int(x) for x in re.findall(rb"1[0-9]{6}", r.stdout)})

def main():
    argv = sys.argv[1:]; maxmin = 1e9; args = []
    while argv:
        a = argv.pop(0)
        if a == "--max-minutes": maxmin = float(argv.pop(0))
        elif a.strip(): args.append(a)
    rid = None
    if os.path.exists(STATE): rid = int(open(STATE).read().strip())
    elif args and args[0].isdigit(): rid = int(args[0])
    ids = liste()
    if not ids: sys.exit("ERREUR: aucune reponse du site (blocage possible de cette machine)")
    if rid is None or rid not in ids:
        if rid is not None: print("round", rid, "n'est plus dans la liste, recherche automatique", flush=True)
        rid = auto_start() or ids[0]
        open(STATE, "w").write(str(rid))
    t0 = time.time(); odds = {}; stable = {}; since = {}; cur = None
    last_ok = time.time(); last_beat = time.time(); saved = 0
    print("depart au round", rid, flush=True)
    while time.time() - t0 < maxmin * 60:
        ids = liste()
        if time.time() - last_beat > 600:
            print("vivant: round", rid, "| site", "ok" if time.time() - last_ok < 120 else "SANS REPONSE",
                  "| rounds ecrits", saved, flush=True); last_beat = time.time()
        if ids and rid not in ids:
            print("round", rid, "disparu de la liste, recherche automatique", flush=True)
            odds.clear(); stable.clear(); since.clear()
            rid = auto_start() or ids[0]; open(STATE, "w").write(str(rid)); print("nouveau depart", rid, flush=True)
        open_later = False; got = {}
        for r in range(rid, rid + 6):
            ev = fetch(r)
            if not ev: continue
            evs = [read_event(e) for e in ev]; got[r] = evs
            since.setdefault(r, time.time())
            if any("odds_1" in e for e in evs):
                odds[r] = {e["event_id"]: e for e in evs}      # derniere cote vue
                if r > rid: open_later = True
        if ids and got: last_ok = time.time()
        if time.time() - last_ok > 900:
            sys.exit("ERREUR: le site ne repond plus depuis 15 min (machine bloquee?), arret pour changer de machine")
        evs = got.get(rid)
        if evs and all("ft_home" in e for e in evs):
            sig = tuple((e["event_id"], e["ft_home"], e["ft_away"]) for e in evs)
            if stable.get(rid, (None,))[0] != sig: stable[rid] = (sig, time.time())
            # fini = scores complets, inchanges depuis 90 s, et un round suivant est deja ouvert aux paris
            if time.time() - stable[rid][1] >= 90 and open_later:
                cur = writer_for_today(cur); n = 0
                for e in evs:
                    base = odds.get(rid, {}).get(e["event_id"])
                    if not base: continue
                    row = dict(base, round=rid, ft_home=e["ft_home"], ft_away=e["ft_away"],
                               result="1" if e["ft_home"] > e["ft_away"] else
                                      "2" if e["ft_home"] < e["ft_away"] else "X")
                    cur[1].writerow(row); n += 1
                cur[2].flush(); saved += 1; print("round", rid, "->", n, "matchs", flush=True)
                odds.pop(rid, None); stable.pop(rid, None); since.pop(rid, None); rid += 1
                open(STATE, "w").write(str(rid))
        if rid in since and time.time() - since[rid] > 7200:
            print("round", rid, "abandonne (bloque depuis 2 h)", flush=True)
            odds.pop(rid, None); since.pop(rid, None); rid += 1; open(STATE, "w").write(str(rid))
        time.sleep(20)
    open(STATE, "w").write(str(rid)); print("fin de session, prochain round:", rid)

if __name__ == "__main__":
    main()
