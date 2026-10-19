"""Arrests as the prisoners' organisations count them, read from the archive:
the monthly tallies (2014 →) and the overnight statements (October 2023 →).

    .venv/bin/python -m ops.extract_arrests              # the archive → data/raw/arrests/
    .venv/bin/python -m ops.extract_arrests --from DIR   # the texts already dumped (tests, reruns)

WHY (2026-10-19). Zaid: "how many kids got detained in the West Bank" was his
own example of a question the databank should answer. The databank holds the
joint institutions' PDFs to January 2024 (arrests_joint_monthly) and Addameer's
monthly stock; the archive holds 29,441 texts in which the Palestinian
Prisoners' Club, the Palestine Centre for Prisoner Studies, the joint
institutions, the Commission of Detainees and the Jerusalem governorate state
their counts month by month — total, children, women, sometimes by governorate
— and, since October 2023, the Club's overnight statements ("arrested (12)
citizens since last evening"). This reads them.

WHAT A RECORD IS. Monthly: the headline first, else a lead sentence, that
names the month and a total ("450 حالة اعتقال خلال نوفمبر"); a range of months,
a cumulative since 7 October, a half-year or a year is not a month. A total
scoped to one governorate ("بالخليل", "محافظة القدس") is that governorate's row;
otherwise the row is the West Bank's. Two authorities may count the same month
differently: each keeps its own row, the authority in attrs. Daily: the Club's
statement with an overnight cue and a count; one value a day (the one most
statements agree on); a day without a statement is absent, never zero.

MEASURED (19 Oct, read by hand): see data/raw/arrests/README.md after a run.
"""
from __future__ import annotations

import json
import re
import sys
import collections
import datetime
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "arrests"
QUESTIONS = {
    "monthly": '("حالة اعتقال" OR "حالات اعتقال" OR "حالات الاعتقال") (خلال شهر OR الشهر الماضي) (الأسير OR الضمير OR الأسرى)',
    "daily": '"نادي الأسير" (اعتقلت OR اعتقال OR اعتقل) (الليل OR فجر OR أمس OR اليوم)',
}
SINCE = {"monthly": "2014-01-01", "daily": "2023-10-07"}


def dump_texts(d: Path) -> None:
    from ingest import archive_text as T
    from resolve.db import connect
    d.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        cur = c.cursor(); cur.execute("SET default_transaction_read_only = on"); cur.execute("SET statement_timeout = '240s'")
        for name, q in QUESTIONS.items():
            cur.execute("""SELECT d.doc_id, d.published_at, d.source, d.url, d.title, d.body FROM document d
                           WHERE d.terms @@ to_tsquery('english', %s) AND d.published_at >= %s::timestamptz AND d.body IS NOT NULL AND d.body <> ''
                           ORDER BY d.published_at""", (T.question(q), SINCE[name]))
            rows = [{"doc_id": r[0], "date": r[1].isoformat(), "publisher": r[2], "url": r[3], "title": r[4], "text": r[5]} for r in cur]
            json.dump({"question": q, "texts": rows}, open(d / f"{name}.json", "w"), ensure_ascii=False)
            print(f"  {name}: {len(rows)} texts")


def run(S: str) -> None:
    AR=str.maketrans('٠١٢٣٤٥٦٧٨٩','0123456789')
    MONTHS={'كانون الثاني':1,'كانون ثاني':1,'يناير':1,'شباط':2,'فبراير':2,'آذار':3,'اذار':3,'مارس':3,'نيسان':4,'أبريل':4,'ابريل':4,'إبريل':4,'أيار':5,'ايار':5,'مايو':5,'حزيران':6,'يونيو':6,'تموز':7,'يوليو':7,'آب':8,'أغسطس':8,'اغسطس':8,'أيلول':9,'ايلول':9,'سبتمبر':9,'تشرين الأول':10,'تشرين أول':10,'تشرين اول':10,'أكتوبر':10,'اكتوبر':10,'تشرين الثاني':11,'تشرين ثاني':11,'تشرين الآخر':11,'نوفمبر':11,'كانون الأول':12,'كانون أول':12,'كانون اول':12,'ديسمبر':12}
    MRE='|'.join(sorted(map(re.escape,MONTHS),key=len,reverse=True))
    NUM=r'\(?\s*(\d[\d,]*)\s*\)?'
    def norm(t): return re.sub(r'\s+',' ',re.sub(r'[ً-ْـ]','',t.translate(AR)))
    def num(s): return int(s.replace(',',''))
    AUTH=[('pcps', re.compile(r'مركز (?:فلسطين|أسرى فلسطين) لدراسات الأسرى|مركز أسرى فلسطين')), ('joint', re.compile(r'التقرير (?:الشهري )?المشترك|مؤسسات الأسرى|تقرير(?:ها)? المشترك|معطيات حقوقية|جمعيات حقوقية')),
          ('pps', re.compile(r'نادي الأسير')), ('commission', re.compile(r'هيئة شؤون الأسرى|هيئة الأسرى')), ('addameer', re.compile(r'الضمير')), ('governorate_office', re.compile(r'محافظة القدس:|وحدة العلاقات العامة'))]
    GOVS={'القدس':'Jerusalem','الخليل':'Hebron','رام الله':'Ramallah','نابلس':'Nablus','بيت لحم':'Bethlehem','جنين':'Jenin','طولكرم':'Tulkarm','قلقيلية':'Qalqilya','طوباس':'Tubas','سلفيت':'Salfit','أريحا':'Jericho','اريحا':'Jericho','غزة':'Gaza Strip','قطاع غزة':'Gaza Strip'}
    GRE='|'.join(sorted(map(re.escape,GOVS),key=len,reverse=True))
    texts=json.load(open(f'{S}/monthly.json'))['texts']; out=[]
    for x in texts:
        t=norm(x['text']); pub=datetime.date.fromisoformat(x['date'][:10])
        m=re.search(r'(?:خلال|في) (?:شهر )?(?:ال)?('+MRE+r')(?:\s*/\s*(?:'+MRE+r'))?\s*(?:من العام |من عام |عام )?(\d{4})?', t)
        if m: mo=MONTHS[m.group(1)]; yr=int(m.group(2)) if m.group(2) else (pub.year if mo<=pub.month else pub.year-1); period=f'{yr:04d}-{mo:02d}'; basis='named'
        elif re.search(r'الشهر الماضي|الشهر المنصرم', t): p=pub.replace(day=1)-datetime.timedelta(days=1); period=f'{p.year:04d}-{p.month:02d}'; basis='relative'
        else: continue
        if re.search(r'التقرير السنوي|خلال العام|خلال عام \d{4}|النصف الأول|النصف الثاني|منذ بداية العام|منذ مطلع', t[:400]): continue
        TOTAL=re.compile(NUM+r'\s*(?:حالة اعتقال|حالات اعتقال|حالة إعتقال|حالة اعتقـال|مواطن(?:ا|اً|ًا)?(?:\s*فلسطيني(?:ا|اً|ًا)?)?|فلسطيني(?:ا|اً|ًا)?(?![ةه])|معتقل(?:ا|اً|ًا)?)')
        BAD=re.compile(r'منذ .{0,40}(?:وحتى|حتى|إلى)|وحتى|النصف|الربع|منذ بداية|منذ مطلع|منذ 7|منذ السابع|منذ بدء|ثلاثة أشهر|أشهر|فلسطينية|مقدسي|من قطاع غزة|من غزة|من الضفة والقدس')
        SCOPE=re.compile(r'(?:في|ب|من|محافظة)\s*(?:محافظة |مدينة )?('+GRE+r')')
        title=norm(x['title'] or '')
        cands=[('title', title)] + [('lead', ss) for ss in re.split(r'(?<=[.؟!])\s+', t[:700])]
        tot=None; where=None
        for w, ss in cands:
            if not re.search(MRE+r'|الشهر الماضي|الشهر المنصرم', ss): continue
            mm=TOTAL.search(ss)
            if mm and not BAD.search(ss):
                tot=mm; where=w; src=ss; break
        if not tot: continue
        total=num(tot.group(1))
        if not (20 <= total <= 5000): continue
        # a governorate scopes the figure only when it sits beside the total ("101 حالة اعتقال في القدس",
        # "80 معتقلا من محافظة الخليل") or opens the headline ("محافظة القدس:"); "نصفها من القدس" does not
        near = src[tot.start():tot.end() + 40]
        sc = SCOPE.search(near) or re.match(r'\s*(?:محافظة )?(' + GRE + r')\s*:', src)
        if sc and sc.re is SCOPE and re.search(r'نصف|ثلث|ربع|بين|منه|منها|معظم|غالبي|أغلب', near[:sc.start()]):
            sc = None                                     # "half of them from Jerusalem" scopes nothing
        scope = GOVS[sc.group(1)] if sc else 'West Bank'
        if scope == 'Gaza Strip': continue
        t = src + ' ' + t
        win = src + ' ' + t[len(src):len(src) + 300]       # the statement's own sentence and what follows it
        ch=re.search(NUM+r'\s*(?:طفل|أطفال|قاصر|قُصّر|قصر)', win); wo=re.search(NUM+r'\s*(?:امرأة|سيدة|نساء|فتاة|سيدات|إمرأة)', win)
        if ch and num(ch.group(1)) > total: ch = None          # a figure larger than the total is some other count
        if wo and num(wo.group(1)) > total: wo = None
        auth=next((k for k,r in AUTH if r.search(t)), None)
        govs={}
        for g in re.finditer(NUM+r'\s*(?:حالة اعتقال |حالة |مواطن(?:ا|اً|ًا)? |معتقلا |معتقلاً )?(?:من |في )(?:مدينة |محافظة |قطاع )?('+GRE+r')', t):
            govs.setdefault(GOVS[g.group(2)], num(g.group(1)))
        out.append({'doc_id':x['doc_id'],'date':x['date'][:10],'publisher':x['publisher'][:30],'url':x['url'],'period':period,'basis':basis,'authority':auth,'total':total,
                    'children':num(ch.group(1)) if ch else None,'women':num(wo.group(1)) if wo else None,'by_governorate':govs or None,'where':where,'scope':scope,'quote':src[:220]})
    # one figure per (period, authority): the same report in several outlets
    g=collections.defaultdict(list)
    for r in out: g[(r['period'],r['scope'],r['total'])].append(r)          # the same report in several outlets, whoever named the authority
    figs=[]
    for (p,sc,tv),rs in sorted(g.items()):
        best=next((r for r in rs if r['authority']), rs[0])
        merged={**best,'children':next((r['children'] for r in rs if r['children'] is not None),None),'women':next((r['women'] for r in rs if r['women'] is not None),None),
                'by_governorate':next((r['by_governorate'] for r in rs if r['by_governorate']),None),'outlets':len({r['publisher'] for r in rs}),'doc_ids':[r['doc_id'] for r in rs]}
        figs.append(merged)
    # ── the daily overnight statements since Oct 2023 ──
    daily=json.load(open(f'{S}/daily.json'))['texts']; days=collections.defaultdict(list)
    DAILY=re.compile(NUM+r'\s*(?:مواطن(?:ا|اً|ًا)?|فلسطيني(?:ا|اً|ًا)?(?![ةه])|معتقل(?:ا|اً|ًا)?|شخص(?:ا|اً|ًا)?)')
    DAYCUE=re.compile(r'خلال الليل|الليلة الماضية|فجر اليوم|منذ مساء أمس|منذ مساء امس|منذ الليلة|الليلة|فجر')
    for x in daily:
        title=norm(x['title'] or ''); lead=norm(x['text'])[:400]
        for ss in [title]+re.split(r'(?<=[.؟!])\s+', lead):
            if 'نادي الأسير' not in ss and 'نادي الاسير' not in ss: continue
            if not DAYCUE.search(ss) or re.search(r'منذ 7|منذ السابع|منذ بدء|منذ بداية|حصيلة|ارتفع|إجمالي|الاجمالي', ss): continue
            mm=DAILY.search(ss)
            if mm:
                n=num(mm.group(1))
                if 1 <= n <= 400: days[x['date'][:10]].append({'n':n,'doc_id':x['doc_id'],'publisher':x['publisher'][:30],'quote':ss[:200]}); break
    dseries=[]
    for d,rs in sorted(days.items()):
        vals=collections.Counter(r['n'] for r in rs); n,c=vals.most_common(1)[0]
        dseries.append({'date':d,'arrests_overnight':n,'statements':len(rs),'agree':c,'doc_ids':[r['doc_id'] for r in rs if r['n']==n][:5],'quote':next(r['quote'] for r in rs if r['n']==n)})
    with open(f'{S}/daily.ndjson','w') as f:
        for r in dseries: f.write(json.dumps(r, ensure_ascii=False)+'\n')
    print('daily: days with a statement', len(dseries), 'span', dseries[0]['date'] if dseries else None, '→', dseries[-1]['date'] if dseries else None, 'months', len({d['date'][:7] for d in dseries}))
    mo=collections.defaultdict(int)
    for d in dseries: mo[d['date'][:7]]+=d['arrests_overnight']
    print('daily sums by month (sample):', {k:v for k,v in list(sorted(mo.items()))[:6]}, '…', {k:v for k,v in list(sorted(mo.items()))[-4:]})
    random.seed(2); print('--- 6 daily rows ---')
    for d in random.sample(dseries, 6): print(f"{d['date']} n={d['arrests_overnight']} stmts={d['statements']} agree={d['agree']} | {d['quote'][:120]}")
    with open(f'{S}/monthly.ndjson','w') as f:
        for r in figs: f.write(json.dumps(r, ensure_ascii=False)+'\n')
    print('rows',len(out),'→ figures',len(figs))
    print('by year:', dict(sorted(collections.Counter(f['period'][:4] for f in figs).items())))
    print('authority:', collections.Counter(f['authority'] for f in figs))
    per=collections.defaultdict(set)
    for f in figs: per[f['authority']].add(f['period'])
    print('months covered per authority:', {k:len(v) for k,v in per.items()})
    random.seed(9)
    for f in random.sample(figs, 16): print(f"{f['period']} {str(f['authority']):10} tot {f['total']:>5} ch {str(f['children']):>4} wo {str(f['women']):>4} govs {len(f['by_governorate'] or {})} x{f['outlets']} | {f['quote'][:120]}")


def main(argv: list[str]) -> int:
    d = Path(argv[argv.index("--from") + 1]) if "--from" in argv else OUT
    if "--from" not in argv:
        print("archive → texts"); dump_texts(d)
    run(str(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
