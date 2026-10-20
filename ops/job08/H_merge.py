import json,yaml,glob
from datetime import date
ROOT="/home/zaid/palestine-v2"
Q={int(q["idx"]):q for q in (json.loads(l) for l in open(f"{ROOT}/data/raw/jobs/08/H.review/queue.ndjson"))}
def close(a,b):
    if not a or not b: return False
    return abs(a-b)/max(1,b)<=0.03
keep=[]; drop={}; seen=set()
for f in sorted(glob.glob(f"{ROOT}/data/raw/jobs/08/H.review/detention-*.ndjson")):
    for line in open(f):
        try: v=json.loads(line)
        except: continue
        idx=int(v["idx"])
        if idx not in Q: continue
        seen.add(idx)
        if v.get("verdict")=="keep":
            try: orders=int(float(v.get("orders")))
            except: continue
            if orders<=0: continue
            stock=bool(v.get("stock"))
            t={"doc":Q[idx]["doc"],"idx":idx,"authority":v.get("authority"),
               "from":v.get("from"),"to":v.get("to"),
               "precision":v.get("precision") if v.get("precision") in ("day","month","year") else ("day" if not stock else None),
               "orders":orders,
               "qualifier":v.get("qualifier") if v.get("qualifier") in ("more_than","about","at_least","up_to") else None,
               "note":v.get("note") or ""}
            if v.get("new_orders") is not None: t["new_orders"]=int(float(v["new_orders"]))
            if v.get("renewals") is not None: t["renewals"]=int(float(v["renewals"]))
            if stock: t["stock"]=True
            elif not t["from"] or not t["to"]: continue
            hit=None
            for o in keep:
                if (o.get("authority") or "")!=(t.get("authority") or ""): continue
                if bool(o.get("stock"))!=bool(t.get("stock")): continue
                if not close(o["orders"],t["orders"]): continue
                if o.get("from")!=t.get("from"): continue
                if o.get("to")!=t.get("to"): continue
                hit=o; break
            if hit: hit["note"]=(hit.get("note","")+f" also {t['doc']}:{idx}.").strip(); continue
            keep.append(t)
        else: drop[idx]=v.get("reason") or "not an orders tally"
for idx in Q:
    if idx not in seen: drop.setdefault(idx,"not read")
keep.sort(key=lambda e:(e.get("from") or e.get("date") or "",e["doc"],e["idx"]))
yaml.safe_dump({"reviewed_on":"2026-10-20","method":"judgment pass: every sentence read","admin_detention_tallies":keep,"dropped":{"admin_detention_tallies":drop}},open(f"{ROOT}/data/raw/jobs/08/admin_detention.review.yaml","w"),allow_unicode=True,sort_keys=False,width=200)
print("keep",len(keep),"drop",len(drop))
