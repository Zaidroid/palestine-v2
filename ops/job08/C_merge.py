import json,yaml,glob
from datetime import date
ROOT="/home/zaid/palestine-v2"
Q={int(q["idx"]):q for q in (json.loads(l) for l in open(f"{ROOT}/data/raw/jobs/08/C.review/queue.ndjson"))}
def close(a,b):
    if not a or not b: return False
    return abs(a-b)/max(1,b)<=0.05
def dd(a,b):
    try: return abs((date.fromisoformat(a)-date.fromisoformat(b)).days)
    except: return 9999
keep=[]; drop={}; seen=set()
for f in sorted(glob.glob(f"{ROOT}/data/raw/jobs/08/C.review/trucks-*.ndjson")):
    for line in open(f):
        try: v=json.loads(line)
        except: continue
        idx=int(v["idx"])
        if idx not in Q: continue
        seen.add(idx)
        if v.get("verdict")=="keep":
            t=v.get("trucks")
            try: t=int(float(t))
            except: continue
            if t<=0: continue
            row={"doc":Q[idx]["doc"],"idx":idx,"trucks":t,
                 "scope":v.get("scope") if v.get("scope") in ("aid","all","fuel","commercial") else "aid",
                 "authority":v.get("authority"),"qualifier":v.get("qualifier") if v.get("qualifier") in ("more_than","about","at_least","up_to") else None,
                 "note":v.get("note") or ""}
            if v.get("day"): row["day"]=v["day"]
            elif v.get("from") and v.get("to"): row["from"]=v["from"]; row["to"]=v["to"]
            else: continue
            hit=None
            for o in keep:
                if (o.get("scope") or "aid")!=(row.get("scope") or "aid"): continue
                if (o.get("authority") or "")!=(row.get("authority") or ""): continue
                if not close(o["trucks"],row["trucks"]): continue
                if row.get("day") and o.get("day") and dd(row["day"],o["day"])<=21: hit=o; break
                if row.get("from") and o.get("from")==row.get("from") and o.get("to")==row.get("to"): hit=o; break
                if o["doc"]==row["doc"]: hit=o; break
            if hit:
                hit["note"]=(hit.get("note","")+f" also {row['doc']}:{idx}.").strip(); continue
            keep.append(row)
        else:
            drop[idx]=v.get("reason") or "not a truck count"
for idx in Q:
    if idx not in seen: drop.setdefault(idx,"not read")
keep.sort(key=lambda e:(e.get("day") or e.get("from") or "",e["doc"],e["idx"]))
out={"reviewed_on":"2026-10-20","method":"judgment pass: every sentence read","gaza_trucks_stated":keep,
     "dropped":{"gaza_trucks":drop}}
yaml.safe_dump(out,open(f"{ROOT}/data/raw/jobs/08/gaza_trucks.review.yaml","w"),allow_unicode=True,sort_keys=False,width=200)
print("keep",len(keep),"drop",len(drop),"queue",len(Q))
