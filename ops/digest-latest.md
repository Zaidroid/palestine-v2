# صيانة الإثنين — ٢٢ أيلول ٢٠٢٦ (وصلت يوم الثلاثاء)

**يا زيد: هذا أول تقرير منذ ٧ أيلول. تشغيل الصيانة ليلة أمس انقطع بسبب حدّ الإنفاق، وكان يحمل إصلاحاً وجولة قياس لم يُحفظا. تحققتُ منهما وحفظتهما. والخبر الأهم أن مصنِّف الحوادث رسب في أول قياس كامل له: ٧٢٪، والمطلوب ٨٠٪.**

١. **مصنِّف الحوادث رسب.** قُرئ ٢٢٠ خبراً واحداً واحداً. من ١٨٠ خبراً يعرضها النظام حوادث، ١٢٩ صحيحة (٧٢٪). الأسوأ نوع "وفاة": ٧ صحيحة فقط من ٢٠. المشكلة ليست في قراءة الخبر، بل في أنه يقبل نصوصاً ليست أخباراً أصلاً. ٣٦ من الأخطاء الـ٥١ من هذا النوع: نعي فصائل، تشييع، رثاء، مقابلات، تقارير عامة، بيانات. أما في الأخبار الحقيقية فدقته ٩٠٪. وفي الاتجاه الآخر، من ٤٠ خبراً رفضها كانت ١٢ حوادث حقيقية (٣٠٪، وكانت ١٠٪).
   **[لك القرار]** هل النعي أو التشييع خبر وفاة؟ جوابك يحدد شكل الإصلاح. وإلى أن تقرر، واجهة الحوادث تعرض مصنِّفاً تحت بوابته: نتركها كما هي، أم نضع تحذيراً؟

٢. **حفظتُ إصلاح قاعدة البيانات.** فحص الجودة لكل مجموعة بيانات كان يحكم على صفوف الليلة الجديدة وحدها. لذلك رسب ملف اللاجئين أربع ليالٍ بسبب صف واحد من أربعة، مع أن المجموعة كلها ٣٣٦ صحيحة من ٣٣٩. الإصلاح يعمل منذ ليلة أمس، ونبض قاعدة البيانات عاد أخضر.

٣. **أخضر:** النسخ الاحتياطية تُحفظ كل ليلة على هيتزنر منذ ١٩ أيلول، وفي القرص ١٧٤ غيغا فارغة (كانت ١٦). أرشيف الإثبات فيه ١٬٨٠٣ ملفاً، ولا ملف تالفاً، ونما من ٢٩ يوماً إلى ٤٤. يوم ٢ أيلول ناقص لأن الجهاز كان مطفأً ٤٠ ساعة، لا لعطل.

٤. **[لك القرار] كما كان:** عدد شهداء غزة عندنا متوقف عند ٨ آب منذ ٤٥ يوماً (٧٣٬٣٨٤). الناشر وصل إلى ٧٣٬٩١٧ في ٢١ أيلول، والملف موجود عندنا لكن لا شيء يقرؤه؛ طريق إصلاحه في الخطة (العضو C). قناة الوقود تنشر صوراً فقط، ولا عطل عندنا. وطرق palhub تراجعت للأسبوع الخامس إلى ٧٢.٨٪، ولم أُرقِّها.

٥. **ما لم أفعله عمداً:** لم ألمس قواعد المصنِّف. هناك ست كلمات ناقصة فعلاً، مثل "مقتل" و"يفجر"، لكن إصلاحها يُبطل القياس الذي أخذناه للتو ولا يمسّ المشكلة الكبرى. ولم أُرقِّ أي مصدر، ولم أحرّك أي بوابة.

---

## English detail

**Adopted and committed.** The 09-21 hand-run hit the spend limit with two pieces of work uncommitted. Both were verified here and committed unchanged. `ae91490`: per-dataset floors were counted after the already-held skip, so refugees failed four nights on `3/4` while the dataset stood at 336/339. Its tests fail on `f934ae6` and pass with the fix, and it has been live since the 09-22 03:43 run. `eb5fa5e`: incident round 7, with 0 kin of rounds 1–6 and all 220 claims classified by 1.6.

**Measured.** Classifier 1.6: **0.717 [0.647–0.777], n=180, GATE FAIL**. death 0.350 is below the 0.60 floor; demolition 0.60, siege 0.65, settler_attack 0.70, closure/injury 0.75, shooting 0.85, arrest/raid 0.90. 36 of the 51 wrong rows are not reports (15 aftermath, 21 features/statements/roundups). On real reports it scores 129/144 = 0.896. Miss rate 30% (12/40), was 10%. No rule was touched, so **1.6 stays MEASURED, at 0.717**. palhub_roads: 34,650 pairs at 0.7279, the fifth straight weekly decline; still quarantined, **not promoted**. fuel_images is still unmeasurable.

**Green.** 19/20 jobs; the 20th, maintain, is this run. Feeds 10/12; the two fuel feeds are silent because upstream posts only photos. Backup on Hetzner: 2,442,590 rows in 93 s; disk 174 GB free. Vault 1,803 entries / 0 bad; v2 manifest 29 → 44 days (09-02 is missing because the host was down 40 h). Gap radar is unchanged from 09-07: 26 fresh / 1 late / 1 stalled / 2 dead-upstream / 1 closed, nothing newly stalled. Scout 09-20: 0 new packages scoring ≥ 7. The one never-seen package (a CTrees forest-biomass raster, score 6) was hidden by the 40-row cut. It is noise; the cut is filed.

**Verification.** SQL 82 PASS + G3.7 (`maintain`, this run's own heartbeat). pytest 664 passed / 2 skipped / 1 deselected; the deselected vault test was run as its own body. One skip is a stale fallback IP from the reboot and passes with `.env` loaded; the other is correlate at lag 0. Standalone 34 + 27; eval_geo 88.2%, 0 foreign leaks.

**[ZAID].** (1) Is an obituary or a funeral a death report? That decides whether v1.7 is a lexicon patch or a "not a report" gate. And what should `/v2/incidents` show while it is below its gate? (HANDOFF §6 still says 0.864.) (2) Gaza casualties, 45 days frozen: plan items F-10..F-12. (3) Fuel: serve "unknown" or the image cards that failed their gate? (4) Unchanged: the seat probe cannot see a mid-session cap (F-03c), and the vault test no longer fits in a run (22 min).

**Deliberately not done.** No v1.7 lexicon fixes: they would un-measure 1.6 a day after measuring it. No promotions, no gate changes. The 8 old power windows, the scout's cut and the stale test IP are left as filed.
