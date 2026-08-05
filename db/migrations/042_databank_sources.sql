-- 042 — the databank's 53 upstream licenses become rows, not a JSON file
--
-- T2.1 (P2.1). v1 kept its license registry in src/api/data/licenses.json and
-- enforced nothing with it. Porting it into `source` puts every upstream's
-- SPDX (or honest non-SPDX string: 'verify-required', 'varies',
-- 'fair-use-headlines') and commercial_use boolean where the serving layer's
-- WHERE clause can reach them — T2.5 builds that clause, and its test is that
-- a commercial-tier query can never return a non-commercial row.
--
-- Quarantine-by-default: only a registry entry that says commercial_use=true
-- OUTRIGHT gets true here. 'varies', 'unknown', and every verify_required
-- entry lands false until Zaid reads or contacts the source — flipping one is
-- a human decision recorded in DECISIONS.md, never an ETL side effect.
--
-- ON CONFLICT DO NOTHING: 'ioda' already exists (Tier 1 connectivity), and
-- the port must not overwrite what Tier 1 already governs. rss_palinfo /
-- rss_qudsn are Tier 1's live pollers of outlets that also appear here under
-- their databank keys ('palinfo'): same upstream, different acquisition path;
-- both rows carry the same fair-use non-commercial terms, so the license
-- filter treats them identically wherever the join lands.
--
-- Datasets are NOT seeded here. The audit (ops/t2-category-audit.json) found
-- nine categories mixing licenses in one file, so datasets are per
-- (category, source) and are created from the reviewed mapping specs in
-- db/mappings/ by the T2.3 loader — the spec is the reviewable artifact.

INSERT INTO source (key, name, kind, license_spdx, commercial_use,
                    attribution_text, authority_rank, active)
SELECT v.key, v.name, v.kind::source_kind, v.spdx, v.commercial,
       v.attribution, v.rank, true
FROM (VALUES
  ('addameer', 'Addameer Prisoner Support and Human Rights Association', 'file', 'verify-required', false, 'Data: Addameer Prisoner Support and Human Rights Association (addameer.ps).', 3),
  ('al_jazeera_palestine_rss', 'Al Jazeera Palestine', 'rss', 'copyright-fair-use', false, 'News: Al Jazeera Palestine (aljazeera.com). All rights reserved.', 2),
  ('al_jazeera_rss', 'Al Jazeera (RSS headlines)', 'rss', 'copyright-fair-use', false, 'Headlines: Al Jazeera (aljazeera.com). All rights reserved.', 2),
  ('amnesty', 'Amnesty International', 'rss', 'fair-use-headlines', false, 'Headlines: Amnesty International (links to original).', 3),
  ('anadolu', 'Anadolu Agency', 'rss', 'fair-use-headlines', false, 'Headlines: Anadolu Agency (links to original).', 2),
  ('bbc', 'BBC Middle East', 'rss', 'fair-use-headlines', false, 'Headlines: BBC Middle East (links to original).', 2),
  ('btselem', 'B''Tselem', 'file', 'CC-BY-NC-4.0', false, 'Data: B''Tselem (btselem.org), licensed CC-BY-NC 4.0.', 3),
  ('electronic_intifada_rss', 'The Electronic Intifada', 'rss', 'copyright-fair-use', false, 'News: The Electronic Intifada (electronicintifada.net).', 2),
  ('gaza_moh', 'Gaza Ministry of Health', 'file', 'public-record', false, 'Data: Gaza Ministry of Health daily bulletins.', 4),
  ('goodshepherd', 'Good Shepherd Collective', 'file', 'verify-required', false, 'Data: Good Shepherd Collective (goodshepherdcollective.org).', 2),
  ('haaretz_rss', 'Haaretz', 'rss', 'copyright-fair-use', false, 'Headlines: Haaretz (haaretz.com). All rights reserved.', 2),
  ('hamoked', 'HaMoked', 'file', 'verify-required', false, 'Detention figures: HaMoked, sourced from IPS.', 3),
  ('hdx', 'Humanitarian Data Exchange', 'api', 'varies', false, 'Data: Humanitarian Data Exchange (data.humdata.org). License varies by dataset.', 3),
  ('historical_archives', 'Historical Palestine archives (1948–2000)', 'file', 'varies', false, 'Historical data compiled from public archives and academic sources.', 2),
  ('hrw', 'Human Rights Watch', 'rss', 'fair-use-headlines', false, 'Headlines: Human Rights Watch (links to original).', 3),
  ('idmc', 'IDMC', 'api', 'CC-BY-IGO', true, 'Displacement events: IDMC (idmc.ch) via HDX, CC-BY-IGO.', 4),
  ('imemc', 'IMEMC News', 'rss', 'fair-use-headlines', false, 'Headlines: IMEMC News (links to original).', 2),
  ('imf', 'IMF DataMapper', 'api', 'CC-BY-4.0', true, 'Economic indicators: IMF DataMapper.', 4),
  ('ioda', 'IODA — Internet Outage Detection & Analysis', 'api', 'free-with-attribution', false, 'Internet outage events: IODA, Internet Intelligence Lab, Georgia Tech.', 3),
  ('memo', 'Middle East Monitor', 'rss', 'fair-use-headlines', false, 'Headlines: Middle East Monitor (links to original).', 2),
  ('middle_east_eye_rss', 'Middle East Eye', 'rss', 'copyright-fair-use', false, 'News: Middle East Eye (middleeasteye.net).', 2),
  ('mondoweiss_rss', 'Mondoweiss', 'rss', 'copyright-fair-use', false, 'News: Mondoweiss (mondoweiss.net).', 2),
  ('ocha', 'UN OCHA oPt', 'api', 'CC-BY-IGO-3.0', true, 'Data: UN OCHA oPt (ochaopt.org), licensed CC-BY 3.0 IGO.', 4),
  ('ocha_casualties', 'UN OCHA oPt — Data on Casualties', 'file', 'verify-required', false, 'Palestinian fatalities: UN OCHA oPt, sourced from B''Tselem.', 4),
  ('ocha_demolitions', 'UN OCHA oPt — Data on Demolitions', 'file', 'verify-required', false, 'Demolitions: UN OCHA oPt.', 4),
  ('ooni', 'OONI', 'api', 'free-with-attribution', false, 'Censorship measurements: OONI (ooni.org), CC-BY-SA.', 3),
  ('palinfo', 'Palestinian Information Center', 'rss', 'fair-use-headlines', false, 'Headlines: Palestinian Information Center (links to original).', 2),
  ('palopenmaps', 'Palestine Open Maps', 'file', 'verify-required', false, 'Historical localities and census data: Palestine Open Maps (palopenmaps.org), with Abu Sitta / Zochrot / PalestineRemembered.', 2),
  ('pcbs', 'Palestinian Central Bureau of Statistics', 'file', 'public-statistics', false, 'Data: Palestinian Central Bureau of Statistics (pcbs.gov.ps).', 4),
  ('pcbs_direct', 'Palestinian Central Bureau of Statistics (PCBS)', 'file', 'verify-required', false, 'Official statistics: PCBS (pcbs.gov.ps).', 4),
  ('peace_now', 'Peace Now — Settlement Watch', 'file', 'verify-required', false, 'Settlement data: Peace Now (Settlement Watch).', 3),
  ('reliefweb', 'ReliefWeb', 'api', 'metadata-free-with-attribution', true, 'Report metadata: ReliefWeb (reliefweb.int), OCHA.', 3),
  ('reuters_rss', 'Reuters (RSS headlines)', 'rss', 'copyright-fair-use', false, 'Headlines: Reuters (reuters.com). All rights reserved.', 2),
  ('tech4palestine', 'Tech4Palestine', 'api', 'CC-BY-4.0', true, 'Data: Tech4Palestine (data.techforpalestine.org), licensed CC-BY-4.0.', 2),
  ('tech4palestine_telegram', 'Tech4Palestine Telegram Channels', 'api', 'fair-use-attribution', false, 'Alert signals derived from Telegram channels monitored by Tech4Palestine.', 2),
  ('times_of_israel', 'Times of Israel', 'rss', 'fair-use-headlines', false, 'Headlines: Times of Israel (links to original).', 2),
  ('ucdp', 'UCDP Georeferenced Event Dataset', 'api', 'CC-BY-IGO', true, 'Conflict events: UCDP GED, Uppsala University.', 4),
  ('un_news_rss', 'UN News', 'rss', 'UN-attribution', false, 'News: UN News (news.un.org).', 4),
  ('unesco', 'UNESCO World Heritage', 'api', 'CC-BY-SA-3.0-IGO', true, 'Data: UNESCO (whc.unesco.org), licensed CC-BY-SA 3.0 IGO.', 4),
  ('unfts', 'UN OCHA Financial Tracking Service', 'api', 'CC-BY-IGO-3.0', true, 'Funding flows: UN OCHA Financial Tracking Service (fts.unocha.org), licensed CC-BY-IGO-3.0.', 4),
  ('unhcr', 'UNHCR Operational Data Portal', 'api', 'CC-BY-4.0', true, 'Data: UNHCR Operational Data Portal (unhcr.org), licensed CC-BY-4.0.', 4),
  ('unosat', 'UNOSAT (UNITAR)', 'file', 'CC-BY-SA', true, 'Satellite damage assessments: UNOSAT (UNITAR) via HDX (CC-BY-SA).', 4),
  ('unrwa', 'UNRWA', 'file', 'UN-attribution', false, 'Data: UNRWA (unrwa.org).', 4),
  ('unrwa_aid_trucks', 'UNRWA Gaza Supply and Logistics dashboard', 'api', 'CC-BY', true, 'Gaza aid truck data: UNRWA via HDX (CC-BY).', 2),
  ('wafa_rss', 'WAFA (Palestinian News & Info Agency)', 'rss', 'copyright-fair-use', false, 'News: WAFA (english.wafa.ps).', 2),
  ('wfp', 'WFP Food Prices', 'api', 'CC-BY-IGO', true, 'Food prices: World Food Programme (WFP) via HDX (CC-BY-IGO).', 4),
  ('who', 'WHO Global Health Observatory', 'api', 'CC-BY-NC-SA-3.0-IGO', false, 'Data: WHO Global Health Observatory, licensed CC-BY-NC-SA 3.0 IGO.', 4),
  ('who_ssa', 'WHO SSA', 'api', 'CC-BY-IGO', true, 'Attacks on health care: WHO SSA via HDX (CC-BY-IGO).', 4),
  ('worldbank', 'World Bank Open Data', 'api', 'CC-BY-4.0', true, 'Data: The World Bank (data.worldbank.org), licensed CC-BY-4.0.', 4),
  ('zochrot', 'Zochrot', 'file', 'verify-required', false, 'Data: Zochrot (zochrot.org). License unverified — attribution, no redistribution beyond fair use until confirmed.', 3),
  ('atlas_of_palestine', 'Atlas of Palestine (Salman Abu Sitta)', 'file', 'verify-required', false, 'Data: Atlas of Palestine, Salman Abu Sitta. License unverified.', 3),
  ('palestine_remembered', 'Palestine Remembered', 'file', 'verify-required', false, 'Data: PalestineRemembered.com. License unverified.', 2),
  ('wikidata', 'Wikidata', 'api', 'CC0-1.0', true, 'Data: Wikidata (wikidata.org), CC0 1.0.', 2)
) AS v(key, name, kind, spdx, commercial, attribution, rank)
ON CONFLICT (key) DO NOTHING;

-- The [ZAID] verify-required list, machine-readable for the digest:
-- addameer, al_jazeera_palestine_rss, al_jazeera_rss, btselem, electronic_intifada_rss, gaza_moh, goodshepherd, haaretz_rss, hamoked, hdx, historical_archives, middle_east_eye_rss, mondoweiss_rss, ocha_casualties, ocha_demolitions, palopenmaps, pcbs, pcbs_direct, peace_now, reuters_rss, tech4palestine_telegram, un_news_rss, unrwa, wafa_rss
