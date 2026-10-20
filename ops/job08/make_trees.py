import sys,csv,json,gzip,yaml,collections
sys.path.insert(0,"/home/zaid/jobs/job-08-lake-second-pass/ops/job08")
from lib import load_read
rows=load_read("trees_uprooted")
ev=list(csv.DictReader(open("/home/zaid/palestine-v2/data/raw/jobs/08/trees.events.tsv"),delimiter="\t"))
kept={int(e["idx"]) for e in ev}
inc=[]
for e in ev:
    r=rows[int(e["idx"])]
    q=e["quote"]
    note=[]
    n=int(e["others"] or 0)
    if n: note.append(f"{n} other outlet(s) on the same incident (clustered by place, count and date)")
    if e["place"] and e["place"] not in q: note.append("place from the gazetteer, not the sentence spelling")
    row={"doc":int(e["doc"]),"idx":int(e["idx"]),"trees":int(e["trees"])}
    if e["qual"]: row["qualifier"]=e["qual"]
    row["place"]=e["place"] or None
    row["gov"]=e["gov"] or None
    if e["actor"]: row["actor"]=e["actor"]
    if e["kind"]: row["kind"]=e["kind"]
    if note: row["note"]="; ".join(note)
    inc.append(row)
# every read record not an incident gets one reason
dropped={}
for i,r in enumerate(rows):
    if i not in kept:
        dropped[i]="not an incident: no tree count, cutting verb and named place in one clause"
out={"reviewed_on":"2026-10-20","reader":"JOB-08 second pass (DeepSeek)",
     "trees_incidents":inc,"trees_tallies":[],"dropped":{"trees_uprooted":dropped}}
p="/home/zaid/palestine-v2/data/raw/jobs/08/trees_uprooted.review.yaml"
yaml.safe_dump(out,open(p,"w"),allow_unicode=True,sort_keys=False,width=200)
print("incidents",len(inc),"dropped",len(dropped),"others",sum(int(e["others"] or 0) for e in ev))
print("yaml bytes",__import__("os").path.getsize(p))
