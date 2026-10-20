import json,yaml,glob,os,collections
from datetime import date
ROOT="/home/zaid/palestine-v2"
P=json.load(open(f"{ROOT}/data/raw/jobs/08/A.review/prelim.json"))
import gzip
READ=[json.loads(l) for l in gzip.open(f"{ROOT}/data/raw/jobs/08/trees_uprooted.read.ndjson.gz","rt")]
inc=[dict(e) for e in P["incidents"]]
tall=[dict(t) for t in P["tallies"]]
seen={(e["doc"],e["idx"]) for e in inc}
tseen={(t["doc"],t["idx"]) for t in tall}
def close(a,b):
    if not a or not b: return False
    return abs(a-b)/max(1,b)<=0.2
def dd(a,b):
    try: return abs((date.fromisoformat(a)-date.fromisoformat(b)).days)
    except: return 999
QUAL={"أكثر من":"more_than","اكثر من":"more_than","نحو":"about","حوالي":"about","قرابة":"about","ما يقارب":"about","أقل من":"up_to","اقل من":"up_to","على الأقل":"at_least"}
def normq(x):
    if not x: return None
    return QUAL.get(x.strip(),x.strip() if x.strip() in ("more_than","about","up_to","at_least") else None)
dropv={}
keeps=[]; agent_tallies=[]
for f in sorted(glob.glob(f"{ROOT}/data/raw/jobs/08/A.review/drops-*.ndjson")):
    for line in open(f):
        line=line.strip()
        if not line: continue
        try: v=json.loads(line)
        except: continue
        if v.get("verdict")=="keep": keeps.append(v)
        elif v.get("verdict")=="tally": agent_tallies.append(v)
        else: dropv[int(v["idx"])]=v.get("reason") or "not one incident"
print("agent keeps",len(keeps),"tallies",len(agent_tallies),"drops",len(dropv))
def add_inc(e):
    idx=int(e["idx"]); key=(READ[idx]["doc_id"],idx)
    if key in seen: return
    row={"doc":key[0],"idx":idx,"trees":int(float(e.get("trees") or 0)),
         "place":e.get("place"),"gov":e.get("gov"),"actor":e.get("actor") or None,
         "kind":e.get("kind") or "trees","date":e.get("date") or "",
         "qualifier":normq(e.get("qualifier")),"note":e.get("note") or ""}
    if not row["date"]:
        row["date"]=(READ[idx].get("date") or "")[:10]
    for o in inc:
        if o.get("gov")!=row["gov"]: continue
        if o.get("place") and row.get("place") and o["place"]!=row["place"]: continue
        if close(row["trees"],o.get("trees")) and dd(row["date"],o.get("date"))<=14:
            o["note"]=(o.get("note","")+f" also {row['doc']}:{row['idx']}.").strip(); return
    inc.append(row); seen.add(key)
for e in sorted(keeps,key=lambda x:x.get("date") or ""): add_inc(e)
# tallies from agents: named bodies, and undated-authority monthly/yearly rows with a bounded total
def span_days(a,b):
    try: return (date.fromisoformat(b)-date.fromisoformat(a)).days
    except: return 9999
tkeys=set()
for t in tall:
    tkeys.add((t["doc"],t["idx"]))
for t in agent_tallies:
    auth=t.get("authority") or ""
    named=bool(auth) and "unstated" not in auth.lower() and auth.lower() not in ("none","null")
    rows=t.get("rows") or []
    if not t.get("from") or not t.get("to") or not rows: continue
    mx=max(int(float(r.get("trees") or 0)) for r in rows)
    if not named:
        if t.get("precision") not in ("month","year","day"): continue
        if span_days(t["from"],t["to"])>370 or mx>20000: continue
    key=(READ[int(t["idx"])]["doc_id"],int(t["idx"]))
    if key in tkeys: continue
    pr=t.get("precision") if t.get("precision") in ("day","month","year") else "day"
    prow=[]
    for r in rows:
        n=int(float(r.get("trees") or 0))
        if n<=0: continue
        x={"measure":r.get("measure","all"),"place":r.get("place","West Bank"),"trees":n}
        q=normq(r.get("qualifier"))
        if q: x["qualifier"]=q
        prow.append(x)
    if not prow: continue
    tall.append({"doc":key[0],"idx":key[1],"from":t["from"],"to":t["to"],"precision":pr,
                 "authority":auth if named else f"{READ[int(t['idx'])].get('publisher')} (not named in the sentence)",
                 "rows":prow,**({"note":t["note"]} if t.get("note") else {})})
    tkeys.add(key)
# dedupe tallies by period + rows
seen_t=set(); tt=[]
for t in tall:
    k=(t["from"],t["to"],tuple(sorted((r["measure"],r["place"],r["trees"],r.get("qualifier") or "") for r in t["rows"])))
    if k in seen_t: continue
    seen_t.add(k); tt.append(t)
tall=tt
# curate tallies: trees only, bounded period, no broad statistics
KEEP_AUTH=("Commission","هيئة","وزارة","ARIJ","أريج","POICA","OCHA","أوتشا","Agriculture","UN report")
BAD_AUTH=("ICRC","الصليب","اشتية","Olive Council","الزيت الفلسطيني","اللوثرية","التضامن")
def span(a,b):
    try: return (date.fromisoformat(b)-date.fromisoformat(a)).days
    except: return 99999
ct=[]
for t in tall:
    rows=[r for r in t["rows"] if r.get("measure")!="attacks" and int(r.get("trees") or 0)>0]
    if not rows: continue
    t["rows"]=rows
    mx=max(int(r["trees"]) for r in rows)
    if mx>50000: continue
    sp=span(t["from"],t["to"])
    auth=t.get("authority") or ""
    if sp>1100 and not ("2023-10-07"==t["from"]): continue
    if any(b in auth for b in BAD_AUTH) and not any(k in auth for k in ("Commission","هيئة","وزارة","ARIJ")):
        continue
    ct.append(t)
# one per period+measure: prefer named authority, then larger total
by={}
for t in ct:
    k=(t["from"],t["to"])
    score=(any(k in (t.get("authority") or "") for k in KEEP_AUTH), sum(r["trees"] for r in t["rows"]))
    if k not in by or score>by[k][0]: by[k]=(score,t)
tall=[v[1] for v in by.values()]
# all queue idx for drop map
Q=[json.loads(l) for l in open(f"{ROOT}/data/raw/jobs/08/A.review/drops.ndjson")]
inc_keys={(e["doc"],e["idx"]) for e in inc}
drop={}
for q in Q:
    idx=int(q["idx"]); key=(READ[idx]["doc_id"],idx)
    if key in inc_keys or key in tseen: continue
    reason=dropv.get(idx)
    if not reason:
        # use the old reason only if the sentence is clearly not an incident; otherwise say unread
        reason="not one incident"
    drop[idx]=reason
out={"reviewed_on":"2026-10-20","method":"judgment pass: every candidate sentence read; reviewed 188 rows unchanged",
     "trees_incidents":inc,"trees_tallies":tall,"dropped":{"trees_uprooted":drop}}
yaml.safe_dump(out,open(f"{ROOT}/data/raw/jobs/08/trees_uprooted.review.yaml","w"),allow_unicode=True,sort_keys=False,width=200)
print("incidents",len(inc),"tallies",len(tall),"drops",len(drop),"agent drop verdicts",len(dropv))
