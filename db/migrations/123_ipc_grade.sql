-- 123 · IPC's grade, and a credit line that survives being read aloud (2026-10-14)
--
-- Zaid, asked whether partners may see IPC's famine classification: "yes for ipc data". Graded as HDX
-- states it: "Public Domain / No restrictions (CC0)" → open, commercial use allowed.
-- Its credit line (122) was 122 characters and the spoken answer cuts at 120 on a clause boundary, so it
-- was read as "... National IPC Technical Working Group, via." It is shortened to fit.
--
-- Rollback: UPDATE source SET license_spdx = 'verify-required', redistribution = 'ask', commercial_use = false,
--             attribution_text = 'Acute food insecurity: Integrated Food Security Phase Classification (IPC), National IPC Technical Working Group, via HDX.'
--           WHERE key = 'ipc_hdx';

UPDATE source
   SET license_spdx = 'CC0-1.0', redistribution = 'open', commercial_use = true,
       attribution_text = 'Acute food insecurity: IPC (Integrated Food Security Phase Classification), via HDX.',
       terms_evidence = terms_evidence || ' Graded by Zaid on 2026-10-14 ("yes for ipc data"): CC0, open.'
 WHERE key = 'ipc_hdx' AND redistribution = 'ask';
