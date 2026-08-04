# تقرير الصيانة الأسبوعي — ٤ آب ٢٠٢٦

زيد، النظام شغّال: ١٦ من ١٧ مهمة و١٢ من ١٢ مصدر خضراء، والنسخة الاحتياطية تمّت (١٫٢ مليون صف). العطل الوحيد المفتوح هو تشغيل الصيانة نفسه — فشل ٦:٣٠ لأنه ما لقي أمر `claude`، انصلح قبل ما أبدأ، وهذا التشغيل هو الدليل. بينطفي لحاله لما أخلص.

**الوقود — الخبر المهم.** المصدر النصّي **مات**، مو بس ضعف: آخر نشرة أمس ١:٥١ ظهراً. النشرات باليوم ٣٤١ ← ١٠١ ← ٩ ← ١ ← صفر. القناة لسّه بتنشر ١١٤ رسالة اليوم، بس كلها **صور بدون نص**.

والنظام تصرّف صح لحاله: كل الـ١٩٦ محطة صارت **"غير معروف"**، الثقة صفر، وعمر المعلومة مكتوب. **ولا محطة معروضة إنها فيها وقود.** ما حدا تدخّل — وهذا بالضبط اللي بيميّزنا. اليوم حوالي ٩:١٧ رح تصير إشارة الوقود حمرا؛ **صحيحة، مو عطل جديد**.

**[ZAID] — القرار الوحيد إلك:** الباقي الوحيد للوقود هو قراءة الصور، وهي **راسبة**: ٠٫٩٥٧، و**٣٤ حالة الصورة قالت "متوفر" والنص قال "مش متوفر"**، وصفر بالعكس. يعني غلطها كله باتجاه الطمأنة الكاذبة اللي بتبعث حدا على محطة فاضية، والشرط صفر. ما رفعتها ولا بروّجها — بتضلّ "غير معروف"، ولا نعرض الصور مع تحذير؟

الدقة: ما في جولة مستحقّة — v1.6 انقاست الصبح ٠٫٨٩٧. و`arrest` و`closure` و`demolition` و`death` لسّه **غير مقاسة**، وبنقولها بصراحة.

ملاحظة صغيرة: رح يضلّ إنذار واحد مفتوح باسم `palestine-v2-maintain.service` — سجلّ فشل الساعة ٦:٣٠. ما مسحته: إنذار فشلي أنا مو من حقّي أمسحه بنفسي. لما تشوفه، أمره: `.venv/bin/python -m ops.alert --clear`.

---

## English

**Green.** 16/17 jobs, 12/12 feeds, backup ok (1,237,239 rows, off-host). Verification: **59/60 SQL**, 315 pytest, 34 + 27 standalone, eval_geo 89.3% / 0 foreign leaks. The one SQL failure is G3.7 naming `maintain` — this run. Proved in a rolled-back transaction that its success flips G3.7 to PASS: 60/60 the moment this run exits. Not a defect to "fix".

**Measured.** Quarantine re-check: fuel images 0.957 with **34 one-sided false-availables** (gate ≥0.99 and ZERO) — stays. Palhub roads 0.7215 over 6,657 pairs (gate ≥0.90) — stays. No precision round due (v1.6 scored today, 0.897 [0.80–0.95]). **Unmeasured, stated as such: arrest, closure, demolition, death** (n<5). Classifier untouched, so 0.897 still holds.

**Root-caused, not pattern-matched.** The fuel silence resembled the known "drying up" story. It isn't: the collector is healthy and the channel is live — palhub went image-only. Last text bulletin 2026-08-03 13:51:30Z matches the last DB row to the second.

**Fixed.** `db5423b` — `ops/maintain-logs/` was not git-ignored; an unattended agent's full session transcript sat one `git add -A` from permanent history. Failing test written first, reads LOGDIR from `maintain.sh`. `d2def3a` — HANDOFF's test counts (436, measured).

**Deliberately not done.** No promotion of the fuel image feed (failed gate, Zaid's call). No classifier, threshold, or serving-gate change. No re-scoring of scored rounds. Filed untouched: round 6's v1.7 list — street-name governorate, two actor inversions, settlement expansion read as demolition. **Did not `--clear` the `palestine-v2-maintain.service` alarm**: it records this run's own predecessor failing, and an unattended agent acknowledging the alarm raised by its own crash is marking its own homework. The `watchdog:job:maintain` twin self-resolves once the heartbeat lands.
