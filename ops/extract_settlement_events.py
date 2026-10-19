"""Settlement housing-unit announcements and new outposts, read from the archive.

    .venv/bin/python -m ops.extract_settlement_events              # the archive → data/raw/settlements/
    .venv/bin/python -m ops.extract_settlement_events --from DIR   # the texts already dumped (tests, reruns)

WHY (2026-10-19). Zaid asked for settlement units and outposts by month from
the archive. The databank's settlement area stops in May 2024 (Peace Now's
population sheet); the archive holds 6,410 texts naming housing units and
11,382 naming outposts, 1999 → today. This is the first pass: deterministic
patterns, every record with its quote and document, nothing written to the
databank. A judgment pass (docs/jobs/JOB-04) reviews each event before any
row is loaded, and the outside tallies (Peace Now, the UN's 2334 reports, the
EU's yearly reports, Israel's CBS) are the cross-check.

WHAT A RECORD IS. Units: one announcement — an approval, tender, plan,
permit or construction start — with the number of units, from the headline
first, or from a body sentence that carries a same-day marker; a sentence that
states a period (a year, "since the start of the year", a named month) or a
figure above 10,000 (a master plan, a cumulative total) is an AGGREGATE, kept
apart. The same figure within 45 days is one announcement (outlets repeat it
for weeks). Outposts: settlers establishing a new outpost, with a day marker
or an explicit date, placed on the gazetteer when the village is named; the
same place within 45 days is one event; a warning, an attempt, an intent, a
count of outposts or a past establishment is not an event.

MEASURED (19 Oct, 16-row samples read by hand): units ~14/16 right, outposts
~11/16 right; the archive's outposts run at about half of Peace Now's list
(2024: 23 against 59), so the list is the series and this is its detail.
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
OUT = ROOT / "data" / "raw" / "settlements"
QUESTIONS = {"units": '"وحدة استيطانية" OR "وحدات استيطانية"', "outposts": '"بؤرة استيطانية" OR "بؤر استيطانية"'}


def dump_texts(d: Path) -> None:
    """The matching texts, one JSON line each, through the archive's own index."""
    from ingest import archive_text as T
    from resolve.db import connect
    d.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        cur = c.cursor(); cur.execute("SET default_transaction_read_only = on"); cur.execute("SET statement_timeout = '240s'")
        for name, q in QUESTIONS.items():
            cur.execute("""SELECT d.doc_id, d.published_at, d.source, d.kind, d.url, d.title, d.body FROM document d
                           WHERE d.terms @@ to_tsquery('english', %s) AND d.body IS NOT NULL AND d.body <> '' ORDER BY d.published_at""", (T.question(q),))
            n = 0
            with open(d / f"texts-{name}.ndjson", "w") as f:
                for r in cur:
                    f.write(json.dumps({"doc_id": r[0], "date": r[1].isoformat() if r[1] else None, "source": r[2], "kind": r[3], "url": r[4], "title": r[5], "body": r[6]}, ensure_ascii=False) + "\n"); n += 1
            print(f"  {name}: {n} texts")


def dump_reference(d: Path) -> None:
    """The gazetteer's localities with their governorate, and the reviewed settlement names."""
    import yaml
    from resolve.db import connect
    with connect() as c:
        cur = c.cursor(); cur.execute("SET default_transaction_read_only = on")
        cur.execute("""SELECT l.place_id, l.name_en, l.name_ar, g.name_ar, g.name_en, l.oslo_area FROM place l
                       LEFT JOIN place g ON g.kind='governorate' AND g.admin2_pcode = l.admin2_pcode
                       WHERE l.kind='locality' AND l.merged_into IS NULL""")
        rows = [r for r in cur.fetchall() if r[2] and any('\u0600' <= ch <= '\u06FF' for ch in r[2])]
    json.dump([{"place_id": r[0], "en": r[1], "ar": r[2], "gov_ar": r[3], "gov_en": r[4], "oslo": r[5]} for r in rows], open(d / "localities.json", "w"), ensure_ascii=False)
    names = yaml.safe_load(open(ROOT / "db" / "reference" / "peacenow_settlement_names.yaml"))
    names = names.get("settlements") or names.get("entries") or names
    json.dump(list(names.values()) if isinstance(names, dict) else names, open(d / "settlement_names.json", "w"), ensure_ascii=False)


def run(S: str) -> None:
    AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
    def norm(t):
        t = t.translate(AR_DIGITS)
        t = re.sub(r'[ً-ْـ]', '', t)            # harakat, tatweel
        return re.sub(r'\s+', ' ', t)
    def key(t):
        t = norm(t); t = re.sub(r'[أإآٱ]', 'ا', t); t = t.replace('ة', 'ه').replace('ى', 'ي').replace('ئ', 'ي').replace('ؤ', 'و')
        t = re.sub(r'[“”"\'«»()\[\]،,:.]', ' ', t); t = re.sub(r'\bال', '', t)
        return re.sub(r'\s+', ' ', t).strip()
    def sents(body):
        return [s.strip() for s in re.split(r'(?<=[.؟!])\s+|\n+|(?<=\s)-\s', body) if 12 < len(s.strip()) < 600]
    def parse_num(m):
        """'12 ألفا و934' / '3 آلاف' / '2,386' / '1936' → int"""
        s = m.replace('٬', ',').replace(',', '').replace('.', '')
        mm = re.match(r'(\d+)\s*(?:ألف[اً]?|آلاف)\s*(?:و\s*(\d+))?$', s)
        if mm: return int(mm.group(1)) * 1000 + int(mm.group(2) or 0)
        return int(s) if s.isdigit() else None
    RANK = {'tender': 0, 'approval': 1, 'plan': 2, 'permit': 3, 'promote': 4, 'build': 5}
    # ── units ──
    NUMW = r'(\d[\d,٬\.]*(?:\s*(?:ألف[اً]?|آلاف)(?:\s*و\s*\d+)?)?)'
    UNIT_RE = re.compile(NUMW + r'\s*(?:وحدة|وحدات)\s+(?:سكنية\s+)?(?:استيطانية|إستيطانية|استعمارية)')
    UNIT_RE2 = re.compile(NUMW + r'\s*(?:وحدة|وحدات)\s+سكنية')             # only in a settlement sentence
    SETTLE_CTX = re.compile(r'مستوطن|استيطان|إستيطان|استعمار|مستعمر')
    STAGES = [('tender', re.compile(r'عطاء|مناقص')), ('approval', re.compile(r'\bصادق|\bتصادق|\bصدّق|\bصدق|\bصودق|مصادقة|\bأقر|\bتقر|إقرار|\bوافق|\bتوافق|موافقة|\bاعتمد|\bتعتمد')),
              ('plan', re.compile(r'مخطط|خطة|خطط|إيداع|ايداع')), ('permit', re.compile(r'ترخيص|تراخيص|رخص')),
              ('promote', re.compile(r'دفع|تقدم|تقدّم|ستقدم')), ('build', re.compile(r'بناء|إقامة|اقامة|إنشاء|انشاء|توسيع'))]
    AGG = re.compile(r'خلال (?:كانون|شباط|آذار|نيسان|أيار|حزيران|تموز|آب|أيلول|تشرين|يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)|العام الماضي|العام المنصرم|عام \d{4}|سنة \d{4}|خلال \d{4}|منذ بداية|منذ مطلع|خلال الأشهر|خلال الشهور|خلال النصف|خلال الربع|في الفترة|خلال العام|خلال السنة|الأعوام|السنوات|على مدار|منذ عام|منذ العام|حتى الآن|الشهر الماضي|خلال شهر|منذ تولي|منذ بدء|منذ توقيع|منذ اتفاق|آخر عام|العقد|منذ \d{4}')
    HYPO = re.compile(r'\bتحذير|\bحذر|في حال|إذا ما|لو |تعتزم|تنوي|ينوي|يعتزم|تخطط|تسعى|مقترح|قد يصل|سيتم|ستقوم|ستبني|ستبحث|سيبحث|المقبل|القادم|قريبا|قريباً|مرتقب|مزمع|من المتوقع|يطالب|طالب|تطالب|دعا|تهدد|توقع|يتوقع|محتمل')
    PASTU = re.compile(r'تم إقرارها|تم اقرارها|أقرت سابق|سابقا|سابقاً|في وقت سابق|قبل أعوام|قبل سنوات|قبل أشهر|قبل عام|قبل شهر|كانت قد|كان قد|لم تتم|لم يتم|آنذاك')
    DAY = re.compile(r'اليوم|أمس|امس|صباح|مساء|فجر|ظهر|الليلة|قبل أيام|قبل يومين|الأسبوع الماضي|الاسبوع الماضي|(?:السبت|الأحد|الاحد|الاثنين|الإثنين|الثلاثاء|الأربعاء|الاربعاء|الخميس|الجمعة)')
    SUBJ = re.compile(r'مستوطن|مستعمر|الاحتلال|جماعات|عصابات')
    CITY_RE = re.compile(r'(?:مستوطنة|مستوطنه|مستعمرة|مستعمره|مغتصبة)\s*[«"“]?\s*([^\s«"”»،,.()]+(?:\s+[^\s«"”»،,.()]+)?)')
    REGION = [('East Jerusalem', re.compile(r'القدس')), ('West Bank', re.compile(r'الضفة'))]
    names = json.load(open(S + '/settlement_names.json'))
    SETTLE_KEYS = {}
    for n in names:
        for v in (n.get('ar'), n.get('printed')):
            if v: SETTLE_KEYS[key(v)] = n['name']
    def settlement_of(sent):
        m = CITY_RE.search(sent)
        if not m: return None, None
        raw = m.group(1).strip(); k = key(raw)
        for cand in (k, ' '.join(k.split()[:1])):
            if cand in SETTLE_KEYS: return raw, SETTLE_KEYS[cand]
        for kk, en in SETTLE_KEYS.items():
            if kk and (k.startswith(kk) or kk.startswith(k.split()[0] if k else '#')): return raw, en
        return raw, None
    units_events, units_aggs = [], []
    for line in open(S + '/texts-units.ndjson'):
        x = json.loads(line); d = (x['date'] or '')[:10]
        if not d: continue
        cands = [('title', x['title'] or '')] + [('body', s) for s in sents(x['body'])]
        got_title = False
        for where, s in cands:
            n = norm(s)
            hits = UNIT_RE.findall(n) or (UNIT_RE2.findall(n) if SETTLE_CTX.search(n) else [])
            if not hits: continue
            vals = [parse_num(h) for h in hits]; vals = [v for v in vals if v and 2 <= v <= 60000]
            if not vals: continue
            stage = next((k for k, r in STAGES if r.search(n)), None)
            if stage is None or HYPO.search(n): continue
            is_agg = bool(AGG.search(n)) or max(vals) > 10000      # a master plan or a cumulative figure, never one announcement
            if not is_agg:
                if PASTU.search(n): continue
                if where == 'body' and (got_title or not DAY.search(n)): continue
                if where == 'title': got_title = True
            raw, en = settlement_of(n); region = next((r for r, rx in REGION if rx.search(n)), None)
            rec = {'doc_id': x['doc_id'], 'date': d, 'source': x['source'], 'url': x['url'], 'stage': stage,
                   'units': max(vals), 'settlement_ar': raw, 'settlement_en': en, 'region': region or ('East Jerusalem' if (en is None and 'القدس' in n) else None), 'quote': s[:300]}
            rec['where'] = where
            (units_aggs if is_agg else units_events).append(rec)
    # dedupe events: same units + stage within 5 days (any outlet) → one event
    def dedupe(evs, keyf, days):
        evs = sorted(evs, key=lambda r: r['date']); out = []
        for r in evs:
            k = keyf(r); dt = datetime.date.fromisoformat(r['date'])
            for o in reversed(out):
                if o['_k'] == k and (dt - datetime.date.fromisoformat(o['date'])).days <= days:
                    o['doc_ids'].add(r['doc_id']); o['outlets'].add(r['source'])
                    if 'stage' in r and RANK.get(r['stage'], 9) < RANK.get(o.get('stage'), 9): o['stage'] = r['stage']
                    if not o.get('settlement_en') and r.get('settlement_en'): o['settlement_en'] = r['settlement_en']; o['settlement_ar'] = r['settlement_ar']
                    if not o.get('place_id') and r.get('place_id'): o['place_id'] = r['place_id']; o['place_en'] = r['place_en']; o['governorate'] = r.get('governorate')
                    break
            else:
                out.append({**r, '_k': k, 'doc_ids': {r['doc_id']}, 'outlets': {r['source']}})
        for o in out: o['doc_ids'] = sorted(o['doc_ids']); o['outlets'] = sorted(o['outlets']); o.pop('_k')
        return out
    RANK = {'tender': 0, 'approval': 1, 'plan': 2, 'permit': 3, 'promote': 4, 'build': 5}
    U = dedupe(units_events, lambda r: r['units'], 45)
    # ── outposts ──
    NEW = re.compile(r'بؤر[ةه]\s+(?:استيطانية|إستيطانية|استعمارية)\s+(?:رعوية\s+|زراعية\s+)?جديدة|(?:إقامة|اقامة|أقام(?:وا|ت|ها)?|نصب(?:وا|ت)?|تثبيت|ثبت(?:وا)?|إنشاء|انشاء|أنشأ(?:وا|ت)?|شرع(?:وا|ت)? في إقامة|الشروع في إقامة|بدأ(?:وا)? (?:ب)?إقامة|يقيم(?:ون)?|تقيم)\s+(?:\S+\s+){0,3}?بؤر[ةه]\s+(?:استيطانية|إستيطانية|استعمارية)')
    REMOVED = re.compile(r'إخلاء|اخلاء|تفكيك|إزالة|ازالة|هدم بؤرة|أخلت|أزالت|فككت')
    LEGAL = re.compile(r'شرعن|تبييض|تشريع|اعتراف ب|الاعتراف ب')
    PAST = re.compile(r'قبل (?:نحو |حوالي )?(?:\d+|عدة|بضعة|عام|شهر|أشهر|سنوات|سنة|أسابيع)|منذ (?:نحو |حوالي )?(?:\d+|عدة|بضعة|سنوات|أشهر|عام|شهر)|في عام \d{4}|عام \d{4}|العام الماضي|سابق|السابق|آنذاك|كانت قد|كان قد|في وقت سابق')
    LOC = re.compile(r'(?:على أراضي|في أراضي|بأراضي|على اراضي)\s+(?:قرية|قريتي|بلدة|بلدتي|مدينة|خربة|منطقة)?\s*([^\s،,.()]+(?:\s+[^\s،,.()]+)?)|(?:في|ب)\s*(?:قرية|بلدة|خربة)\s+([^\s،,.()]+(?:\s+[^\s،,.()]+)?)|(?:شرق|غرب|شمال|جنوب)(?:ي|ا)?\s+(?:مدينة|بلدة|قرية|خربة)?\s*([^\s،,.()]+)')
    GOVS = {'جنين':'Jenin','طوباس':'Tubas','طولكرم':'Tulkarm','نابلس':'Nablus','قلقيلية':'Qalqilya','سلفيت':'Salfit','رام الله':'Ramallah','أريحا':'Jericho','اريحا':'Jericho','القدس':'Jerusalem','بيت لحم':'Bethlehem','الخليل':'Hebron'}
    locs = json.load(open(S + '/localities.json'))
    LOC_KEYS = {}
    for l in locs:
        k = key(l['ar']);
        if k and len(k) >= 3: LOC_KEYS.setdefault(k, l)
    def place_of(sent):
        n = norm(sent)
        for m in LOC.finditer(n):
            raw = next(g for g in m.groups() if g)
            k = key(raw)
            for cand in (k, ' '.join(k.split()[:2]), k.split()[0] if k else ''):
                if cand in LOC_KEYS and len(cand) >= 3: return raw, LOC_KEYS[cand]
        return None, None
    def gov_of(sent, loc):
        if loc and loc.get('gov_en'): return loc['gov_en']
        for ar, en in GOVS.items():
            if re.search(r'(?:محافظة|شرق|غرب|شمال|جنوب|قضاء|في)\s*(?:ي|ا)?\s*(?:مدينة)?\s*' + ar, sent): return en
        return None
    op_events = []
    for line in open(S + '/texts-outposts.ndjson'):
        x = json.loads(line); d = (x['date'] or '')[:10]
        if not d: continue
        for s in sents(x['body']):
            n = norm(s)
            if not NEW.search(n) or REMOVED.search(n) or not SUBJ.search(n): continue
            if re.search(r'\d+\s*بؤر', n) or re.search(r'(?:عشرات|مئات|عدد من|عددا من|عدة|العديد من)\s+(?:ال)?بؤر', n): continue   # a count of outposts is an aggregate, not an event
            nm = NEW.search(n)
            if nm.group(0).startswith('بؤر') and not re.search(r'(?:أقام|اقام|أقاموا|نصب|نصبوا|أنشأ|انشأ|أنشأوا|إقامة|اقامة|إنشاء|انشاء|شرع|شرعوا|يقيم|يقيمون|تقيم|بدأ|بدأوا|باشر|تثبيت|ثبت|ينشئ|ينشىء|تنشئ|ينصب|ينصبون)', n): continue
            if re.search(r'(?:لإقامة|لاقامة|بهدف إقامة|محاولة إقامة|محاولات إقامة|لبناء) بؤرة', n) and not re.search(r'بدأ|شرع|باشر', n): continue
            if re.search(r'\bتحذير|\bحذر|\bتهديد|\bهدد|\bمخاوف|\bتهدف|\bيهدف|\bمحاولة|\bمحاولات|\bخطر|\bتمهيد|\bنية\b|\bينوون|\bيسعون|\bيخطط|\bتخطط|مخطط لإقامة', n): continue
            if re.search(r'(?:كانون|شباط|آذار|نيسان|أيار|حزيران|تموز|آب|أيلول|تشرين)[^،.]{0,25}الماضي', n): continue
            stage = 'legalised' if LEGAL.search(n) else 'new'
            if stage == 'new' and (PAST.search(n) or re.search(r'مؤخرا|مؤخراً|قبل نحو|كان المستوطنون قد|كانوا قد', n)): continue
            explicit = re.search(r'في (\d{1,2})/(\d{1,2})/(\d{4})', n)
            if not (DAY.search(n) or explicit or (x['title'] and NEW.search(norm(x['title'])))): continue
            raw, loc = place_of(n); gov = gov_of(n, loc)
            m = re.search(r'في (\d{1,2})/(\d{1,2})/(\d{4})', n)
            ev_date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else d
            op_events.append({'doc_id': x['doc_id'], 'date': ev_date, 'published': d, 'source': x['source'], 'url': x['url'], 'stage': stage,
                              'place_raw': raw, 'place_id': loc['place_id'] if loc else None, 'place_en': loc['en'] if loc else None, 'governorate': gov, 'quote': s[:300]})
    O = dedupe([e for e in op_events if e['stage'] == 'new'], lambda r: (r['place_id'] or key(r['place_raw'] or '') or (r['governorate'], 'nogov')), 45)
    # ── write + report ──
    for name, rows in (('events-units', U), ('aggregates-units', units_aggs), ('events-outposts', O)):
        with open(f'{S}/{name}.ndjson', 'w') as f:
            for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"units: {len(units_events)} sentence hits → {len(U)} events; {len(units_aggs)} aggregate sentences; settlements named {sum(1 for r in U if r['settlement_en'])}/{len(U)}")
    print(f"outposts: {len(op_events)} hits → {len(O)} new-outpost events; placed {sum(1 for r in O if r['place_id'])}, governorate {sum(1 for r in O if r['governorate'])}")
    by = collections.Counter(r['date'][:4] for r in U); print('unit events by year:', dict(sorted(by.items())))
    st = collections.defaultdict(lambda: collections.defaultdict(int))
    for r in U: st[r['date'][:4]][r['stage']] += r['units']
    print('units by year and stage:'); [print('  ', y, dict(v)) for y, v in sorted(st.items()) if y >= '2012']
    bu = collections.defaultdict(int)
    for r in U: bu[r['date'][:4]] += r['units']
    print('units summed by year:', dict(sorted(bu.items())))
    bo = collections.Counter(r['date'][:4] for r in O); print('new outposts by year:', dict(sorted(bo.items())))
    random.seed(11)
    random.seed(31)
    print('\n--- 16 unit events ---')
    for r in random.sample(U, 16): print(f"{r['date']} {r['stage']:8} {r['units']:>6} {str(r['settlement_en'] or r['settlement_ar'] or r['region'] or '-'):18} x{len(r['outlets'])} | {r['quote'][:150]}")
    random.seed(37)
    print('\n--- 16 outposts ---')
    for r in random.sample(O, 16): print(f"{r['date']} {str(r['place_en'] or r['place_raw'] or '-'):22} {str(r['governorate'] or '-'):10} x{len(r['outlets'])} | {r['quote'][:150]}")


def main(argv: list[str]) -> int:
    d = Path(argv[argv.index("--from") + 1]) if "--from" in argv else OUT
    if "--from" not in argv:
        print("archive → texts"); dump_texts(d); dump_reference(d)
    run(str(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
