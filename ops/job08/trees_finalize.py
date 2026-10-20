import sys,re,json,yaml
from datetime import date
sys.path.insert(0,"/home/zaid/jobs/job-08-lake-second-pass/ops/job08")
from lib import *
ROOT="/home/zaid/palestine-v2"
SETTLE={r["ar"] for r in json.load(open(f"{ROOT}/data/raw/settlements/settlement_names.json")) if r.get("ar")}
SETTLE |= {"يتسهار","بروخين","عادي عاد","إيبي هناحل","كرني شمرون","ميفودوتان","حفات ماعون","سوسيا","عفرا","بيت إيل","مجدال عوز","كفار عصيون","أورانيت","معاليه أدوميم","جوش عتصيون","شافي شمرون"}
rows=load_read("trees_uprooted")
p=f"{ROOT}/data/raw/jobs/08/trees_uprooted.review.yaml"
rv=yaml.safe_load(open(p))
MONTHS={"كانون الثاني":1,"يناير":1,"شباط":2,"فبراير":2,"آذار":3,"اذار":3,"مارس":3,"نيسان":4,"أبريل":4,"ابريل":4,"أيار":5,"ايار":5,"مايو":5,"حزيران":6,"يونيو":6,"تموز":7,"يوليو":7,"آب":8,"اب":8,"أغسطس":8,"اغسطس":8,"أيلول":9,"ايلول":9,"سبتمبر":9,"تشرين الأول":10,"تشرين الاول":10,"أكتوبر":10,"اكتوبر":10,"تشرين الثاني":11,"نوفمبر":11,"كانون الأول":12,"كانون الاول":12,"ديسمبر":12}
def edate(q):
    q2=re.sub(r"\([^)]*\)"," ",q)
    m=re.search(r"(\d{1,2})\s*[/\-]\s*(\d{1,2})\s*[/\-]\s*(20\d\d|19\d\d)",q2)
    if m:
        try: return date(int(m.group(3)),int(m.group(2)),int(m.group(1))).isoformat()
        except: pass
    for name,mo in sorted(MONTHS.items(),key=lambda x:-len(x[0])):
        m=re.search(r"(\d{1,2})\s+"+re.escape(name)+r"\s+(20\d\d|19\d\d)",q2)
        if m:
            try: return date(int(m.group(2)),mo,int(m.group(1))).isoformat()
            except: pass
    return None
keep=[]; dropped2={}
for e in rv["trees_incidents"]:
    r=rows[e["idx"]]; q=r.get("quote") or ""
    if re.search(r"يخطر|إخطار|اخطار|أخطرت|اخطرت",q) and not re.search(r"اقتلع|قطع|أحرق|حرق|كسر|حطم",q):
        dropped2[e["idx"]]="notice to uproot, not an uprooting"; continue
    d=edate(q)
    e["date"]=d or (r.get("date") or "")[:10]
    if not d:
        e["note"]=(e.get("note")+" " if e.get("note") else "")+"date is the publication day (no day stated)."
    p0,g=place_of(q,0)
    if not e.get("place") and p0:
        e["place"]=p0
    if e.get("place") and (e["place"] in SETTLE or norm(e["place"]) in CITYN):
        e["place"]=None
    e["gov"]=e.get("gov") or g
    keep.append(e)
rv["trees_incidents"]=keep
for k,v in dropped2.items(): rv["dropped"]["trees_uprooted"][k]=v
yaml.safe_dump(rv,open(p,"w"),allow_unicode=True,sort_keys=False,width=200)
print("kept",len(keep),"dropped extra",len(dropped2),"tallies",len(rv["trees_tallies"]))
