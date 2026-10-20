import gzip,json,glob,re,os,unicodedata
ROOT="/home/zaid/palestine-v2"
CPS=json.load(open(f"{ROOT}/data/raw/jobs/08/checkpoints.json"))
def norm(s):
    s=unicodedata.normalize("NFKC",s or "")
    s=re.sub(r"[\u064B-\u0652\u0670\u0640]","",s)
    s=s.replace("أ","ا").replace("إ","ا").replace("آ","ا").replace("ى","ي").replace("ة","ه")
    return re.sub(r"\s+"," ",s).strip()
names=[]
for c in CPS:
    forms=[c.get("ar"),c.get("en")]
    al=c.get("aliases")
    if isinstance(al,str):
        try: al=json.loads(al)
        except: al=[al]
    if isinstance(al,list): forms+=al
    for f in forms:
        if not f: continue
        n=norm(str(f))
        if len(n)>=4: names.append((n,c["place_id"],c.get("ar") or f))
names.sort(key=lambda x:-len(x[0]))
STATE=[("closed",r"اغلق|اغلقت|اغلاق|مغلق|مغلقه|اقفل|اقفال|اغلقت"),
       ("opened",r"فتح|فتحت|اعاد فتح|اعاده فتح|فتحه|مفتوح"),
       ("partial",r"جزئي|جزئيا|جزئيه"),
       ("restricted",r"تشديد|قيود|تقييد|منع|عرقله")]
STATE=[(k,re.compile(v)) for k,v in STATE]
def sents(t):
    t=re.sub(r"\s+"," ",t or "")
    return re.split(r"(?<=[.!؟])\s+|\n+",t)
out={}
for p in glob.glob(f"{ROOT}/data/raw/jobs/08/corpus/*.ndjson.gz"):
    for line in gzip.open(p,"rt",errors="replace"):
        try: r=json.loads(line)
        except: continue
        d=(r.get("date") or "")[:10]
        if not ("2003-01-01"<=d<="2023-12-31"): continue
        body=r.get("body") or ""
        if "حاجز" not in body: continue
        for s in sents(body):
            if "حاجز" not in s: continue
            ns=norm(s)
            for name,pid,ar in names:
                if name not in ns: continue
                # state cue near the name
                i=ns.find(name); window=ns[max(0,i-80):i+len(name)+80]
                st=None
                for k,rx in STATE:
                    if rx.search(window): st=k; break
                if not st: continue
                key=(r["doc_id"],pid,st,s[:120])
                if key in out: continue
                out[key]={"doc_id":r["doc_id"],"date":d,"publisher":r.get("source"),"url":r.get("url"),
                          "family":"checkpoint_closure","cue":"حاجز","number":None,"printed":None,"unit":None,
                          "place_hint":ar,"authority_hint":None,"quote":s[:300],
                          "checkpoint_id":pid,"checkpoint_ar":ar,"state":st}
print("clauses",len(out))
with open(f"{ROOT}/data/raw/jobs/08/J.review/corpus-clauses.ndjson","w") as f:
    for v in out.values(): f.write(json.dumps(v,ensure_ascii=False)+"\n")
