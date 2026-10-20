import json,yaml
from datetime import date
ROOT="/home/zaid/palestine-v2"
M=json.load(open(f"{ROOT}/data/raw/jobs/08/A.review/merged.json"))
inc=[dict(e) for e in M["rev"]]
seen={(e["doc"],e["idx"]) for e in inc}
def close(a,b):
    if not a or not b: return False
    return abs(a-b)/max(1,b)<=0.2
def dd(a,b):
    try: return abs((date.fromisoformat(a)-date.fromisoformat(b)).days)
    except: return 999
fold=0
for e in sorted(M["new"],key=lambda x:x.get("date") or ""):
    if (e["doc"],e["idx"]) in seen: continue
    hit=None
    for o in inc:
        if o.get("gov")!=e.get("gov"): continue
        if o.get("place") and e.get("place") and o["place"]!=e["place"]: continue
        if close(e.get("trees"),o.get("trees")) and dd(e.get("date"),o.get("date"))<=14: hit=o; break
    if hit:
        hit["note"]=(hit.get("note","")+f" also {e['doc']}:{e['idx']} ({e['date']}).").strip(); fold+=1; continue
    inc.append(e); seen.add((e["doc"],e["idx"]))
print("incidents",len(inc),"folded new",fold,"tallies",len(M["tallies"]))
json.dump({"incidents":inc,"tallies":M["tallies"]},open(f"{ROOT}/data/raw/jobs/08/A.review/prelim.json","w"),ensure_ascii=False)
