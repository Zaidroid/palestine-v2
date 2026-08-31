# صيانة الإثنين — ٣١ آب ٢٠٢٦

**يا زيد: أهم شيء اليوم — النسخة الاحتياطية البعيدة متوقفة منذ ست ليالٍ، والسبب ليس عندنا. وصيانة الأسبوع الماضي لم تحدث أصلاً.**

١. **[لك القرار] النسخة الاحتياطية خارج الجهاز متوقفة منذ ٢٥ آب — ست ليالٍ.** مساحة غوغل درايف امتلأت تماماً: ١٥.٠٨٧ من أصل ١٥ غيغابايت. أربع مهام نسخ تتشارك نفس الحساب: `zlab-restic` ٨.٤ غيغا (٥٦٪)، ومشروع فلسطين ٤.٧ غيغا (٣١٪)، و`agent-backups` ٢ غيغا، و`lifeos` ٠.٠٣. النسخ المحلية سليمة (٧ مجموعات، ٢.٦ غيغا) والنسخة اليومية ما زالت تُكتب — **الذي توقف هو النسخة التي تنجو لو احترق هذا الجهاز**. واختبار الاسترجاع الأسبوعي يفشل لأنه يبحث عن نسخة لم تُرفع، وهذا سلوك صحيح لا عطل ثانٍ. لم ألمس شيئاً: تفريغ المساحة يعني حذف نسخ أحدهم، واختيار أي المهام الأربع تأخذ المساحة قرارك أنت.

٢. **[لك القرار] وآلية التنظيف التي كان يفترض أن تمنع هذا لم تحذف شيئاً قط.** القاعدة "احتفظ بآخر ٣٠ + كل نسخة يوم ١ من الشهر للأبد" — وفي ١ آب كانت هناك تسع نسخ يدوية من أيام البناء، وكلها مثبّتة للأبد. جرّبتُ القاعدة على القائمة الحقيقية (٣٩ نسخة): **قائمة الحذف فارغة، ودائماً كانت**. والأسوأ: التنظيف يعمل *بعد* الرفع، فإذا امتلأت المساحة فشل الرفع ولم يصل التنظيف أبداً. سطر واحد يصلح كلاً منهما، لكنه يحذف نسخاً احتياطية — فتركته لك.

٣. **[لك القرار] صيانة ٢٤ آب لم تحدث: `API Error: 529 Overloaded`.** هذه ثالث طريقة مختلفة يفشل بها المشغّل في خمسة أسابيع (أمر مفقود، ثم انتهاء الجلسة، ثم ازدحام الخادم). **اثنان من آخر أربعة إثنينات لم يحدثا**، ولا شيء يعيد المحاولة.

٤. **أصلحتُ عطلاً كان صامتاً منذ ولادته: جامع أخبار الكهرباء كان يقرأ القائمة الخطأ.** موقع كهرباء الشمال ينشر قائمتين في صفحة واحدة: أخبار الشركة (بتواريخ)، وإعلانات فصل التيار (بدون تواريخ). الجامع كان يقرأ الأولى، والإعلانات ليست فيها أبداً. النتيجة: "صفر إعلانات" بينما **سبعة كانت على الصفحة**. والأخطر — في صيانة ١٧ آب قلتُ لك إن الكهرباء صامتة لأن *المصدر* صامت، وإن آخر إعلان عندهم ١٣/٠٨. **ذلك كان خبراً عن زيارة، لا إعلان فصل.** التحقّق نفسه جرى عبر العدسة المكسورة. الآن: ٧ إعلانات، ٦ بمواعيد مقروءة، ٥ محدّدة المكان، **ولا واحد فعّال الآن** فلا شيء قديم يُقدَّم كانقطاع جارٍ. استرجعنا ٤ إعلانات لم نرها قط (زواتا، عصيرة الشمالية، نابلس في ٢١/٨، والباذان في ٢٣/٨).

٥. النظام وجدته **أحمر قبل أن أبدأ** — اختباران كانا يفشلان أصلاً. أصلحتُ واحداً (رقم في README تخلّف: ٢٧٥ ألف مقابل ٣١٢ ألف حقيقية)، والثاني تركته لك لأنه يحتاج قراراً لا تصليحاً.

---

## English detail

**Green.** 16/19 jobs, 8/12 feeds. as_of evidence **1,342 entries / 0 bad** (was 1,034), manifest grew **9 → 23 days** — the history layer is provable. Gap radar 31 datasets: 27 fresh, 0 late, **1 stalled**. Scout swept 253 PSE packages, 40 candidates, **0 never seen before** — nothing to license-read.

**Measured.** The Aug-17 palhub fix is now proved by instrument: measure-review 0 pairs → 14,662 → **31,634** at 0.7909, the trailing window moving as a live feed's must. Still below its gate, still quarantined, **not promoted**. fuel_images still n=0 (UNMEASURABLE, text bulletins dead since Aug 3). No precision round due — classifier 1.6 scored 0.897 on Aug 4, 26 days against a 35-day ceiling, so it falls due on **Sep 14, not Sep 7**. No classifier rule touched, so 1.6 stays measured; arrest, closure and demolition remain UNMEASURED from round 6.

**The one stalled dataset is not new.** `v1_conflict_tech4palestine` crossed from "late" to "stalled" — it is [ZAID] 1 from Aug 17 deteriorating on schedule, now 23 days frozen. `ops/fetch_t4p.py` is healthy and fetched 1,059 days at 03:45 today; no spec reads it. Not the June-9 class: nothing broke, the cut was never built.

**Fixed.** `c557729` the power collector's discovery, with four regression tests written first. README observations floor 275,000 → 310,000, which `test_license_model` demanded by name.

**Verification.** 82 SQL PASS + **1 FAIL** — the liveness gate naming backup, maintain and restore-test. That FAIL is honest and, unlike last week's, **does not clear when this run exits**: two of the three need the quota freed. pytest 614 passed / 1 failed / 1 skipped, 34 + 27 standalone, eval_geo 89.5% agreement (gate ≥80%) and 0 foreign leaks.

**[ZAID] 4 — the correlate test, red before I arrived.** Bread-vs-sugar from 2026-07-01 now has 1 overlapping point where it had 0, so the refusal reads "1 of 12 required" not "no points". The test exists so three kinds of absence send callers three different places; restoring that means choosing a window that is empty and stays empty. A test-design judgment, not a stale number.

**[ZAID] 5 — restated, unchanged.** The Gaza casualty cut (`conflict.yaml` still reads v1); the maintainer's credential; fuel's missing believed source.

**Deliberately not done.** Promoted nothing, moved no gate, touched no policy. Did not free the Drive quota or fix `prune_remote` — both delete backups. Did not raise `checkpoint_settlers`' 24h default: chased it and the feed is innocent (p50 11.2h, **p99 2.14 days**, 29 arrivals < the 60 needed to derive a threshold), so the alarm is the ceiling, and moving a ceiling is a threshold change. Did not touch v1's 28–30 failing steps — cutting v2 off them is the fix, not repairing them.
