import sys,re,collections,json
sys.path.insert(0,"/home/zaid/jobs/job-08-lake-second-pass/ops/job08")
from lib import *
rows=load_read("trees_uprooted")
N=re.compile(r"(\d[\d,\.]*)\s*(ألف|آلاف|مليون|ملايين)?\s*(?:شجرة|أشجار|شتلة|غرسة|فسيلة)")
N2=re.compile(r"(?:شجرة|أشجار|شتلة|غرسة)[^\d]{0,15}(\d[\d,\.]*)")
CUT=re.compile(r"اقتلع|اقتلاع|تقتلع|يقتلع|قلع|قطع|تقطع|يقطع|تقطيع|حرق|أحرق|احرق|يحرق|سمم|تسميم|كسر|يكسر|تحطيم|حطم|تخريب|جرف|تجريف|جرفت|يجرف|دمر|تدمير|دمرت|قص|تنشير")
AGG=re.compile(r"خلال|منذ|شهر|شهري|سنوي|أسبوعي|اسبوعي|نصف|حصيلة|إجمالي|اجمالي|مجموع|بلغ|تقريبا|مئات|عشرات|آلاف|الاف|%|في المئة|إحصائي|احصائي|تقرير")
import json as _json
SETTLE={r["ar"] for r in _json.load(open("/home/zaid/palestine-v2/data/raw/settlements/settlement_names.json")) if r.get("ar")}
SETTLE |= {"يتسهار","بروخين","عادي عاد","إيبي هناحل","كرني شمرون","ميفودوتان","حفات ماعون","سوسيا","عفرا","بيت إيل","مجدال عوز","كفار عصيون","أورانيت","معاليه أدوميم","جوش عتصيون"}
def parse(g):
    s=g.replace(",","")
    try: v=float(s)
    except: return None
    if "." in g and len(g.split(".")[-1])==3 and v<1000: return round(v*1000)
    return v
def count(q):
    m=N.search(q) or N2.search(q)
    if not m: return None,None
    v=parse(m.group(1))
    if v is None: return None,None
    if m.re is N and m.lastindex and m.lastindex>=2 and m.group(2):
        v*= {"ألف":1000,"آلاف":1000,"مليون":1_000_000,"ملايين":1_000_000}[m.group(2)]
    return v,m.start()
ev=[]
for i,r in enumerate(rows):
    q=r.get("quote") or ""; dt=(r.get("date") or "")[:10]
    if not dt or dt[:4]>="2026": continue
    c,pos=count(q)
    if not c or c>10000: continue
    if not CUT.search(q[max(0,pos-80):pos+80]): continue
    if AGG.search(q[max(0,pos-80):pos+80]): continue
    if re.search(r"أخطر|اخطر|أخطار|إنذار|انذار|أوامر|اوامر|أمر عسكري|امر عسكري|سيتم|ستتم|تهدد|ينوي|يعتزم",q[max(0,pos-70):pos+70]): continue
    if c>2000 or c<5: continue
    if re.search(r"مليون|إحصائي|احصائي|تقرير|في مختلف|مختلف محافظات|في محافظات|وسلفيت|ورام الله|بلدتي|قريتي|إخطار|اخطار|أخطرت|اخطرت|نية|مقترح|سيتم|سوف|يهدد|خلال|منذ",q): continue
    if re.search(r"وثق|سجل",q) and re.search(r"اعتداء|اعتداءات",q): continue
    if re.search(r"منذ مطلع|مطلع الشهر|الشهر الجاري|خلال الشهر|شهر (?:كانون|شباط|آذار|نيسان|أيار|حزيران|تموز|آب|أيلول|تشرين)",q): continue
    if re.search(r"و\s*\d+\s*(?:أخرى|اخرى)",q): continue
    if re.search(r"وسلفيت|ورام الله|ومحافظات|في محافظات|بين بلدتي|بين قريتي|بين\s+\S+\s+و\S+",q[max(0,pos-90):pos+90]): continue
    ps=[x for x in places_in(q) if x[2] not in CITYN and x[3][0] not in {"الضفة الغربية","الضفة","قطاع غزة"}]
    if len({x[3][0] for x in ps})>1: continue
    p,g=place_of(q,pos)
    if p and norm(p) in CITYN: p=None
    if p and norm(p) in {"الزراعه","البريه","الحقوق","المنطقه","الارض","الموقع","الشارع","الطريق","الخط"}: p=None
    if g not in GOVS: continue
    if p and p in SETTLE: p=None
    if not p and not g: continue
    if not p: continue
    if not actor(q): continue
    ev.append({"idx":i,"doc":r["doc_id"],"date":dt,"trees":int(c),"place":p,"gov":g,"actor":actor(q),
               "kind":kind_near(q,pos),"qual":qualifier(q),"quote":q,"publisher":r.get("publisher"),"url":r.get("url")})
print("candidates",len(ev),"village",sum(1 for e in ev if e["place"]),"gov-only",sum(1 for e in ev if not e["place"]))
print("by year",dict(sorted(collections.Counter(e["date"][:4] for e in ev).items())))
# cluster: same day+gov+count (10%) always; within 14 days same gov+count and
# same place or a similar sentence.
from datetime import date
def sim(a,b):
    A=set(norm(a).split()); B=set(norm(b).split())
    return len(A&B)/max(1,len(A|B))
ev.sort(key=lambda e:(e["date"],e["doc"]))
out=[]
for e in ev:
    hit=None
    for o in out:
        if o["gov"]!=e["gov"]: continue
        try: dd=abs((date.fromisoformat(o["date"])-date.fromisoformat(e["date"])).days)
        except: continue
        near=abs(o["trees"]-e["trees"])/max(1,e["trees"])<=0.1
        if dd==0 and near: hit=o; break
        if dd<=3 and (o["place"] or "")==(e["place"] or "") and abs(o["trees"]-e["trees"])/max(1,e["trees"])<=0.25: hit=o; break
        if dd<=14 and o["trees"]==e["trees"] and ((o["place"] or "")==(e["place"] or "") or sim(o["quote"],e["quote"])>=0.45): hit=o; break
    if hit:
        hit.setdefault("others",[]).append((e["doc"],e["idx"],e["date"],e["trees"],e["publisher"]))
        if e["place"] and not hit.get("place2"): hit["place2"]=e["place"]
    else: out.append(e)
with open("/home/zaid/palestine-v2/data/raw/jobs/08/trees.events.tsv","w") as f:
    f.write("idx\tdoc\tdate\ttrees\tplace\tgov\tactor\tkind\tqual\tothers\tquote\n")
    for e in out:
        f.write("\t".join(map(str,[e["idx"],e["doc"],e["date"],e["trees"],e["place"] or "",e["gov"] or "",e["actor"] or "",e["kind"] or "",e["qual"] or "",len(e.get("others") or []),e["quote"].replace("\t"," ")]))+"\n")
for e in out[:25]:
    print(e["date"],e["trees"],e["place"],e["gov"],e["actor"],e["kind"],"|",e["quote"][:150])
