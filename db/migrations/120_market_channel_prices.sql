-- 120 · Gaza's market prices as the Telegram channel «أسعار السوق - غزة» (@asarsook) posts them
-- 2026-10-14
--
-- The channel (about 5,000 subscribers, November 2024 onward) posts the day's prices in Gaza's
-- markets: lists for the north, Gaza City, the middle area or the south, the Ministry of
-- Agriculture's marketing directorate's lists, chicken by the cut, fish, and the goods missing from
-- the market. The public channel reader holds its posts (data/raw/tg_public/asarsook/);
-- ops/build_market_channel.py reads the lists into data/raw/market_channel/prices.json and
-- db/mappings/price_asarsook.yaml loads them. Beside the Chamber's weekly averages and WFP's monthly
-- prices, never merged with them.
--
-- Terms, as read on 2026-10-14: a public Telegram channel that states no licence and no terms. So
-- the row takes the cautious default of 117 (the Chamber) and Addameer: no-redistribution and
-- commercial_use = false, held for the house and withheld from partners, until Zaid says otherwise.
--
-- Rollback: DELETE FROM dataset WHERE key = 'market_channel_prices' AND NOT EXISTS
--             (SELECT 1 FROM observation o JOIN dataset d USING (dataset_id) WHERE d.key = 'market_channel_prices');
--           DELETE FROM source WHERE key = 'tg_asarsook' AND NOT EXISTS (SELECT 1 FROM dataset d
--             JOIN source s USING (source_id) WHERE s.key = 'tg_asarsook');
--           (with rows loaded, deactivate instead: UPDATE source SET active = false WHERE key = 'tg_asarsook')

INSERT INTO source (key, name, kind, authority_rank, license_spdx, commercial_use, share_alike,
                    attribution_required, attribution_text, redistribution, terms_url, terms_verified_at,
                    terms_evidence, active)
SELECT 'tg_asarsook', 'أسعار السوق - غزة (Telegram channel @asarsook)', 'file', 5,
       'no-license-found', false, false, true,
       'Gaza market prices: the Telegram channel «أسعار السوق - غزة» (@asarsook).',
       'no-redistribution',
       'https://t.me/s/asarsook',
       '2026-10-14T14:00:00Z',
       'Read 2026-10-14: a public Telegram channel; its page states no licence and no terms of use. The cautious default of migrations 117 and 042: held for the house, withheld from partners.',
       true
 WHERE NOT EXISTS (SELECT 1 FROM source WHERE key = 'tg_asarsook');

INSERT INTO dataset (key, name, source_id, v1_category, cadence, active, attrs)
SELECT 'market_channel_prices',
       'Gaza market prices by day, as the Telegram channel «أسعار السوق - غزة» posts them',
       s.source_id, 'food', 'irregular', true,
       jsonb_build_object(
         'publisher_window_from', '2024-11-19',
         'not_a_continuation_of', jsonb_build_array('v1_food_wfp', 'gazacham_prices'),
         'scope_note', 'One list''s price per good, area and day (not an average or a survey): the north, Gaza City, the middle area, the south, or the Strip where a list names no area; the price paid by app as series of their own; the days a list marked a good missing. Not read: exchange rates, adverts, commentary, goods priced by the uqiya or the ratl or in packs of no stated size.')
  FROM source s
 WHERE s.key = 'tg_asarsook'
   AND NOT EXISTS (SELECT 1 FROM dataset WHERE key = 'market_channel_prices');
