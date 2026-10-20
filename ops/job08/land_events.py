import sys,re,csv,collections
sys.path.insert(0,"/home/zaid/jobs/job-08-lake-second-pass/ops/job08")
from lib import *
rows=load_read("land_orders")
N=re.compile(r"(\d[\d,\.]*)\s*(ألف|آلاف|مليون|ملايين)?\s*(?:دونم|دونماً|دونما|دونمات|دونمًا)")
ORD=re.compile(r"أمر|أوامر|مصادرة|مصادر|وضع اليد|استيلاء|إعلان|اعلان|قرار|إخطار|اخطار|استولت|صادرت")
BAD=re.compile(r"مخطط|ينوي|تعتزم|تهدد|سيتم|ستتم|دراسة|مقترح|تقديرات|توقع|نفى|نفي")
def val(g):
    # comma: 1-2 digits after = decimal, 3 = thousands
    if "," in g:
        a,b=g.rsplit(",",1)
        if len(b)<=2: return float(a+"."+b)
        g=g.replace(",","")
    try: return float(g)
    except: return None
ev=[]
for i,r in enumerate(rows):
    q=r.get("quote") or ""; dt=(r.get("date") or "")[:10]
    if not dt or dt[:4]>"2025": continue
    m=N.search(q)
    if not m: continue
    v=val(m.group(1))
    if v is None or v<=0: continue
    if m.group(2):
        v*= {"ألف":1000,"آلاف":1000,"مليون":1_000_000,"ملايين":1_000_000}[m.group(2)]
    if v>50000: continue
    pos=m.start()
    if BAD.search(q[max(0,pos-70):pos+70]): continue
    if not ORD.search(q[max(0,pos-90):pos+90]): continue
    p,g=place_of(q,pos)
    if not p and not g: continue
    if g not in GOVS and g!="Jerusalem": continue
    ev.append({"idx":i,"doc":r["doc_id"],"date":dt,"dunums":v,"place":p,"gov":g,
      "kind":"declaration" if re.search(r"إعلان|اعلان|أراضي دولة|اراضي دوله",q) else "order",
      "purpose":("military" if re.search(r"أغراض عسكرية|اغراض عسكريه|عسكري|طريق",q) else None),
      "qual":qualifier(q),"quote":q,"publisher":r.get("publisher"),"url":r.get("url")})
print("candidates",len(ev),"village",sum(1 for e in ev if e["place"]))
from datetime import date
ev.sort(key=lambda e:(e["date"],e["doc"]))
out=[]
for e in ev:
    hit=None
    for o in out:
        if o["gov"]==e["gov"] and (o["place"] or "")==(e["place"] or ""):
            try: dd=abs((date.fromisoformat(o["date"])-date.fromisoformat(e["date"])).days)
            except: continue
            if dd<=14 and abs(o["dunums"]-e["dunums"])/max(0.001,e["dunums"])<=0.05: hit=o; break
    if hit: hit.setdefault("others",[]).append((e["doc"],e["idx"],e["date"],e["dunums"]))
    else: out.append(e)
print("clusters",len(out))
with open("/home/zaid/palestine-v2/data/raw/jobs/08/land.events.tsv","w") as f:
    f.write("idx\tdoc\tdate\tdunums\tplace\tgov\tkind\tqual\tothers\tquote\n")
    for e in out:
        f.write("\t".join(map(str,[e["idx"],e["doc"],e["date"],e["dunums"],e["place"] or "",e["gov"] or "",e["kind"],e["qual"] or "",len(e.get("others") or []),e["quote"].replace("\t"," ")]))+"\n")
for e in out[:20]:
    print(e["date"],e["dunums"],e["place"],e["gov"],e["kind"],"|",e["quote"][:150])
