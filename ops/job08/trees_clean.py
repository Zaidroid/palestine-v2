import sys,re,json,yaml
sys.path.insert(0,"/home/zaid/jobs/job-08-lake-second-pass/ops/job08")
from lib import *
ROOT="/home/zaid/palestine-v2"
rows=load_read("trees_uprooted")
p=f"{ROOT}/data/raw/jobs/08/trees_uprooted.review.yaml"; rv=yaml.safe_load(open(p))
FORCE={
"218367:369":"governorate total, not one incident",
"2328061:1018":"monthly tally split by governorate",
"226419:555":"the sentence is about 5,000 in Ramallah; 1,500 is not this incident",
"3124508:1660":"activist video caption, not a dated event",
"2326773:1011":"monthly tally split by governorate",
"231288:678":"olive theft, not 35 trees uprooted",
"4379154:2808":"two villages in one sentence (Deir Jarir and Salwad)",
"2729578:1419":"last Saturday, no event date; retrospective",
"4770006:3001":"775 all trees with 380 olive, an aggregate",
"4388110:2828":"15 grape vines and 20 olives; the count is not trees uprooted",
"218374:372":"1,420 trees in Hebron, not Nablus",
"4775832:3019":"weekly/commission report with several numbers, not one incident",
"4199591:2617":"400 grape vines and 70 olives; the count is not trees uprooted"}
AREA={"الراس","الرأس","البقعة","الشجارة","الحمرة","العديسة","القرينات","الصفا","الواد","السهل","القطاع"}
keep=[]; extra={}
for e in rv["trees_incidents"]:
    q=rows[e["idx"]].get("quote") or ""
    if f"{e['doc']}:{e['idx']}" in FORCE:
        extra[e["idx"]]=FORCE[f"{e['doc']}:{e['idx']}"]; continue
    if re.search(r"يتحدث عن|يتحدث|يقول|فيديو",q) and not re.search(r"في \d{1,2}/",q):
        extra[e["idx"]]="caption or testimony, not a dated event"; continue
    if re.search(r"تقريره الشهري|الشهر الماضي|خلال الشهر|حصيلة الشهر",q):
        extra[e["idx"]]="monthly report, a tally not one incident"; continue
    if re.search(r"بلدتي|قريتي|بلدتين|قريتين|بين بلد|بين قر|وقرية|وبلدة|ومخيم",q):
        extra[e["idx"]]="two places in one sentence; one row per event needs one place"; continue
    if e["trees"]>=50 and re.search(r"اعتداءات|اعتداءين|اعتداءان|هجمات|عمليات|على التوالي|توزعت|منذ بداية|خلال الشهر|خلال العام",q):
        extra[e["idx"]]="aggregate of several attacks or a period, not one incident"; continue
    if re.search(r"ونابلس|وبيت لحم|والخليل|وسلفيت|ورام الله|وقلقيلية|وجنين|وطوباس|وأريحا|والقدس",q):
        extra[e["idx"]]="several governorates in one sentence; a tally, not one incident"; continue
    if e.get("place") in AREA:
        e["place"]=None; e["note"]=(e.get("note")+" " if e.get("note") else "")+"area name removed from place; governorate only"
    keep.append(e)
rv["trees_incidents"]=keep
for k,v in extra.items(): rv["dropped"]["trees_uprooted"][k]=v
yaml.safe_dump(rv,open(p,"w"),allow_unicode=True,sort_keys=False,width=200)
print("kept",len(keep),"extra drops",len(extra))
