import json,yaml,gzip,glob
from datetime import date
ROOT="/home/zaid/palestine-v2"
Q=[json.loads(l) for l in open(f"{ROOT}/data/raw/jobs/08/B.review/queue.ndjson")]
READ=[json.loads(l) for l in gzip.open(f"{ROOT}/data/raw/jobs/08/land_orders.read.ndjson.gz","rt")]
def close(a,b):
    if not a or not b: return False
    return abs(a-b)/max(1e-9,b)<=0.2
def dd(a,b):
    try: return abs((date.fromisoformat(a)-date.fromisoformat(b)).days)
    except: return 9999
keep=[]; cited=[]; drop={}
seen=set()
for f in sorted(glob.glob(f"{ROOT}/data/raw/jobs/08/B.review/orders-*.ndjson")):
    for line in open(f):
        try: v=json.loads(line)
        except: continue
        idx=int(v["idx"]); q=Q[idx]
        if v.get("verdict")=="keep":
            try: dun=float(v["dunums"])
            except: continue
            if dun<=0: continue
            row={"doc":q["doc"],"idx":idx,"n":int(v.get("n") or 1),"dunums":dun,
                 "qualifier":v.get("qualifier"),"place":v.get("place"),"gov":v.get("gov"),
                 "kind":v.get("kind") or "order","purpose":v.get("purpose"),
                 "date":v.get("date") or q["date"],"note":v.get("note") or ""}
            if row["gov"] and row["gov"] not in ("Jenin","Tubas","Tulkarm","Nablus","Qalqilya","Salfit","Ramallah","Jericho","Jerusalem","Bethlehem","Hebron"):
                row["note"]=(row["note"]+" governorate corrected from "+row["gov"]).strip(); row["gov"]=None
            # fold duplicate into an earlier row
            hit=None
            for o in keep:
                if row["gov"] and o["gov"] and row["gov"]!=o["gov"]: continue
                if row["place"] and o["place"] and row["place"]!=o["place"]: continue
                if close(row["dunums"],o["dunums"]) and dd(row["date"],o["date"])<=14: hit=o; break
            if hit:
                hit["note"]=(hit["note"]+f" also {row['doc']}:{idx}.").strip(); continue
            keep.append(row); seen.add(idx)
        elif v.get("verdict")=="cited":
            cited.append(v); seen.add(idx)
        else:
            drop[idx]=v.get("reason") or "not one order"
# any queue row without verdict: drop unread (should not happen)
for q in Q:
    i=int(q["idx"])
    if i not in seen: drop.setdefault(i,"not read")
keep.sort(key=lambda e:(e["date"],e["doc"],e["idx"]))
out={"reviewed_on":"2026-10-20","method":"judgment pass: every sentence read",
     "land_orders":keep,"cited":cited,"dropped":{"land_orders":drop}}
yaml.safe_dump(out,open(f"{ROOT}/data/raw/jobs/08/land_orders.review.yaml","w"),allow_unicode=True,sort_keys=False,width=200)
print("keep",len(keep),"cited",len(cited),"drop",len(drop))
