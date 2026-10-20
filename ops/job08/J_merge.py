import json,yaml,glob,gzip,re,unicodedata
ROOT="/home/zaid/palestine-v2"
def norm(s):
    s=unicodedata.normalize("NFKC",s or "")
    s=re.sub(r"[\u064B-\u0652\u0670\u0640]","",s)
    s=s.replace("أ","ا").replace("إ","ا").replace("آ","ا").replace("ى","ي").replace("ة","ه")
    return re.sub(r"\s+"," ",s).strip()
rows=[json.loads(l) for l in gzip.open(f"{ROOT}/data/raw/jobs/08/checkpoint_states.read.ndjson.gz","rt")]
lakeQ={int(q["idx"]):q for q in (json.loads(l) for l in open(f"{ROOT}/data/raw/jobs/08/J.review/queue.ndjson"))}
pub={r["doc_id"]:r.get("publisher") for r in rows}
cand={int(v["cid"]):v for v in (json.loads(l) for l in open(f"{ROOT}/data/raw/jobs/08/J.review/corpus-unique.ndjson"))}
def auth(a,doc):
    if not a or a=="<publisher> (not named in the sentence)":
        p=pub.get(doc) or "unknown outlet"
        return f"{p} (not named in the sentence)"
    return a
rows_out=[]; lake_drop={}; corpus_keep=[]; corpus_drop=0
# lake keeps
for f in glob.glob(f"{ROOT}/data/raw/jobs/08/J.review/states-lake-*.ndjson"):
    for line in open(f):
        try: v=json.loads(line)
        except: continue
        idx=int(v["idx"]); q=lakeQ.get(idx)
        if not q: continue
        if v.get("verdict")=="keep":
            rows_out.append({"doc":q["doc"],"idx":idx,"date":v.get("date") or q["date"],
                "checkpoint_ar":v.get("checkpoint_ar"),"checkpoint_id":v.get("checkpoint_id"),
                "state":v.get("state"),"who":v.get("who") or "army",
                "authority":auth(v.get("authority"),q["doc"]),"note":v.get("note") or ""})
        else: lake_drop[idx]=v.get("reason") or "not a checkpoint state"
seen=set()
for f in glob.glob(f"{ROOT}/data/raw/jobs/08/J.review/states-corpus-*.ndjson"):
    for line in open(f):
        try: v=json.loads(line)
        except: continue
        cid=int(v["cid"]); c=cand.get(cid)
        if not c: continue
        if v.get("verdict")=="keep":
            corpus_keep.append((cid,v,c))
        else: corpus_drop+=1
# append corpus kept to read file, assign idx
corpus_keep.sort(key=lambda x:x[0])
for cid,v,c in corpus_keep:
    rec=dict(c); rec["doc_id"]=c["doc_id"]; rec["date"]=c.get("date"); rec["idx"]=len(rows)
    rows.append(rec)
    rows_out.append({"doc":c["doc_id"],"idx":rec["idx"],"date":v.get("date") or c["date"],
        "checkpoint_ar":v.get("checkpoint_ar") or c.get("checkpoint_ar"),
        "checkpoint_id":v.get("checkpoint_id") if v.get("checkpoint_id") is not None else c.get("checkpoint_id"),
        "state":v.get("state") or c.get("state"),"who":v.get("who") or "army",
        "authority":auth(v.get("authority"),c["doc_id"]),"note":v.get("note") or ""})
# dedupe
keep=[]; folded=0
def named(a): return bool(a) and "not named" not in a
for e in sorted(rows_out,key=lambda x:(x["date"],x["doc"],x["idx"])):
    key=(e.get("checkpoint_id") or norm(e.get("checkpoint_ar")),e.get("state"),e.get("date"))
    hit=None
    for o in keep:
        if (o.get("checkpoint_id") or norm(o.get("checkpoint_ar")),o.get("state"),o.get("date"))==key: hit=o; break
    if hit:
        if named(e.get("authority")) and not named(hit.get("authority")): hit["authority"]=e["authority"]
        hit["note"]=(hit.get("note","")+f" also {e['doc']}:{e['idx']}.").strip(); folded+=1
    else: keep.append(e)
with gzip.open(f"{ROOT}/data/raw/jobs/08/checkpoint_states.read.ndjson.gz","wt",encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
yaml.safe_dump({"reviewed_on":"2026-10-20","method":"judgment pass: lake sentences + corpus clauses","checkpoint_states":keep,"dropped":{"checkpoint_states":lake_drop}},open(f"{ROOT}/data/raw/jobs/08/checkpoint_states.review.yaml","w"),allow_unicode=True,sort_keys=False,width=200)
print("keep",len(keep),"lake drop",len(lake_drop),"corpus keep",len(corpus_keep),"corpus drop",corpus_drop,"folded",folded,"read",len(rows))
