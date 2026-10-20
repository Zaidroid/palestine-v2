import sys,re,collections
sys.path.insert(0,"/home/zaid/jobs/job-08-lake-second-pass/ops/job08")
from lib import *
rows=load_read("trees_uprooted")
N=re.compile(r"(\d[\d,\.]*)\s*(ألف|آلاف|مليون|ملايين)?\s*(?:شجرة|أشجار|شتلة|غرسة|فسيلة)")
N2=re.compile(r"(?:شجرة|أشجار|شتلة|غرسة)[^\d]{0,15}(\d[\d,\.]*)")
CUT=re.compile(r"اقتلع|اقتلاع|تقتلع|يقتلع|قلع|قطع|تقطع|يقطع|تقطيع|حرق|أحرق|احرق|يحرق|سمم|تسميم|كسر|يكسر|تحطيم|حطم|تخريب|جرف|تجريف|جرفت|يجرف|دمر|تدمير|دمرت|قص|تنشير")
ORD=re.compile(r"أوامر|اوامر|أمر عسكري|امر عسكري|إخطار|اخطار|قرار|مخطط|سيتم|ستتم|تهدد|ينوي|يعتزم")
PER=re.compile(r"خلال الشهر|نصف العام|منذ بداية|(?<![\u0621-\u064A])(?:شهري|سنوي|أسبوعي|اسبوعي|حصيلة|إجمالي|اجمالي|مجموع)(?![\u0621-\u064A])|بلغ مجموع")
def parse(g):
    s=g.replace(",","")
    try: v=float(s)
    except: return None
    if "." in g and len(g.split(".")[-1])==3 and v<1000:
        # trees: 3-digit tail after dot is thousands in tallies; decimals are <100 in land, not trees
        return round(v*1000)
    return v
def count(q):
    m=N.search(q) or N2.search(q)
    if not m: return None,None
    g=m.group(1); v=parse(g)
    if v is None: return None,None
    if m.re is N and m.lastindex and m.lastindex>=2 and m.group(2):
        v*= {"ألف":1000,"آلاف":1000,"مليون":1_000_000,"ملايين":1_000_000}[m.group(2)]
    return v,m.start()
def near(q,pos,pat,window=70):
    if pos is None: return None
    m=pat.search(q[max(0,pos-window):pos+window])
    return m
labels=collections.Counter(); out=[]
for i,r in enumerate(rows):
    q=r.get("quote") or ""; c,pos=count(q)
    if not c or not (place_of(q,pos)[0] or gov_in(q)):
        lab="mention"; why="no count or no place"
    elif re.search(r"(?:أوامر|اوامر|أمر عسكري|امر عسكري|إخطار|اخطار|قرار)[^.]{0,40}(?:لاقتلاع|باقتلاع|لقطع|بقطع|لإزالة|بإزالة)",q):
        lab="order"; why="order/notice to uproot near the count"
    elif near(q,pos,re.compile(r"سيتم|ستتم|تهدد|ينوي|يعتزم|مخطط"),60):
        lab="order"; why="future/intention near the count"
    elif near(q,pos,PER,50):
        lab="tally"; why="aggregated period near the count"
    elif near(q,pos,CUT,70):
        lab="incident"; why=None
    else:
        lab="mention"; why="no cutting verb near the count"
    labels[lab]+=1
    p,g=place_of(q,pos)
    out.append((i,r,c,lab,p,g,actor(q),kind(q),q))
print(labels)
for lab in ("incident","tally","mention","order"):
    print("=====",lab)
    n=0
    for i,r,c,l,p,g,a,k,q in out:
        if l!=lab: continue
        print(i,r["doc_id"],r["date"][:10] if r.get("date") else "",c,"|",p,g,a,k,"|",q[:160]); n+=1
        if n>=5: break
