import json,re,unicodedata,yaml
ROOT="/home/zaid/palestine-v2"
LOC=json.load(open(f"{ROOT}/data/raw/settlements/localities.json"))
def norm(s):
    s=unicodedata.normalize("NFKC",s or "")
    s=re.sub(r"[\u064B-\u0652\u0670\u0640]","",s)
    s=s.replace("أ","ا").replace("إ","ا").replace("آ","ا").replace("ى","ي").replace("ة","ه").replace("ؤ","و").replace("ئ","ي")
    s=re.sub(r"[^\w\s]"," ",s)
    return re.sub(r"\s+"," ",s).strip().lower()
# locality lookup: normalized name -> list of (ar,gov,id)
LOCS={}
for r in LOC:
    if not r.get("ar"): continue
    k=norm(r["ar"])
    if len(k)>=4:
        LOCS.setdefault(k,[]).append((r["ar"],r.get("gov_en"),r["place_id"]))
GOVS={"Jenin":["جنين"],"Tubas":["طوباس"],"Tulkarm":["طولكرم"],"Nablus":["نابلس"],"Qalqilya":["قلقيلية"],
"Ramallah":["رام الله","البيرة"],"Jericho":["أريحا","اريحا"],"Jerusalem":["القدس"],"Bethlehem":["بيت لحم"],"Hebron":["الخليل"]}
# normalized governorate aliases
GOVN={}
for g,names in GOVS.items():
    for n in names: GOVN[norm(n)]=g
BLACK={"الزيتون","الزيتونه","النخيل","البستان","الكروم","العنب","الشجره","الاشجار","البيادر"}
def places_in(q):
    """all locality matches, whole-word, via token n-gram lookup"""
    nq=norm(q); words=nq.split(); out=[]
    for n in (1,2,3,4):
        for i in range(len(words)-n+1):
            k=" ".join(words[i:i+n])
            v=LOCS.get(k)
            if v and k not in BLACK:
                pos=nq.find(k)
                out.append((pos,pos+len(k),k,v))
    # drop a match contained in a longer one
    out.sort(key=lambda x:(x[0],-(x[1]-x[0])))
    keep=[]
    for m in out:
        if any(m[0]>=x[0] and m[1]<=x[1] and (x[1]-x[0])>(m[1]-m[0]) for x in out): continue
        keep.append(m)
    return keep
CITYN={norm(n) for names in GOVS.values() for n in names}
REGION={norm("الضفة الغربية"),norm("الضفة"),norm("قطاع غزة"),norm("فلسطين")}
def place_of(q, near=None):
    ms=[m for m in places_in(q) if m[2] not in CITYN and norm(m[3][0][0]) not in REGION]
    if not ms: return None,None
    cand=ms
    if near is not None:
        before=[m for m in cand if m[1]<=near]
        if before:
            cand=before
            cand.sort(key=lambda m:abs(m[1]-near))
        else:
            cand.sort(key=lambda m:abs(m[0]-near))
    ar,gov,pid=cand[0][3][0]
    # a governorate named within 40 chars after the village fixes a duplicate name
    tail=q[cand[0][1]:cand[0][1]+45]
    g2=gov_in(tail)
    if g2: gov=g2
    return ar,gov
def gov_in(q):
    nq=norm(q)
    for k,g in GOVN.items():
        if re.search(r"(?<!\w)"+re.escape(k)+r"(?!\w)",nq): return g
    return None
def qualifier(q):
    if re.search(r"أكثر من|اكثر من",q): return "more_than"
    if re.search(r"ما لا يقل عن|على الأقل",q): return "at_least"
    if re.search(r"لا يتجاوز|اقل من|أقل من",q): return "up_to"
    if re.search(r"نحو|حوالي|قرابة|ما يقارب|تقريبا|تقريباً|زهاء",q): return "about"
    return None
def actor(q):
    nq=norm(q)
    si=nq.find("مستوطن"); ar=nq.find("جيش"); qu=nq.find("قوات"); ih=nq.find("احتلال")
    settlers=min([x for x in (si,nq.find("مستعمر"),nq.find("مغتصب")) if x>=0] or [9999])
    army=min([x for x in (ar,qu,ih) if x>=0] or [9999])
    if settlers<army: return "settlers"
    if army<9999: return "army"
    return None
def kind_near(q,pos):
    tail=q[pos:pos+35]
    if "عنب" in tail or "كرمة" in tail: return "grapevines"
    if "زيتون" in tail: return "olive"
    if re.search(r"لوز|تين|خوخ|رمان|حمضيات|مثمرة|فواكه",tail): return "fruit_trees"
    return kind(q)
def kind(q):
    if "زيتون" in q: return "olive"
    if re.search(r"عنب|كرمة|كروم",q): return "grapevines"
    if re.search(r"لوز|تين|خوخ|رمان|حمضيات|مثمرة|فواكه",q): return "fruit_trees"
    return "trees"
def date_day(q, pub):
    return (pub or "")[:10] or None
def load_read(fam):
    import gzip
    return [json.loads(l) for l in gzip.open(f"{ROOT}/data/raw/jobs/08/{fam}.read.ndjson.gz","rt",encoding="utf-8")]
