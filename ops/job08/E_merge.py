import json,yaml,glob
from datetime import date
ROOT="/home/zaid/palestine-v2"
Q={int(q["idx"]):q for q in (json.loads(l) for l in open(f"{ROOT}/data/raw/jobs/08/E.review/queue.ndjson"))}
def close(a,b):
    if not a or not b: return False
    return abs(a-b)/max(1,b)<=0.03
def dd(a,b):
    try: return abs((date.fromisoformat(a)-date.fromisoformat(b)).days)
    except: return 9999
def named(a): return bool(a) and "not named" not in a
keep=[]; drop={}; seen=set()
for f in sorted(glob.glob(f"{ROOT}/data/raw/jobs/08/E.review/hunger-*.ndjson")):
    for line in open(f):
        try: v=json.loads(line)
        except: continue
        idx=int(v["idx"])
        if idx not in Q: continue
        seen.add(idx)
        if v.get("verdict")=="keep":
            pr=v.get("prisoners"); dos=v.get("day_of_strike")
            pr=int(float(pr)) if pr not in (None,"",0) else 0
            dos=int(float(dos)) if dos not in (None,"",0) else 0
            if pr<=0 and dos<=0: continue
            row={"doc":Q[idx]["doc"],"idx":idx,"date":v.get("date") or Q[idx]["date"],
                 "prisoners":pr,"day_of_strike":dos or None,"prison":v.get("prison"),
                 "kind":v.get("kind") if v.get("kind") in ("mass","individual","solidarity") else "mass",
                 "name":v.get("name"),"authority":v.get("authority"),
                 "qualifier":v.get("qualifier") if v.get("qualifier") in ("more_than","about","at_least","up_to") else None,
                 "note":v.get("note") or ""}
            hit=None
            for o in keep:
                if (o["kind"]!="solidarity")!=(row["kind"]!="solidarity"): continue
                if o["kind"]=="solidarity" and row["kind"]=="solidarity" and o.get("name")!=row.get("name"): continue
                if o["kind"]=="individual" and row["kind"]=="individual" and o.get("name")!=row.get("name"): continue
                if o.get("prison") and row.get("prison") and o["prison"]!=row["prison"]: continue
                if o.get("day_of_strike") and row.get("day_of_strike") and o["day_of_strike"]!=row["day_of_strike"]: continue
                if not close(o["prisoners"],row["prisoners"]): continue
                if dd(o["date"],row["date"])>2: continue
                hit=o; break
            if hit:
                if named(row.get("authority")) and not named(hit.get("authority")):
                    hit["authority"]=row["authority"]
                hit["note"]=(hit.get("note","")+f" also {row['doc']}:{idx}.").strip(); continue
            keep.append(row)
        else:
            drop[idx]=v.get("reason") or "not a strike statement"
for idx in Q:
    if idx not in seen: drop.setdefault(idx,"not read")
keep.sort(key=lambda e:(e["date"],e["doc"],e["idx"]))
out={"reviewed_on":"2026-10-20","method":"judgment pass: every sentence read","hunger_strikes":keep,"dropped":{"hunger_strikes":drop}}
yaml.safe_dump(out,open(f"{ROOT}/data/raw/jobs/08/hunger_strikes.review.yaml","w"),allow_unicode=True,sort_keys=False,width=200)
print("keep",len(keep),"drop",len(drop),"queue",len(Q))
