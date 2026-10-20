import yaml,json,gzip,glob,os,collections
from datetime import date
ROOT="/home/zaid/palestine-v2"
rows=[json.loads(l) for l in gzip.open(f"{ROOT}/data/raw/jobs/08/trees_uprooted.read.ndjson.gz","rt")]
rv=yaml.safe_load(open(f"{ROOT}/data/raw/jobs/08/trees_uprooted.review.yaml"))
fx=yaml.safe_load(open(f"{ROOT}/db/reference/job08_review_fixes.yaml"))["trees_uprooted"]
only={tuple(map(int,k.split(":"))) for k in fx["only"]}
fix={tuple(map(int,k.split(":"))):v for k,v in fx["fix"].items()}
dropped0={i:r for i,r in rv["dropped"]["trees_uprooted"].items()}
cur={}
for e in rv["trees_incidents"]: cur[(e["doc"],e["idx"])]=e
# reviewed: only keys that are incidents + the 8 add rows
rev={}
for k in only:
    if k in cur: rev[k]=dict(cur[k])
for a in fx["add"]["trees_incidents"]:
    k=(a["doc"],a["idx"]); rev[k]=dict(a)
for k,e in rev.items():
    e.update(fix.get(k,{}))
    if not e.get("date"): e["date"]=(rows[e["idx"]].get("date") or "")[:10]
# new verdicts
new=[]; dropv={}
V=[l.rstrip("\n").split("\t") for l in open(f"{ROOT}/data/raw/jobs/08/A.review/new.verdicts.tsv") if not l.startswith("idx")]
for f in V:
    idx=int(f[0]); doc=int(f[1]) if False else None
    doc=rows[idx]["doc_id"]
    if f[1]=="keep":
        if (doc,idx) in rev: continue
        new.append({"doc":doc,"idx":idx,"trees":int(float(f[2])),"place":None if f[3]=="-" else f[3],
            "gov":f[4],"date":f[5],"actor":None if f[6]=="-" else f[6],"kind":f[7],
            "note":("" if f[8]=="-" else f[8])})
    else:
        dropv[idx]=f[8] if f[8]!="-" else "dropped in the reading pass"
# agent drops (only complete ranges)
def complete(path,n):
    try: return sum(1 for _ in open(path))==n
    except: return False
TALLIES=[
 dict(doc=219071,idx=416,authority="ARIJ, 2006",**{"from":"2006-01-01","to":"2006-12-31","precision":"year"},
      rows=[dict(measure="all",place="West Bank",trees=20300)]),
 dict(doc=2294140,idx=927,authority="Colonization and Wall Resistance Commission, half-year 2023",**{"from":"2023-01-01","to":"2023-06-30","precision":"day"},
      rows=[dict(measure="olive",place="West Bank",trees=8340)]),
 dict(doc=2318475,idx=957,authority="Colonization and Wall Resistance Commission, September 2024",**{"from":"2024-09-01","to":"2024-09-30","precision":"month"},
      rows=[dict(measure="all",place="West Bank",trees=699),dict(measure="olive",place="West Bank",trees=694)]),
 dict(doc=2325415,idx=1004,authority="Colonization and Wall Resistance Commission, annual report 2024",**{"from":"2024-01-01","to":"2024-12-31","precision":"year"},
      rows=[dict(measure="all",place="West Bank",trees=14212),dict(measure="olive",place="West Bank",trees=10459)]),
 dict(doc=2343845,idx=1087,authority="Colonization and Wall Resistance Commission, cumulative since 7 October 2023",**{"from":"2023-10-07","to":"2025-10-08","precision":"day"},
      rows=[dict(measure="all",place="West Bank",trees=48728),dict(measure="olive",place="West Bank",trees=37237)]),
 dict(doc=2326773,idx=1011,authority="Colonization and Wall Resistance Commission, January 2025",**{"from":"2025-01-01","to":"2025-01-31","precision":"month"},
      rows=[dict(measure="all",place="West Bank",trees=969),dict(measure="olive",place="West Bank",trees=960),
            dict(measure="all",place="Hebron",trees=350),dict(measure="all",place="Bethlehem",trees=328),
            dict(measure="all",place="Salfit",trees=160),dict(measure="all",place="Nablus",trees=100),
            dict(measure="all",place="Ramallah",trees=31)]),
 dict(doc=2346503,idx=1112,authority="Colonization and Wall Resistance Commission, October 2025",**{"from":"2025-10-01","to":"2025-10-31","precision":"month"},
      rows=[dict(measure="olive",place="West Bank",trees=1200)]),
 dict(doc=310475,idx=767,authority="Ministry of Agriculture, week to 26 December 2025",**{"from":"2025-12-19","to":"2025-12-26","precision":"day"},
      rows=[dict(measure="all",place="West Bank",trees=8000,qualifier="more_than")]),
 dict(doc=234894,idx=747,authority="ARIJ, since 1 January 2025",**{"from":"2025-01-01","to":"2025-11-01","precision":"day"},
      rows=[dict(measure="all",place="West Bank",trees=13000,qualifier="about")]),
]
# verify tally figure is inside its quote (digits, Arabic thousands)
def digits(s): return "".join(ch for ch in s if ch.isdigit())
for t in TALLIES:
    q=rows[t["idx"]]["quote"]
    for r in t["rows"]:
        n=r["trees"]; ok=str(n) in q or f"{n:,}" in q or (n%1000==0 and f"{n//1000} آلاف" in q) or (n==13000 and "13 ألف" in q) or (n==8000 and "8 آلاف" in q)
        if not ok: print("TALLY FIGURE NOT IN QUOTE",t["doc"],t["idx"],n)
print("reviewed",len(rev),"new keep",len(new),"tallies",len(TALLIES),"new drop",len(dropv))
json.dump({"rev":list(rev.values()),"new":new,"tallies":TALLIES,"dropv":dropv},open(f"{ROOT}/data/raw/jobs/08/A.review/merged.json","w"),ensure_ascii=False)
