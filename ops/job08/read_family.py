#!/usr/bin/env python3
"""Write every lake record of one JOB-08 family to <family>.read.ndjson.gz,
in one fixed order (doc_id, date, quote), and print the shape.
JOB-06 settled documents are skipped for A/B."""
import gzip, json, glob, sys, os, collections, yaml
ROOT="/home/zaid/palestine-v2"
LAKE=f"{ROOT}/data/raw/jobs/06/lake/*.ndjson.gz"
OUT=f"{ROOT}/data/raw/jobs/08"
os.makedirs(OUT,exist_ok=True)
fam=sys.argv[1]
skip=set()
if fam in ("trees_uprooted","land_orders"):
    rv=yaml.safe_load(open(f"{ROOT}/db/reference/job06_review.yaml"))
    if fam=="trees_uprooted":
        skip |= {e["doc"] for e in rv.get("trees_incidents") or []}
        skip |= {e["doc"] for e in rv.get("trees_tallies") or []}
        for k in (rv.get("dropped",{}).get("trees_uprooted") or {}):
            skip.add(int(str(k).split("#")[0]))
    else:
        skip |= {e["doc"] for e in rv.get("land_orders") or []}
        for k in (rv.get("dropped",{}).get("land_orders") or {}):
            skip.add(int(str(k).split("#")[0]))
rows=[]
for p in glob.glob(LAKE):
    with gzip.open(p,"rt",encoding="utf-8",errors="replace") as f:
        for line in f:
            try: r=json.loads(line)
            except: continue
            if r.get("family")!=fam: continue
            if r.get("doc_id") in skip: continue
            rows.append(r)
rows.sort(key=lambda r:(r.get("doc_id") or 0, r.get("date") or "", r.get("printed") or "", r.get("quote") or ""))
out=f"{OUT}/{fam}.read.ndjson.gz"
with gzip.open(out,"wt",encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
print(fam,"read",len(rows),"docs",len({r['doc_id'] for r in rows}),"skipped docs",len(skip))
print("years",dict(sorted(collections.Counter((r.get('date') or '')[:4] for r in rows).items())))
# 8 samples spread over time
for i in [0,len(rows)//7,len(rows)//3,len(rows)//2,2*len(rows)//3,5*len(rows)//6,len(rows)-1]:
    if 0<=i<len(rows):
        r=rows[i]; print("SAMPLE",r["doc_id"],r["date"][:10] if r.get("date") else "",r.get("number"),r.get("unit"),"|",(r.get("quote") or "")[:220])
