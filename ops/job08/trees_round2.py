import sys,re,csv,json,collections,yaml
from datetime import date,datetime
sys.path.insert(0,"/home/zaid/jobs/job-08-lake-second-pass/ops/job08")
from lib import *

ROOT="/home/zaid/palestine-v2"
rows=load_read("trees_uprooted")
rv=yaml.safe_load(open(f"{ROOT}/data/raw/jobs/08/trees_uprooted.review.yaml"))
fx=yaml.safe_load(open(f"{ROOT}/db/reference/job08_review_fixes.yaml"))["trees_uprooted"]
drops={tuple(map(int,k.split(":"))) for k in fx["drop"]}
fix={tuple(map(int,k.split(":"))):v for k,v in fx["fix"].items()}
reps=[]
for e in rv["trees_incidents"]:
    if (e["doc"],e["idx"]) in drops: continue
    e.update(fix.get((e["doc"],e["idx"]),{})); e["_rep"]=True; reps.append(e)
REPKEY={(e["doc"],e["idx"]) for e in reps}
N=re.compile(r"(\d[\d,\.]*)\s*(ألف|آلاف|مليون|ملايين)?\s*(?:شجرة|أشجار|شتلة|غرسة|فسيلة)")
N2=re.compile(r"(?:شجرة|أشجار|شتلة|غرسة)[^\d]{0,15}(\d[\d,\.]*)")
V=re.compile(r"اقتلع|اقتلاع|تقتلع|يقتلع|يقتلعون|قلع|يقلع|قطع|تقطع|يقطع|يقطعون|تقطيع|أحرق|احرق|يحرق|يحرقون|حرق|كسر|يكسر|يكسرون|تكسير|حطم|يحطم|يحطمون|تحطيم|جرف|تجريف|جرفت|يجرف|يجرفون|أتلف|اتلف|يتلف|يتلفون|تلف|سمم|تسمم|يسمم|خرب|تخريب|يخرب|قص|تنشير|إحراق|احراق|إتلاف|اتلاف|تدمير|تحطيم|أعدم|اعدام|احتراق|التهمت|هدم|دمر")
MONTHS={"كانون الثاني":1,"يناير":1,"شباط":2,"فبراير":2,"آذار":3,"اذار":3,"مارس":3,"نيسان":4,"أبريل":4,"ابريل":4,"أيار":5,"ايار":5,"مايو":5,"حزيران":6,"يونيو":6,"تموز":7,"يوليو":7,"آب":8,"اب":8,"أغسطس":8,"اغسطس":8,"أيلول":9,"ايلول":9,"سبتمبر":9,"تشرين الأول":10,"تشرين الاول":10,"أكتوبر":10,"اكتوبر":10,"تشرين الثاني":11,"تشرين الثاني":11,"نوفمبر":11,"كانون الأول":12,"كانون الاول":12,"ديسمبر":12}
def parse_count(q):
    m=N.search(q) or N2.search(q)
    if not m: return None,None
    g=m.group(1); s=g.replace(",","")
    if "," in g:
        a,b=g.rsplit(",",1); s=a+"."+b if len(b)<=2 else s
    try: val=float(s)
    except: return None,None
    if m.re is N and m.lastindex and m.lastindex>=2 and m.group(2):
        val*= {"ألف":1000,"آلاف":1000,"مليون":1_000_000,"ملايين":1_000_000}[m.group(2)]
    return val,m.start()
def event_date(q,pub):
    q2=re.sub(r"\([^)]*\)"," ",q)
    m=re.search(r"(\d{1,2})\s*[/\-]\s*(\d{1,2})\s*[/\-]\s*(20\d\d|19\d\d)",q2)
    if m:
        d,mo,y=int(m.group(1)),int(m.group(2)),int(m.group(3))
        try: return date(y,mo,d).isoformat(),"stated"
        except: pass
    for name,mo in sorted(MONTHS.items(),key=lambda x:-len(x[0])):
        m=re.search(r"(\d{1,2})\s+"+re.escape(name)+r"\s+(20\d\d|19\d\d)",q2)
        if m:
            try: return date(int(m.group(2)),mo,int(m.group(1))).isoformat(),"stated"
            except: pass
    if re.search(r"آخرها|سابق|منذ|خلال|في عام|العام الماضي|الأسبوع الماضي|الاسبوع الماضي|شهر الماضي",q):
        return None,None
    return (pub or "")[:10],"published"
def place2(q,near):
    q2=re.sub(r"\([^)]*\)"," ",q)
    ms=[m for m in places_in(q2) if m[2] not in CITYN and norm(m[3][0][0]) not in REGION]
    if ms:
        before=[m for m in ms if m[1]<=near] or ms
        before.sort(key=lambda m:abs(m[1]-near))
        ar,gov=before[0][3][0][0],before[0][3][0][1]
        # a governorate named within 40 chars after the village fixes duplicates
        g2=gov_in(q2[before[0][1]:before[0][1]+45])
        return ar,g2 or gov
    g=gov_in(q2)
    return None,g
def qualif(q):
    if re.search(r"أكثر من|اكثر من",q): return "more_than"
    if re.search(r"ما لا يقل عن|على الأقل",q): return "at_least"
    if re.search(r"لا يتجاوز|أقل من|اقل من",q): return "up_to"
    if re.search(r"نحو|حوالي|قرابة|ما يقارب|تقريبا|تقريباً",q): return "about"
    return None
def kind2(q,pos):
    tail=q[pos:pos+40]
    if "عنب" in tail or "كرمة" in tail: return "grapevines"
    if "زيتون" in tail: return "olive"
    if re.search(r"لوز|تين|خوخ|رمان|حمضيات|مثمرة|فواكه",tail): return "fruit_trees"
    return "trees"
# prepare reps with dates
for e in reps:
    r=rows[e["idx"]]; d,_=event_date(r.get("quote") or "",r.get("date"))
    e["_date"]=d or (r.get("date") or "")[:10]
def close(a,b):
    if not a or not b: return False
    return abs(a-b)/max(1,b)<=0.2
from datetime import date as D
new=[]; reasons=collections.Counter(); cand=[]
for i,r in enumerate(rows):
    if (r["doc_id"],i) in REPKEY: continue
    q=r.get("quote") or ""; pub=(r.get("date") or "")[:10]
    c,pos=parse_count(q)
    if not c: reasons["no tree count"]+=1; continue
    if not V.search(q): reasons["no damaging verb"]+=1; continue
    if c>2000: reasons["tally, not an incident"]+=1; continue
    d,basis=event_date(q,pub)
    if not d: reasons["retrospective or no event date"]+=1; continue
    p,g=place2(q,pos)
    if not p and not g: reasons["no place in the sentence"]+=1; continue
    cand.append({"doc":r["doc_id"],"idx":i,"trees":int(c),"place":p,"gov":g,"actor":actor(q),"kind":kind2(q,pos),"qual":qualif(q),"date":d,"basis":basis,"quote":q})
print("candidates",len(cand),"reasons",reasons)
# cluster against reps and new
for cnd in cand:
    hit=None
    for e in reps:
        if e.get("gov")!=cnd["gov"]: continue
        if e.get("place") and cnd["place"] and norm(e["place"])!=norm(cnd["place"]): continue
        try: dd=abs((D.fromisoformat(e["_date"])-D.fromisoformat(cnd["date"])).days)
        except: continue
        if dd<=14 and close(cnd["trees"],e["trees"]): hit=e; break
    if hit:
        hit.setdefault("_also",[]).append((cnd["doc"],cnd["idx"],cnd["date"]))
        continue
    for e in new:
        if e["gov"]!=cnd["gov"]: continue
        if e["place"] and cnd["place"] and norm(e["place"])!=norm(cnd["place"]): continue
        try: dd=abs((D.fromisoformat(e["date"])-D.fromisoformat(cnd["date"])).days)
        except: continue
        if dd<=14 and close(cnd["trees"],e["trees"]): hit=e; break
    if hit:
        hit.setdefault("_also",[]).append((cnd["doc"],cnd["idx"],cnd["date"]))
        if cnd["basis"]=="stated" and hit.get("basis")=="published":
            hit.update({k:cnd[k] for k in ("date","basis","trees","place","gov")})
    else:
        new.append(cnd)
print("new",len(new),"reps with extra",sum(1 for e in reps if e.get("_also")))
json.dump({"new":new,"reps":[{k:v for k,v in e.items() if k!="_also"} for e in reps],
           "also":{f"{e['doc']}:{e['idx']}":e.get("_also",[]) for e in reps if e.get("_also")},
           "reasons":dict(reasons)},open(f"{ROOT}/data/raw/jobs/08/trees.round2.json","w"),ensure_ascii=False)
for e in new[:20]: print(e["date"],e["trees"],e["place"],e["gov"],e["actor"],e["kind"],"|",e["quote"][:130])
