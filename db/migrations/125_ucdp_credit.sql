-- 125 · UCDP's credit line, reordered so a spoken answer reads a whole name (2026-10-15)
--
-- A spoken answer gives the source line at most 120 characters, cut at a sentence or clause (serve/when.py
-- short_source). UCDP's line (374 characters) has no sentence end before 120, so answers read
-- "… Uppsala Conflict Data" and stopped mid-name. Nothing in the citation UCDP asks for is dropped: the
-- programme, the two datasets, the licence, the university and the three papers all stay; the first sentence
-- now names the programme and the licence, and is what a spoken answer reads:
--   "Conflict events: Uppsala Conflict Data Program (UCDP), Georeferenced and Candidate Events datasets, CC BY 4.0"
-- The grade (CC-BY-4.0, attribution) does not change.
--
-- Rollback: UPDATE source SET attribution_text = 'Conflict events: UCDP Georeferenced Event Dataset (GED) and UCDP Candidate Events Dataset, Uppsala Conflict Data Program, Uppsala University (ucdp.uu.se), licensed CC BY 4.0. Sundberg & Melander (2013), Journal of Peace Research 50(4); Davies, Pettersson & Öberg (2026), Journal of Peace Research; candidate events: Hegre, Croicu, Eck & Högbladh (2020), Research & Politics.' WHERE key = 'ucdp';

UPDATE source
   SET attribution_text = 'Conflict events: Uppsala Conflict Data Program (UCDP), Georeferenced and Candidate Events datasets, CC BY 4.0. '
                       || 'UCDP Georeferenced Event Dataset (GED) and UCDP Candidate Events Dataset, Uppsala University (ucdp.uu.se). '
                       || 'Sundberg & Melander (2013), Journal of Peace Research 50(4); Davies, Pettersson & Öberg (2026), Journal of Peace Research; '
                       || 'candidate events: Hegre, Croicu, Eck & Högbladh (2020), Research & Politics.'
 WHERE key = 'ucdp' AND attribution_text LIKE 'Conflict events: UCDP Georeferenced%';
