import sys,re,collections
sys.path.insert(0,"/home/zaid/jobs/job-08-lake-second-pass/ops/job08")
from lib import *
rows=load_read("trees_uprooted")
NUM=re.compile(r"(\d[\d,\.]*)\s*(ألف|آلاف|مليون|ملايين)?\s*(?:شجرة|أشجار|شتلة|غرسة|فسيلة)")
NUM2=re.compile(r"(?:شجرة|أشجار|شتلة|غرسة)[^\d]{0,18}(\d[\d,\.]*)")
CUT=re.compile(r"اقتلع|اقتلاع|تقتلع|يقتلع|قلع|قطع|تقطع|يقطع|تقطيع|حرق|أحرق|احرق|يحرق|سمم|تسميم|كسر|يكسر|تخريب|جرف|تجريف|جرفت|يجرف|دمر|تدمير|دمرت")
TALLY=re.compile(r"(?<![\u0621-\u064A])(?:وثق|وثّق|سجل|إحصائي|احصائي|تقرير|حصيلة|مجموع|إجمالي|اجمالي|منذ بداية|نصف العام|خلال الشهر|شهري|سنوي|أسبوعي|اسبوعي)(?![\u0621-\u064A])|بلغ مجموع")
ORDER=re.compile(r"أوامر|اوامر|أمر عسكري|امر عسكري|إخطار|اخطار|قرار|مخطط|ينوي|تخطط|سيقتلع|يهدد|أخطر")
def parse(printed):
    s=printed.replace(",","")
    try: v=float(s)
    except: return None
    return v
def count_of(q):
    m=NUM.search(q) or NUM2.search(q)
    if not m: return None
    g=m.group(1)
    v=parse(g)
    if v is None: return None
    if m.lastindex and m.lastindex>=2 and m.group(2):
        v*= {"ألف":1000,"آلاف":1000,"مليون":1_000_000,"ملايين":1_000_000}[m.group(2)]
    if "." in g and len(g.split(".")[-1])==3 and v<1000:
        # thousands in tallies; decimals in incidents are rare
        if TALLY.search(q) or v<100: v=round(v*1000)
    return v
labels=collections.Counter(); out=[]
for i,r in enumerate(rows):
    q=r.get("quote") or ""; c=count_of(q)
    lab=None; reason=None
    if not c: lab="mention"; reason="no tree count next to a tree noun"
    elif ORDER.search(q) and not re.search(r"اقتلع|قطع|أحرق|سمم|كسر|جرف",q): lab="order"; reason="order/notice, not an incident"
    elif TALLY.search(q): lab="tally"; reason="period tally or report"
    elif not CUT.search(q): lab="mention"; reason="no uprooting/cutting verb"
    elif not (place_of(q,c and 0)[0] or gov_in(q)): lab="mention"; reason="no place"
    else: lab="incident"
    labels[lab]+=1
    out.append((i,r,c,lab,place_of(q)[0],gov_in(q),actor(q),kind(q),q))
print(labels)
for lab in ("incident","tally","mention","order"):
    print("=====",lab)
    n=0
    for i,r,c,l,p,g,a,k,q in out:
        if l!=lab: continue
        print(i,r["doc_id"],r["date"][:10] if r.get("date") else "",c,"|",p,g,a,k,"|",q[:180]); n+=1
        if n>=6: break
with open("/home/zaid/palestine-v2/data/raw/jobs/08/trees.features.tsv","w") as f:
    f.write("idx\tdoc\tdate\tnumber\tlabel\tcount\tplace\tgov\tactor\tkind\tquote\n")
    for i,r,c,l,p,g,a,k,q in out:
        f.write("\t".join(map(str,[i,r["doc_id"],(r.get("date") or "")[:10],r.get("number"),l,c or "",p or "",g or "",a or "",k or "",q.replace("\t"," ")]))+"\n")
