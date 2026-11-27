#!/usr/bin/env python3
"""BetPawa virtual football collector (stdlib only, uses curl).
Usage: python collect.py [START_ROUND_ID] [--max-minutes N]
START_ROUND_ID is only needed the first time; progress is kept in state.txt.
Every ~20 s it polls a few rounds ahead of the last finished one:
 - while a round is open for bets: remembers its odds (1X2, O/U 1.5/2.5/3.5)
 - while it is being played: reads the scores
 - when all matches reach minute 90: appends one row per match to dataset.csv
No raw files are kept; dataset.csv only grows. Field map inferred, not official."""
import glob, re, csv, datetime, os, struct, subprocess, sys, time

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


MK = {  # marche: (colonne de cote, condition gagnante sur le total de buts)
 "over_1.5": ("over_1.5", lambda r: r["tot"] >= 2), "under_1.5": ("under_1.5", lambda r: r["tot"] <= 1),
 "over_2.5": ("over_2.5", lambda r: r["tot"] >= 3), "under_2.5": ("under_2.5", lambda r: r["tot"] <= 2),
 "over_3.5": ("over_3.5", lambda r: r["tot"] >= 4), "under_3.5": ("under_3.5", lambda r: r["tot"] <= 3),
 "1": ("odds_1", lambda r: r["result"] == "1"), "X": ("odds_X", lambda r: r["result"] == "X"),
 "2": ("odds_2", lambda r: r["result"] == "2")}
NBINS = 8; Z95 = 1.96; ZCORR = 3.3   # correction pour ~70 tests
def load(files):
    rows = []
    for f in files:
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            try:
                r["tot"] = int(r["ft_home"]) + int(r["ft_away"]); r["rnd"] = int(r["round"]); r["result"] = r["result"].strip().upper()
                for m, (c, _) in MK.items(): r[c] = float(r[c])
                rows.append(r)
            except (ValueError, KeyError): pass
    seen = set(); out = []
    for r in sorted(rows, key=lambda r: r["rnd"]):
        if r["event_id"] not in seen: seen.add(r["event_id"]); out.append(r)
    return out
def stat(rows, m):
    c, win = MK[m]; p = [(win(r) * r[c] - 1) for r in rows]; n = len(p)
    if n < 2: return n, 0.0, 9.9
    mu = sum(p) / n; sd = (sum((x - mu) ** 2 for x in p) / (n - 1)) ** .5
    return n, mu, sd / n ** .5

def table(rows):
    """Decision par marche et tranche de cote (memes regles que zicote.py)."""
    rnds = sorted({r["rnd"] for r in rows}); cut = rnds[int(len(rnds) * .7)]
    train = [r for r in rows if r["rnd"] < cut]; test = [r for r in rows if r["rnd"] >= cut]
    cells = {}
    for m, (c, _) in MK.items():
        v = sorted(r[c] for r in train); edges = [v[int(len(v) * i / NBINS)] for i in range(NBINS)] + [1e9]
        lst = []
        for i in range(NBINS):
            sel = lambda R: [r for r in R if edges[i] <= r[c] < edges[i + 1]]
            a, b = sel(train), sel(test)
            if len(a) < 100: continue
            n1, mu1, se1 = stat(a, m); n2, mu2, se2 = stat(b, m)
            if mu1 - ZCORR * se1 > 0 and n1 >= 300 and mu2 > 0 and n2 >= 100: d = "SIGNAL VALIDE"
            elif mu1 - Z95 * se1 > 0 and mu2 > 0: d = "SURVEILLANCE"
            else: d = "AUCUN SIGNAL"
            lst.append((edges[i], edges[i + 1], d, mu1, se1, mu2))
        cells[m] = lst
    return cells

def open_round():
    for rid in liste():
        ev = fetch(rid)
        if not ev: continue
        evs = [read_event(e) for e in ev]
        if any("odds_1" in e for e in evs): return rid, evs
    return None, []

CHAT_IDS = [x for x in os.environ.get("TELEGRAM_CHAT_IDS", "-1003545879698,7219903652").split(",") if x]
# par defaut : canal "Zicote Cote en direct" + ton chat prive
def telegram(text):
    """Envoie le message a chaque chat. Token du bot dans la variable TELEGRAM_TOKEN."""
    tok = os.environ.get("TELEGRAM_TOKEN")
    if not tok:
        print("(Telegram non envoye : variable TELEGRAM_TOKEN absente)"); return
    for cid in CHAT_IDS:
        r = subprocess.run(["curl", "-s", "-m", "20", "-X", "POST",
            "https://api.telegram.org/bot%s/sendMessage" % tok,
            "--data-urlencode", "chat_id=" + cid, "--data-urlencode", "text=" + text], capture_output=True)
        print("Telegram", cid, ":", "envoye" if b'"ok":true' in r.stdout else "ECHEC " + r.stdout.decode()[:200])

def verdict(d, mu1, mu2):
    if d == "SIGNAL VALIDE": return "SIGNAL VALIDE"
    if d == "SURVEILLANCE": return "SURVEILLANCE"
    if mu2 > 0 and mu1 <= 0: return "PISTE FAIBLE (positif recent seulement)"
    if mu1 > 0 and mu2 <= 0: return "PISTE FAIBLE (positif ancien seulement)"
    if mu1 > 0 and mu2 > 0: return "PISTE FAIBLE (positif des 2 cotes, non significatif)"
    return None

def report(evs, cells):
    """Une ligne par match : verdict + marches positifs d'un cote ou de l'autre."""
    order = {"SIGNAL VALIDE": 0, "SURVEILLANCE": 1}; valid = []
    for e in evs:
        name = "%s-%s" % (e["home"], e["away"]); items = []
        for m, (c, _) in MK.items():
            try: o = float(e[c])
            except (KeyError, ValueError, TypeError): continue
            for lo, hi, d, mu1, se1, mu2 in cells.get(m, []):
                if lo <= o < hi:
                    v = verdict(d, mu1, mu2)
                    if v: items.append((order.get(v, 2), -mu1, v, m, o, mu1, mu2))
        items.sort()
        valid += ["%s  %s @%.2f  (ancien %+.1f%%, recent %+.1f%%)" % (name, x[3], x[4], 100*x[5], 100*x[6]) for x in items if x[2] == "SIGNAL VALIDE"]
        top = items[0][2] if items else "AUCUN SIGNAL"
        print("\n%s : %s" % (name, "AUCUN SIGNAL. Ne rien miser." if not items else top))
        for _, _, v, m, o, mu1, mu2 in items:
            print("   %s @%.2f  ancien %+.1f%%  recent %+.1f%%  -> %s" % (m, o, 100 * mu1, 100 * mu2, v))
        if items and items[0][0] == 2: print("   (aucune piste validee : ne rien miser)")
    return valid

def scan(files, loop=False, max_min=340):
    rows = load(files)
    cells = table(rows)
    print("historique:", len(rows), "matchs")
    done = set(); t0 = time.time()
    while True:
        rid, evs = open_round()
        if rid is None:
            if not loop: sys.exit("Aucun round ouvert aux paris trouve (reessaie dans une minute).")
        elif rid not in done:
            done.add(rid)
            print("\nround", rid, "|", len(evs), "matchs ouverts | heure UTC:", datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S"))
            valid = report(evs, cells)
            if valid:
                telegram("SIGNAL VALIDE - round %s\n" % rid + "\n".join(valid) + "\n\nPari non garanti. Misez avec prudence.")
            else:
                print("Rien envoye sur Telegram (aucun SIGNAL VALIDE).")
        if not loop or time.time() - t0 > max_min * 60: break
        time.sleep(20)

if __name__ == "__main__":
    av = sys.argv[1:]; mm = 340
    if "--max-minutes" in av:
        k = av.index("--max-minutes"); mm = int(av[k + 1]); del av[k:k + 2]
    scan([a for a in av if not a.startswith("--")] or glob.glob("data/*.csv"), loop="--loop" in av, max_min=mm)
