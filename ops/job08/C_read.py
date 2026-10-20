import gzip,json,glob,yaml,collections,os
ROOT="/home/zaid/palestine-v2"; OUT=f"{ROOT}/data/raw/jobs/08"
rv=yaml.safe_load(open(f"{ROOT}/db/reference/job06_review.yaml"))
skip={e["doc"] for e in rv.get("gaza_trucks") or []}
for k in (rv.get("dropped",{}).get("gaza_trucks") or {}):
    skip.add(int(str(k).split("#")[0]))
rows=[]
for p in glob.glob(f"{ROOT}/data/raw/jobs/06/lake/*.ndjson.gz"):
    for line in gzip.open(p,"rt",errors="replace"):
        try: r=json.loads(line)
        except: continue
        if r.get("family")!="aid_trucks" or r.get("doc_id") in skip: continue
        rows.append(r)
rows.sort(key=lambda r:(r.get("doc_id") or 0,r.get("date") or "",r.get("printed") or "",r.get("quote") or ""))
with gzip.open(f"{OUT}/gaza_trucks.read.ndjson.gz","wt",encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
print("read",len(rows),"docs",len({r['doc_id'] for r in rows}),"skipped",len(skip))
print(dict(sorted(collections.Counter((r.get('date') or '')[:4] for r in rows).items())))
for i in range(0,len(rows),max(1,len(rows)//5)):
    r=rows[i]; print(r["doc_id"],(r.get("date") or "")[:10],r.get("number"),r.get("unit"),"|",(r.get("quote") or "")[:160])
