# صيانة الإثنين — ١٧ آب ٢٠٢٦

**يا زيد: النظام يعمل، ولكن وجدتُ عطلين كانا صامتين تماماً — وكلاهما مُصلَح الآن.**

١. **جامع بيانات الطرق (بالهَب) لم يكتب سطراً واحداً منذ ٢ آب.** كان يعمل كل خمس دقائق، ويقول "نجحت" في كل مرة — نحو ٤٣٠٠ تشغيلة على مدى خمسة عشر يوماً — وهو لا يفعل شيئاً. السبب سطر واحد في استعلام قاعدة البيانات: كان يطلب أقدم ٥٠٠ نشرة ثم يستبعد ما عالجه سابقاً، فبقي يدور في المكان. أصلحته، و٥٤٠٨ نشرات محجوزة تدخل الآن؛ وصلنا ٣٨٬١٨٨ قراءة والعدّاد يرتفع. (القناة نفسها صمتت بعد ١١ آب، فهذا استرجاع لما فات لا استئناف لبثّ حيّ.)

٢. **قناة الإنذار كانت معطّلة تسعة أيام.** انقطعت الكهرباء عن الجهاز في ٨ آب أثناء الكتابة فتلف سطر في ملف الإنذارات، وصار كل من يقرأ الملف ينهار. النتيجة الملموسة: **الوقود صمت في ٨ آب ولم يصلك إنذار واحد**، وإنذار قديم بقي مفتوحاً لا يستطيع أحد إغلاقه. أصلحته، وأُطلقت الإنذارات الأربعة المستحقة، وأُغلق القديم.

٣. **[لك القرار] أرقام غزة التراكمية متوقفة عند ٨ آب — تسعة أيام.** عندنا ٧٣٬٣٨٤ شهيداً و١٧٤٬٢٤٢ جريحاً؛ والناشر يقول ٧٣٬٣٩١ و١٧٤٬٢٨٠ حتى ١٥ آب. البيانات الجديدة تنزل عندنا على القرص كل ليلة ولا أحد يقرأها: هذا الجزء ما زال يمرّ عبر النظام القديم الذي مات في ٩ آب. الفصل قرار وتصميم، لا تصليح آلي — فتركته لك.

٤. **[لك القرار] صيانة ١٠ آب لم تحدث أصلاً**: انتهت صلاحية تسجيل الدخول. أسبوع كامل بلا صيانة، وإنذارها وقع في الملف التالف.

٥. النسخة الاحتياطية سليمة تماماً: استرجعنا ١٬٦١٣٬٦٠٢ صفاً من النسخة البعيدة وطابقت. الكهرباء والوقود صامتان لأن **المصدر** صمت — تحققتُ من موقع الكهرباء بنفسي: آخر إعلان عندهم ١٣/٠٨.

---

## English detail

**Green.** 18/19 jobs, 9/12 feeds. Backup 79.8s, 1,613,602 rows off-host; restore test PASSED from the OFF-SITE copy — 30 tables, hypertables intact. as_of evidence 1,034 entries / 0 bad, grew 2 → 9 days. Gap radar: 27 fresh, 1 late, 0 stalled. Scout swept 254 PSE datasets, 40 candidates, **0 never seen before** — nothing to license-read.

**Measured.** No precision round due: classifier 1.6 scored 2026-08-04 at 0.897, 12 days old against a 35-day ceiling. **No classifier rule was touched, so 1.6 stays measured**; arrest, closure and demolition remain UNMEASURED. The two quarantined feeds are now UNMEASURABLE, not failed — fuel_images n=0 (text bulletins dead since Aug 3) and palhub_roads n=0 (the bug above). Neither promoted; both stay quarantined.

**Fixed.** `c9282fe` the palhub LIMIT-before-filter starvation, `8460d10` the torn alerts log. Each has a failing regression test written first. Verification after: 82 SQL PASS + 1 known FAIL (G3.7 naming this run, clears when it exits), 611 pytest passed / 1 skipped, 34 + 27 standalone, eval_geo 89.8% agreement and 0 foreign leaks.

**[ZAID] 1 — the Gaza casualty series.** `conflict.yaml` is the last big spec still reading v1, and v1 died on Aug 9. `ops/fetch_t4p.py` already downloads the fresh file nightly; no spec reads it. Cutting it needs `cut_equivalence`, a replay transformer and a licence reading — Stage 7 work, not mechanical. Build it or say when.

**[ZAID] 2 — the maintainer's credential.** Nothing in this repo can renew the Claude CLI OAuth, so a silent skipped week recurs whenever it expires. Worth an expiry check in `maintain.sh` pre-flight.

**[ZAID] 3 — fuel, restated from Aug 4.** Still no believed source. Image cards failed their gate (0.957 with 34 false-availables). Serve them with a warning, or keep serving "unknown"? Your call, unchanged.

**Deliberately not done.** Did not promote anything or move a gate. Did not touch v1 — its 13 failing refresh steps (25–29 nights) are restated, not chased; cutting v2 off them is the fix, not repairing them. Did not fix `measure_review` reporting `gate_crossed: false` when n=0, which makes "failed" and "unmeasurable" identical in the ledger — that is a judgment about what the ledger means. Did not add gazetteer aliases for the 8 unresolved palhub checkpoint names; each needs a real source, not a guess. Did not clear the 144 open alarms — most predate Aug 8 and acknowledging them is yours.
