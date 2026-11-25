#!/usr/bin/env python3
"""Analyse dataset.csv (stdlib only, works in Termux).
Usage: python analyze.py [fichiers.csv ...]   (par defaut: data/*.csv)
1) Margin of the house   2) Calibration: do outcomes follow the odds?
3) ROI of blindly betting each outcome by odds bucket, with 95% interval
4) Chronological split: is any 'best' bucket from the first 70% still good on the last 30%?"""
import csv, math, sys, collections

import glob
files = sys.argv[1:] or sorted(glob.glob("data/*.csv"))
rows = [r for f in files for r in csv.DictReader(open(f))]
rows.sort(key=lambda r: (int(r["round"]), r["event_id"]))
rows = [r for r in rows if r.get("odds_1") and r.get("result")]
print("matchs:", len(rows))
if len(rows) < 300: print("(trop peu de matchs: les resultats ci-dessous ne veulent rien dire)")

def bets(rs):
    for r in rs:
        for k, o in (("1", "odds_1"), ("X", "odds_X"), ("2", "odds_2")):
            yield r["league"], k, float(r[o]), r["result"] == k
def margin(rs):
    return sum(1/float(r["odds_1"])+1/float(r["odds_X"])+1/float(r["odds_2"]) for r in rs)/len(rs)-1
print("marge moyenne 1X2: %.1f%%" % (100*margin(rows)))

def bucket(o): return "<1.8" if o < 1.8 else "1.8-2.5" if o < 2.5 else "2.5-3.5" if o < 3.5 else ">3.5"
def stats(bs):
    n = len(bs); w = sum(1 for b in bs if b[3])
    prof = [(b[2]-1) if b[3] else -1 for b in bs]
    roi = sum(prof)/n
    sd = (sum((p-roi)**2 for p in prof)/max(n-1, 1))**.5
    return n, w, roi, 1.96*sd/math.sqrt(n)

print("\n== Calibration (prob. implicite normalisee vs frequence reelle) ==")
cal = collections.defaultdict(lambda: [0, 0, 0.0])
for r in rows:
    inv = {k: 1/float(r[o]) for k, o in (("1", "odds_1"), ("X", "odds_X"), ("2", "odds_2"))}
    s = sum(inv.values())
    for k, v in inv.items():
        b = min(int(v/s*10), 9); c = cal[b]; c[0] += 1; c[1] += (r["result"] == k); c[2] += v/s
for b in sorted(cal):
    n, w, p = cal[b]; print("  prob %2d-%2d%%  n=%5d  attendu %.3f  reel %.3f" % (b*10, b*10+10, n, p/n, w/n))

print("\n== ROI en pariant toujours 1 unite (par ligue x issue x tranche de cote) ==")
groups = collections.defaultdict(list)
for b in bets(rows): groups[(b[0], b[1], bucket(b[2]))].append(b)
res = sorted(((stats(v), k) for k, v in groups.items() if len(v) >= 50), key=lambda x: -x[0][2])
for (n, w, roi, ci), k in res[:8]:
    print("  %-20s %s %-8s n=%5d  ROI %+6.1f%% +/- %.1f%%" % (k[0], k[1], k[2], n, 100*roi, 100*ci))
tests = len(res)
print("  -> %d combinaisons testees: avec autant de tests, des ROI positifs par hasard sont NORMAUX." % tests)

print("\n== Test hors echantillon (ordre chronologique 70/30) ==")
cut = int(len(rows)*.7); train, test = rows[:cut], rows[cut:]
g_tr = collections.defaultdict(list)
for b in bets(train): g_tr[(b[0], b[1], bucket(b[2]))].append(b)
best = sorted(((stats(v)[2], k) for k, v in g_tr.items() if len(v) >= 50), reverse=True)[:5]
g_te = collections.defaultdict(list)
for b in bets(test): g_te[(b[0], b[1], bucket(b[2]))].append(b)
tot = []
for roi_tr, k in best:
    t = g_te.get(k, [])
    if t:
        n, w, roi, ci = stats(t); tot += t
        print("  %-20s %s %-8s train ROI %+6.1f%%  ->  test ROI %+6.1f%% +/- %.1f%% (n=%d)" % (k[0], k[1], k[2], 100*roi_tr, 100*roi, 100*ci, n))
if tot:
    n, w, roi, ci = stats(tot)
    print("  Les 5 'meilleurs' reunis sur le test: ROI %+.1f%% +/- %.1f%% (n=%d)" % (100*roi, 100*ci, n))
print("\nUn signal n'est credible que si le ROI du TEST est positif ET l'intervalle ne contient pas 0,")
print("sur beaucoup de matchs, et reste vrai sur de nouvelles donnees.")
