import json,yaml,glob
from datetime import date
ROOT="/home/zaid/palestine-v2"
Q={int(q["idx"]):q for q in (json.loads(l) for l in open(f"{ROOT}/data/raw/jobs/08/G.review/queue.ndjson"))}
def close(a,b):
    if not a or not b: return False
    return abs(a-b)/max(1,b)<=0.03
keep=[]; drop={}; seen=set()
for f in sorted(glob.glob(f"{ROOT}/data/raw/jobs/08/G.review/attacks-*.ndjson")):
    for line in open(f):
        try: v=json.loads(line)
        except: continue
        idx=int(v["idx"])
        if idx not in Q: continue
        seen.add(idx)
        if v.get("verdict")=="keep":
            rows=[]
            for r in v.get("rows") or []:
                try: n=int(float(r.get("attacks")))
                except: continue
                if n<0: continue
                x={"place":r.get("place") or "West Bank","attacks":n}
                q=r.get("qualifier")
                if q in ("more_than","about","at_least","up_to"): x["qualifier"]=q
                rows.append(x)
            if not rows or not v.get("from") or not v.get("to"): continue
            t={"doc":Q[idx]["doc"],"idx":idx,"authority":v.get("authority"),
               "from":v["from"],"to":v["to"],"precision":v.get("precision") if v.get("precision") in ("day","month","year","period") else "period",
               "rows":rows,"note":v.get("note") or ""}
            hit=None
            for o in keep:
                if (o.get("authority") or "")!=(t.get("authority") or ""): continue
                if o["from"]!=t["from"]: continue
                if abs((date.fromisoformat(o["to"])-date.fromisoformat(t["to"])).days)>2: continue
                tot=lambda y: next((r["attacks"] for r in y["rows"] if r["place"]=="West Bank"),0)
                if close(tot(o),tot(t)): hit=o; break
            if hit:
                hit["note"]=(hit.get("note","")+f" also {t['doc']}:{idx}.").strip(); continue
            keep.append(t)
        else:
            drop[idx]=v.get("reason") or "not a period tally"
for idx in Q:
    if idx not in seen: drop.setdefault(idx,"not read")
keep.sort(key=lambda e:(e["from"],e["doc"],e["idx"]))
yaml.safe_dump({"reviewed_on":"2026-10-20","method":"judgment pass: every sentence read","attack_tallies":keep,"dropped":{"attack_tallies":drop}},open(f"{ROOT}/data/raw/jobs/08/attack_tallies.review.yaml","w"),allow_unicode=True,sort_keys=False,width=200)
print("keep",len(keep),"drop",len(drop))
