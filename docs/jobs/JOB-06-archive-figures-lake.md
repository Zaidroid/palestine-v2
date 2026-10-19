---
job: 06
slug: archive-figures-lake
status: open
opened: 2026-10-19 by Claude (Fable), for an overnight run
branch: job-06-archive-figures-lake
deadline: 2026-10-20 08:00 UTC (write the return with whatever is finished)
---

# JOB-06 — The figures lake: every number the archive holds, catalogued, and the ten best series reviewed

**Why.** Zaid's goal for the archive (13 Oct): "the data that nobody realized is there and tells a story". The archive now holds 2.75 million texts with a body (5.04 million with a title), 1948 → today, and we have only ever asked it one question at a time (fuel, CPI, arrests, outposts, water, hospitals, the rota). Nobody has read it whole for numbers. This job does, in one night: every sentence that carries a number with a unit and a subject, tagged by what it measures, counted by month and place, and the ten families that make a series read line by line and delivered loadable.

**Goal.** Three deliverables: the lake (every figure sentence, tagged), the catalogue (what series exist, how deep, how clean), and the top ten series reviewed to the JOB-04 standard.

## Inputs

The corpus, dumped once, read many times. One server-side cursor, streamed, gzip shards by publisher:

```bash
cd /home/zaid/palestine-v2 && mkdir -p data/raw/jobs/06/corpus
.venv/bin/python - <<'PY'
import gzip, json, sys
sys.path.insert(0, '.')
from resolve.db import connect
with connect() as c:
    c.execute("SET default_transaction_read_only = on")
    cur = c.cursor(name='lake')          # server-side: streams, never loads 10 GB
    cur.itersize = 5000
    cur.execute("SELECT doc_id, published_at, source, kind, url, title, body FROM document WHERE body IS NOT NULL AND body <> '' ORDER BY source, published_at")
    files, n = {}, 0
    for doc_id, at, src, kind, url, title, body in cur:
        f = files.get(src)
        if f is None:
            f = files[src] = gzip.open(f"data/raw/jobs/06/corpus/{src.replace(':','_')}.ndjson.gz", 'wt')
        f.write(json.dumps({"doc_id": doc_id, "date": at.isoformat() if at else None, "source": src, "kind": kind, "url": url, "title": title, "body": body}, ensure_ascii=False) + "\n"); n += 1
        if n % 100000 == 0: print(n, flush=True)
    for f in files.values(): f.close()
    print("done", n)
PY
```

About 2.75 M lines, 3–4 GB gzipped, 20–40 minutes. Check `df -h /` first: stop below 20 GB free. The dump is read-only on the database; keep it to ONE cursor.

## Step 1 — the lake (deterministic, parallel, CPU only)

Split each body into sentences; keep a sentence when it has a number (Western or Arabic-Indic digits, or a number word up to twenty, or «ألف/مليون» forms) AND a unit or counted noun AND a subject cue from the family list below. One line per figure sentence: `doc_id`, `date`, `publisher`, `url`, `family`, `cue` (the words that matched), `number` (the printed number, as a float; "12 ألفا و934" = 12934), `unit` (as printed), `qualifier` (نحو / أكثر من / حوالي / على الأقل / ما يزيد عن → about / more_than / at_least; else null), `place_hint` (a governorate, town or crossing named in the sentence, as printed, else null), `period_hint` (a month or year named in the sentence, else null), `authority_hint` (the body quoted — a ministry, OCHA, UNRWA, PCBS, GEDCO, CMWU, a prisoners' organisation, Peace Now, B'Tselem…; else null), `quote` (≤300 chars). Run 6 processes at most; the machine is shared with the live tier.

**The families (start here; add any you find, name them in the return):**

| family | what the number is | cues (Arabic; add forms) |
|---|---|---|
| fishing_zone | Gaza's permitted fishing area, nautical miles | ميل بحري / أميال بحرية / مساحة الصيد |
| rafah_crossing | Rafah open/closed days, travellers, trucks | معبر رفح / مسافر / يوم فتح / أغلق |
| kerem_shalom | Kerem Shalom / Erez trucks and closures | كرم أبو سالم / بيت حانون / إيرز / شاحنة |
| aid_trucks | trucks of aid entering Gaza per day | شاحنة مساعدات / دخلت / شاحنات |
| power_plant | Gaza power plant output, fuel, stoppage | محطة التوليد / ميغاواط / توقفت / وقود المحطة |
| cooking_gas | cooking gas price and availability, Gaza | غاز الطهي / أسطوانة / سعر الغاز |
| war_prices | food and fuel prices in Gaza during the war | سعر كيس الطحين / كيلو السكر / البيض / لتر البنزين (2023-10 →) |
| casualties_place | killed and injured, with the town named | شهيد / شهداء / إصابة / جريح + a place |
| settler_attacks | settler attacks as counted events | اعتداء مستوطنين / هاجم مستوطنون / اعتداءات |
| demolitions_village | structures demolished, with the village | هدم / هدمت / منشأة / منزل + a place |
| checkpoint_closure | a checkpoint closed or reopened, by name and day (2005 → 2023) | حاجز X / إغلاق الحاجز / فتح الحاجز / أغلقت قوات الاحتلال حاجز |
| road_gates | iron gates, road closures by village | بوابة حديدية / أغلقت مدخل / إغلاق الطريق |
| land_orders | confiscation/seizure orders, dunams, by village | أمر استيلاء / مصادرة / دونم / وضع اليد |
| trees_uprooted | trees uprooted or cut, by village | اقتلاع / قطع شجرة / شجرة زيتون / شتلة |
| land_bulldozed | land bulldozed, dunams | تجريف / جرفت / دونم |
| admin_detention | administrative detention orders issued/renewed | أمر اعتقال إداري / أوامر إدارية |
| child_detainees | children in detention, a count | طفل في سجون / أطفال معتقلين / قاصر |
| hunger_strike | prisoners on hunger strike, a count and a day count | إضراب عن الطعام / مضرب / يوم |
| deaths_in_custody | a prisoner's death with the date and the cumulative | استشهاد الأسير / الحركة الأسيرة / منذ 1967 |
| medical_permits | permits/referrals denied or granted, patients | تصريح علاج / تحويلة طبية / رفض / مريض |
| hospital_capacity | beds, occupancy, fuel days left | سرير / نسبة الإشغال / وقود المستشفيات / ساعات |
| schools | schools closed/damaged, students out, days lost | مدرسة مغلقة / تعطيل الدراسة / طالب / يوم دراسي |
| telecom_outage | internet/phone outage, hours or days | انقطاع الاتصالات / الإنترنت / ساعة / يوم |
| displaced | displaced people, a count | نازح / نازحين / تهجير / أسرة |
| journalists | journalists killed, arrested | صحفي / صحفيين |
| fishermen | fishermen arrested, boats confiscated | صياد / قارب / مركب |
| olive_harvest | olive harvest tonnage, oil | موسم الزيتون / طن / زيت |
| unemployment | unemployment and poverty rates, with the region | البطالة / الفقر / نسبة + a region |
| wages_remittances | wages, workers in Israel, remittances | عامل / أجر / تحويلات |
| other | a figure with a unit that fits no family — tag `other` and keep the cue | — |

## Step 2 — the catalogue

For every family: texts, figure sentences, distinct days, months covered (a list and a count out of the span), years covered, publishers, top authorities, the share of sentences with a place hint and a period hint, and a **12-row random read by you**: how many of the 12 are a real figure of that family as printed (not a warning, a forecast, a range, a cumulative, a different subject). Then a verdict per family: `series_ready` (≥ 24 months covered, ≥ 9/12 right), `sparse` (right but thin), `noise` (< 7/12 right: the cues need work), with one line on what a tighter pattern would need.

Write `data/raw/jobs/06/catalogue.json` and `catalogue.md` (a table per family, sorted by months covered × share right), plus `coverage.md`: a month × family grid of counts for 2005 → 2026 (a heat map in text).

## Step 3 — the ten best series, reviewed

Take the ten families with the highest (months covered × share right) that are not already a loaded series (fuel prices, CPI, arrests monthly, electricity hours, outposts and unit announcements are loaded; `fishing_zone`, `checkpoint_closure`, `aid_trucks`, `trees_uprooted`, `land_orders`, `admin_detention`, `hunger_strike`, `medical_permits`, `settler_attacks`, `war_prices` are the likely ten). For each: a reviewed NDJSON to the JOB-04 standard — every record read against its quote, `verdict` keep / fix / drop with a one-line note, the value, unit, place (gazetteer `place_id` when the town is named: `data/raw/settlements/localities.json` holds the localities with their governorate), the period or day, the authority, duplicates across outlets merged within 3 days. Target 300–3,000 kept records per family; if a family has more candidates than a night allows, review the most recent years first and say where you stopped.

## Return

`docs/jobs/JOB-06-RETURN.md`: the catalogue's top table (family, months, years, figures, share right, verdict); the ten reviewed series with their counts, spans and the 20-row self-check; the five best stories the lake suggests that nobody has (one line each, with the family and the span); what the patterns miss; and what was not finished by the deadline. Keep it under two pages; the files carry the detail.

## Rules and limits

- Read `docs/jobs/README.md` first. Database read-only (the dump above is the only database read); no `serve/`; no web; nothing published.
- Run detached with a log and a `DONE` marker; check `df -h /` before the dump and stop below 20 GB free; at most 6 worker processes; stop file `data/raw/jobs/06/STOP` (check it between shards).
- Every figure keeps its quote and `doc_id`; no number is inferred, rounded or summed into a record. A warning, a forecast, a range, a cumulative total is tagged as such in `qualifier`, never dropped silently from the lake (dropped only in the reviewed series, with the reason).
- Figures about lives are reported in the publisher's words; children are a count only when the text counts them.
- Delete the corpus shards at the end (`data/raw/jobs/06/corpus/`) unless the return says why they should stay; the lake, the catalogue and the reviewed series stay.
- By 08:00 UTC write the return with what is finished; a half-finished step is reported as half-finished.
