-- 063 — the IMF terms, read at last (Zaid, 2026-08-08)
--
-- G5.11's last failure. imf.org returns 403 to this host, so Zaid opened the
-- page himself and supplied the text. The answer is more precise than either
-- of the two outcomes I had predicted, and CC-BY-4.0 — inherited from v1's
-- registry and never checked — was wrong in BOTH directions at once.
--
-- WRONG, STRICTER THAN RECORDED: the IMF's general terms are
--   "the Content presented on the IMF Sites are the intellectual property of
--    the IMF and are published 'All Rights Reserved'"
-- with downloading permitted "for personal, noncommercial usage only without
-- any right to resell, redistribute, compile, or create derivative works".
-- Nothing like CC-BY.
--
-- WRONG, MORE PERMISSIVE THAN THAT: a separate section governs statistical
-- data and explicitly overrides the general rule —
--   "Notwithstanding the general prohibition on the commercial use of IMF
--    Content, with respect to published statistical data made available on
--    IMF Sites, the following special terms shall govern."
-- and it names the World Economic Outlook database by name. Every code we
-- hold in v1_economic_imf (LP, PPPGDP, NGDPD, NGDPDPC, BCA, BCA_NGDPD,
-- PPPEX, PPPPC …) is WEO, so these special terms are the ones that apply.
--
-- Under them we MAY redistribute:
--   "You may download, extract, copy, create derivative works, publish,
--    distribute, and use Data obtained from IMF Sites, subject to the
--    following conditions"
-- and the first condition is attribution in a stated format.
--
-- We may NOT sell without asking:
--   "For any potential commercial reuse of IMF Data, please email
--    copyright@imf.org to request permission."
--
-- So: `redistribution = attribution` and `commercial_use = false`. The 474
-- rows stay served, free and credited; they leave the commercial tier. This
-- is not a downgrade of the databank — it is the difference between a
-- licence we assumed and one we read.
--
-- Recorded as LicenseRef-* rather than forced into an SPDX identifier,
-- because no SPDX identifier means "redistributable with attribution,
-- commercial by permission" and picking a near-miss is how the CC-BY-4.0 got
-- there in the first place.

UPDATE source SET
    license_spdx      = 'LicenseRef-IMF-Data-Terms-2024-10-11',
    commercial_use    = false,
    share_alike       = false,
    attribution_required = true,
    redistribution    = 'attribution',
    terms_url         = 'https://www.imf.org/en/About/copyright-and-terms',
    terms_verified_at = '2026-08-08 00:00+00',
    attribution_text  = 'Source: International Monetary Fund, World Economic '
                        'Outlook database, '
                        'https://www.imf.org/en/Publications/WEO/weo-database. '
                        '© IMF.',
    terms_evidence    =
      'IMF Copyright and Usage, effective 2024-10-11, read 2026-08-08. '
      'GENERAL: Content is "published ''All Rights Reserved''"; downloading '
      'is permitted "for personal, noncommercial usage only without any right '
      'to resell, redistribute, compile, or create derivative works". '
      'BUT A SPECIAL SECTION GOVERNS STATISTICAL DATA and says so expressly: '
      '"Notwithstanding the general prohibition on the commercial use of IMF '
      'Content, with respect to published statistical data made available on '
      'IMF Sites, the following special terms shall govern." It names the '
      '"World Economic Outlook database", which is exactly what our 474 rows '
      'are. Under it: "You may download, extract, copy, create derivative '
      'works, publish, distribute, and use Data obtained from IMF Sites, '
      'subject to the following conditions" — attribution as '
      '"Source: International Monetary Fund, Database Name, <<link>>"; no '
      'alteration that affects the Data''s nature or accuracy, and any '
      'material transformation stated explicitly; downstream users to be told '
      'the terms. COMMERCIAL NEEDS ASKING: "For any potential commercial '
      'reuse of IMF Data, please email copyright@imf.org to request '
      'permission." Hence commercial_use=false with redistribution=attribution. '
      'TWO FURTHER RESTRICTIONS worth carrying: the IMF "prohibits the bulk '
      'download of information by automated technology without explicit '
      'permission" (relevant when Stage 7 replaces v1 with a direct fetcher), '
      'and it "does not permit use of its Content or Sites for the training '
      'of large language models (LLMs) without explicit permission" — reading '
      'the data at inference time is not training, but nothing here may ever '
      'be fine-tuned on. IF EVER SOLD: "sellers must inform purchasers that '
      'the Data is available free of charge from the IMF."'
 WHERE key = 'imf';

-- Commercial reuse is ASKABLE, and the address is published. That makes it a
-- twelfth letter rather than a closed door.
INSERT INTO source_permission (source_key, status, scope, contact,
                               letter_path, notes)
VALUES ('imf', 'not_asked',
        'Permission for commercial reuse of World Economic Outlook figures '
        'for the State of Palestine, and confirmation that an automated '
        'nightly fetch of those series is within the bulk-download rule.',
        'copyright@imf.org',
        'db/scout/letters/imf.md',
        'Redistribution with attribution is ALREADY permitted by the IMF''s '
        'published Data terms — this asks only about the commercial tier and '
        'about automated fetching. The 474 rows are served either way.')
ON CONFLICT (source_key) DO NOTHING;
