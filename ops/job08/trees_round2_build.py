import sys,json,re,yaml,collections
from datetime import date
sys.path.insert(0,"/home/zaid/jobs/job-08-lake-second-pass/ops/job08")
from lib import *
ROOT="/home/zaid/palestine-v2"
import json as _json
SETTLE={r["ar"] for r in _json.load(open(f"{ROOT}/data/raw/settlements/settlement_names.json")) if r.get("ar")}
SETTLE |= {"يتسهار","بروخين","عادي عاد","إيبي هناحل","كرني شمرون","ميفودوتان","حفات ماعون","سوسيا","عفرا","بيت إيل","مجدال عوز","كفار عصيون","أورانيت","معاليه أدوميم","جوش عتصيون","شافي شمرون"}
rows=load_read("trees_uprooted")
D=json.load(open(f"{ROOT}/data/raw/jobs/08/trees.round2.json"))
reps=D["reps"]; new=[e for e in D["new"] if e["date"][:4]<="2025"]
for e in reps:
    e.pop("_rep",None); e.pop("_date",None)
# post-filter new
kept_new=[]; drop_new={}
for e in new:
    q=e["quote"]; p=e["place"]; g=e["gov"]
    ps=places_in(re.sub(r"\([^)]*\)"," ",q))
    vills={m[3][0][0] for m in ps if m[2] not in CITYN and norm(m[3][0][0]) not in REGION}
    if len(vills)>1:
        drop_new[f"{e['doc']}:{e['idx']}"]="two villages in one sentence; one row per event needs one place"; continue
    if re.search(r"جدار الفصل|الجدار الفاصل|الجدار",q) and e["trees"]>=1000:
        drop_new[f"{e['doc']}:{e['idx']}"]="wall-impact statement, not one incident"; continue
    if re.search(r"بعد أقل من|في عام 20|منذ|خلال الأعوام|خلال السنوات",q) and not re.search(r"\d{1,2}\s*[/\-]\s*\d{1,2}\s*[/\-]\s*20\d\d",q):
        drop_new[f"{e['doc']}:{e['idx']}"]="retrospective, no event date"; continue
    if p and (p in SETTLE or norm(p) in CITYN):
        p=None; e["note"]="settlement/city name removed from place; governorate only"
    if not g:
        drop_new[f"{e['doc']}:{e['idx']}"]="no governorate in the sentence"; continue
    e["place"]=p; kept_new.append(e)
print("reps",len(reps),"new",len(kept_new),"drop new",len(drop_new))
# tallies: doc -> (from,to,precision,authority,rows,caution,note)
T={
219071:("2006-01-01","2006-12-31","year","ARIJ (Applied Research Institute – Jerusalem), statistic for 2006",[("all","West Bank",20300,None)],None,None),
2294140:("2023-01-01","2023-06-30","day","Colonization and Wall Resistance Commission, half-year 2023",[("olive","West Bank",8340,None)],None,"the sentence says 8,340 olive trees in 140 attacks."),
2319854:("2024-09-01","2024-09-30","month","Colonization and Wall Resistance Commission, monthly report (September 2024)",[("all","West Bank",699,None),("olive","West Bank",694,None)],None,None),
2325415:("2024-01-01","2024-12-31","year","Colonization and Wall Resistance Commission, annual report 2024",[("all","West Bank",14212,None),("olive","West Bank",10459,None)],None,None),
2343845:("2023-10-07","2025-10-08","day","Colonization and Wall Resistance Commission, cumulative since 7 October 2023",[("all","West Bank",48728,None),("olive","West Bank",37237,None)],None,"cumulative, dated at its period."),
2346503:("2025-10-01","2025-10-31","month","Colonization and Wall Resistance Commission, monthly report (October 2025)",[("olive","West Bank",1200,None)],None,None),
310475:("2025-12-19","2025-12-26","day","Ministry of Agriculture, week before 26 December 2025",[("all","West Bank",8000,"more_than")],"the week's dates are inferred from 'during one week' published 26 Dec.",None),
234894:("2025-01-01","2025-11-01","day","ARIJ, since the start of 2025",[("all","West Bank",13000,"about")],None,"cumulative since 1 January 2025."),
}
idx_of={}
for i,r in enumerate(rows): idx_of.setdefault(r["doc_id"],i)
tallies=[]
for doc,(f,t,pr,auth,rr,caut,note) in T.items():
    if doc not in idx_of: print("MISSING tally doc",doc); continue
    tallies.append({"doc":doc,"idx":idx_of[doc],"authority":auth,"from":f,"to":t,"precision":pr,
      **({"caution":caut} if caut else {}),**({"note":note} if note else {}),
      "rows":[{"measure":m,"place":pl,"trees":n,**({"qualifier":q} if q else {})} for m,pl,n,q in rr]})
print("tallies",len(tallies))
# dropped map: category reasons, specific for known drops
dropped={}
inc_keys={(e["doc"],e["idx"]) for e in reps}|{(e["doc"],e["idx"]) for e in kept_new}
folded=set()
for a in (D.get("also") or {}).values():
    for d,i,_ in a: folded.add((d,i))
for i,r in enumerate(rows):
    if (r["doc_id"],i) in inc_keys or (r["doc_id"],i) in folded: continue
    q=r.get("quote") or ""
    if not re.search(r"\d",q): dropped[i]="no tree count"; continue
    if not re.search(r"اقتلع|اقتلاع|قلع|قطع|تقطيع|أحرق|احرق|إحراق|احراق|حرق|كسر|تكسير|حطم|تحطيم|جرف|تجريف|أتلف|اتلف|إتلاف|اتلاف|سمم|تسميم|خرب|تخريب|دمر|تدمير|أعدم|اعدام|احتراق|التهمت",q):
        dropped[i]="no damaging verb"; continue
    key=f"{r['doc_id']}:{i}"
    if key in drop_new: dropped[i]=drop_new[key]; continue
    if re.search(r"وثق|سجل|إحصائي|احصائي|تقرير|حصيلة|إجمالي|اجمالي|مجموع|منذ|خلال|نصف|شهر|عام|أسبوع",q):
        dropped[i]="tally or report, not one incident"; continue
    if not re.search(r"قرية|بلدة|مدينة|مخيم|خربة|منطقة|أراضي|ارض|الأغوار|الغور",q):
        dropped[i]="no place in the sentence"; continue
    dropped[i]="retrospective or no event date"
# reps get note about folded rows
also=D.get("also",{})
for e in reps:
    a=also.get(f"{e['doc']}:{e['idx']}")
    if a:
        ids=", ".join(f"{d}:{i}" for d,i,_ in a[:4])
        e["note"]=(e.get("note")+" " if e.get("note") else "")+f"also {ids} on the same event."
out={"reviewed_on":"2026-10-20","reader":"JOB-08 second pass round 2 (DeepSeek)",
     "trees_incidents":reps+kept_new,"trees_tallies":tallies,
     "dropped":{"trees_uprooted":dropped}}
yaml.safe_dump(out,open(f"{ROOT}/data/raw/jobs/08/trees_uprooted.review.yaml","w"),allow_unicode=True,sort_keys=False,width=200)
print("kept total",len(reps)+len(kept_new),"dropped",len(dropped))
