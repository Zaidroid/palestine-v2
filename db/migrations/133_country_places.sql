-- 133 — the countries that host Palestinian refugees and asylum seekers, as
-- places, and UNHCR's rows placed on them (2026-10-19).
--
-- db/reference/countries.yaml is the reviewed table (UNHCR's ISO3 and English
-- name, the Arabic name, the capital's coordinates from the World Bank's
-- country API as the point); this file is generated from it. The State of
-- Palestine row is not a host country: those rows keep their honest NULL place
-- (people residing in Palestine), as ingest/databank.py already does.
--
-- The data fix places the 45,197 UNHCR rows by their own ISO3 and notes in
-- attrs that the place was NULL before (rollback: set place_id back to NULL
-- where attrs ? 'place_fix_133'). ingest/databank.py places new rows the same
-- way from tonight.

BEGIN;

INSERT INTO place (kind, name_en, name_ar, geom, source_refs, confidence, attrs, servable)
SELECT 'country', v.name_en, v.name_ar,
       ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326),      -- centroid is a generated column
       v.source_refs, 1.0, v.attrs, true
FROM (VALUES
  ('Albania', 'ألبانيا', 19.8172, 41.3317, '{"source": "unhcr_hdx", "iso3": "ALB", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ALB", "point_is": "capital", "asylum_country_name": "Albania"}'::jsonb),
  ('United Arab Emirates', 'الإمارات العربية المتحدة', 54.3705, 24.4764, '{"source": "unhcr_hdx", "iso3": "ARE", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ARE", "point_is": "capital", "asylum_country_name": "United Arab Emirates"}'::jsonb),
  ('Argentina', 'الأرجنتين', -58.4173, -34.6118, '{"source": "unhcr_hdx", "iso3": "ARG", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ARG", "point_is": "capital", "asylum_country_name": "Argentina"}'::jsonb),
  ('Armenia', 'أرمينيا', 44.509, 40.1596, '{"source": "unhcr_hdx", "iso3": "ARM", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ARM", "point_is": "capital", "asylum_country_name": "Armenia"}'::jsonb),
  ('Australia', 'أستراليا', 149.129, -35.282, '{"source": "unhcr_hdx", "iso3": "AUS", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "AUS", "point_is": "capital", "asylum_country_name": "Australia"}'::jsonb),
  ('Azerbaijan', 'أذربيجان', 49.8932, 40.3834, '{"source": "unhcr_hdx", "iso3": "AZE", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "AZE", "point_is": "capital", "asylum_country_name": "Azerbaijan"}'::jsonb),
  ('Belgium', 'بلجيكا', 4.36761, 50.8371, '{"source": "unhcr_hdx", "iso3": "BEL", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "BEL", "point_is": "capital", "asylum_country_name": "Belgium"}'::jsonb),
  ('Benin', 'بنين', 2.6323, 6.4779, '{"source": "unhcr_hdx", "iso3": "BEN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "BEN", "point_is": "capital", "asylum_country_name": "Benin"}'::jsonb),
  ('Bangladesh', 'بنغلاديش', 90.4113, 23.7055, '{"source": "unhcr_hdx", "iso3": "BGD", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "BGD", "point_is": "capital", "asylum_country_name": "Bangladesh"}'::jsonb),
  ('Bulgaria', 'بلغاريا', 23.3238, 42.7105, '{"source": "unhcr_hdx", "iso3": "BGR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "BGR", "point_is": "capital", "asylum_country_name": "Bulgaria"}'::jsonb),
  ('Bahrain', 'البحرين', 50.5354, 26.1921, '{"source": "unhcr_hdx", "iso3": "BHR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "BHR", "point_is": "capital", "asylum_country_name": "Bahrain"}'::jsonb),
  ('Bosnia and Herzegovina', 'البوسنة والهرسك', 18.4214, 43.8607, '{"source": "unhcr_hdx", "iso3": "BIH", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "BIH", "point_is": "capital", "asylum_country_name": "Bosnia and Herzegovina"}'::jsonb),
  ('Belarus', 'بيلاروسيا', 27.5766, 53.9678, '{"source": "unhcr_hdx", "iso3": "BLR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "BLR", "point_is": "capital", "asylum_country_name": "Belarus"}'::jsonb),
  ('Bolivia (Plurinational State of)', 'بوليفيا', -66.1936, -13.9908, '{"source": "unhcr_hdx", "iso3": "BOL", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "BOL", "point_is": "capital", "asylum_country_name": "Bolivia (Plurinational State of)"}'::jsonb),
  ('Brazil', 'البرازيل', -47.9292, -15.7801, '{"source": "unhcr_hdx", "iso3": "BRA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "BRA", "point_is": "capital", "asylum_country_name": "Brazil"}'::jsonb),
  ('Canada', 'كندا', -75.6919, 45.4215, '{"source": "unhcr_hdx", "iso3": "CAN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "CAN", "point_is": "capital", "asylum_country_name": "Canada"}'::jsonb),
  ('Switzerland', 'سويسرا', 7.44821, 46.948, '{"source": "unhcr_hdx", "iso3": "CHE", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "CHE", "point_is": "capital", "asylum_country_name": "Switzerland"}'::jsonb),
  ('Chile', 'تشيلي', -70.6475, -33.475, '{"source": "unhcr_hdx", "iso3": "CHL", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "CHL", "point_is": "capital", "asylum_country_name": "Chile"}'::jsonb),
  ('China', 'الصين', 116.286, 40.0495, '{"source": "unhcr_hdx", "iso3": "CHN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "CHN", "point_is": "capital", "asylum_country_name": "China"}'::jsonb),
  ('Côte d''Ivoire', 'كوت ديفوار', -4.0305, 5.332, '{"source": "unhcr_hdx", "iso3": "CIV", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "CIV", "point_is": "capital", "asylum_country_name": "Côte d''Ivoire"}'::jsonb),
  ('Democratic Republic of the Congo', 'جمهورية الكونغو الديمقراطية', 15.3222, -4.325, '{"source": "unhcr_hdx", "iso3": "COD", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "COD", "point_is": "capital", "asylum_country_name": "Democratic Republic of the Congo"}'::jsonb),
  ('Colombia', 'كولومبيا', -74.082, 4.60987, '{"source": "unhcr_hdx", "iso3": "COL", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "COL", "point_is": "capital", "asylum_country_name": "Colombia"}'::jsonb),
  ('Costa Rica', 'كوستاريكا', -84.0089, 9.63701, '{"source": "unhcr_hdx", "iso3": "CRI", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "CRI", "point_is": "capital", "asylum_country_name": "Costa Rica"}'::jsonb),
  ('Cuba', 'كوبا', -82.3667, 23.1333, '{"source": "unhcr_hdx", "iso3": "CUB", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "CUB", "point_is": "capital", "asylum_country_name": "Cuba"}'::jsonb),
  ('Cyprus', 'قبرص', 33.3736, 35.1676, '{"source": "unhcr_hdx", "iso3": "CYP", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "CYP", "point_is": "capital", "asylum_country_name": "Cyprus"}'::jsonb),
  ('Czechia', 'التشيك', 14.4205, 50.0878, '{"source": "unhcr_hdx", "iso3": "CZE", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "CZE", "point_is": "capital", "asylum_country_name": "Czechia"}'::jsonb),
  ('Germany', 'ألمانيا', 13.4115, 52.5235, '{"source": "unhcr_hdx", "iso3": "DEU", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "DEU", "point_is": "capital", "asylum_country_name": "Germany"}'::jsonb),
  ('Djibouti', 'جيبوتي', 43.1425, 11.5806, '{"source": "unhcr_hdx", "iso3": "DJI", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "DJI", "point_is": "capital", "asylum_country_name": "Djibouti"}'::jsonb),
  ('Denmark', 'الدنمارك', 12.5681, 55.6763, '{"source": "unhcr_hdx", "iso3": "DNK", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "DNK", "point_is": "capital", "asylum_country_name": "Denmark"}'::jsonb),
  ('Algeria', 'الجزائر', 3.05097, 36.7397, '{"source": "unhcr_hdx", "iso3": "DZA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "DZA", "point_is": "capital", "asylum_country_name": "Algeria"}'::jsonb),
  ('Ecuador', 'الإكوادور', -78.5243, -0.229498, '{"source": "unhcr_hdx", "iso3": "ECU", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ECU", "point_is": "capital", "asylum_country_name": "Ecuador"}'::jsonb),
  ('Egypt', 'مصر', 31.2461, 30.0982, '{"source": "unhcr_hdx", "iso3": "EGY", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "EGY", "point_is": "capital", "asylum_country_name": "Egypt"}'::jsonb),
  ('Spain', 'إسبانيا', -3.70327, 40.4167, '{"source": "unhcr_hdx", "iso3": "ESP", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ESP", "point_is": "capital", "asylum_country_name": "Spain"}'::jsonb),
  ('Estonia', 'إستونيا', 24.7586, 59.4392, '{"source": "unhcr_hdx", "iso3": "EST", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "EST", "point_is": "capital", "asylum_country_name": "Estonia"}'::jsonb),
  ('Ethiopia', 'إثيوبيا', 38.7468, 9.02274, '{"source": "unhcr_hdx", "iso3": "ETH", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ETH", "point_is": "capital", "asylum_country_name": "Ethiopia"}'::jsonb),
  ('Finland', 'فنلندا', 24.9525, 60.1608, '{"source": "unhcr_hdx", "iso3": "FIN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "FIN", "point_is": "capital", "asylum_country_name": "Finland"}'::jsonb),
  ('France', 'فرنسا', 2.35097, 48.8566, '{"source": "unhcr_hdx", "iso3": "FRA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "FRA", "point_is": "capital", "asylum_country_name": "France"}'::jsonb),
  ('United Kingdom of Great Britain and Northern Ireland', 'المملكة المتحدة', -0.126236, 51.5002, '{"source": "unhcr_hdx", "iso3": "GBR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "GBR", "point_is": "capital", "asylum_country_name": "United Kingdom of Great Britain and Northern Ireland"}'::jsonb),
  ('Georgia', 'جورجيا', 44.793, 41.71, '{"source": "unhcr_hdx", "iso3": "GEO", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "GEO", "point_is": "capital", "asylum_country_name": "Georgia"}'::jsonb),
  ('Ghana', 'غانا', -0.20795, 5.57045, '{"source": "unhcr_hdx", "iso3": "GHA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "GHA", "point_is": "capital", "asylum_country_name": "Ghana"}'::jsonb),
  ('Greece', 'اليونان', 23.7166, 37.9792, '{"source": "unhcr_hdx", "iso3": "GRC", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "GRC", "point_is": "capital", "asylum_country_name": "Greece"}'::jsonb),
  ('China, Hong Kong Special Administrative Region', 'هونغ كونغ', 114.109, 22.3964, '{"source": "unhcr_hdx", "iso3": "HKG", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "HKG", "point_is": "capital", "asylum_country_name": "China, Hong Kong Special Administrative Region"}'::jsonb),
  ('Croatia', 'كرواتيا', 15.9614, 45.8069, '{"source": "unhcr_hdx", "iso3": "HRV", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "HRV", "point_is": "capital", "asylum_country_name": "Croatia"}'::jsonb),
  ('Hungary', 'المجر', 19.0408, 47.4984, '{"source": "unhcr_hdx", "iso3": "HUN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "HUN", "point_is": "capital", "asylum_country_name": "Hungary"}'::jsonb),
  ('Indonesia', 'إندونيسيا', 106.83, -6.19752, '{"source": "unhcr_hdx", "iso3": "IDN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "IDN", "point_is": "capital", "asylum_country_name": "Indonesia"}'::jsonb),
  ('India', 'الهند', 77.225, 28.6353, '{"source": "unhcr_hdx", "iso3": "IND", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "IND", "point_is": "capital", "asylum_country_name": "India"}'::jsonb),
  ('Ireland', 'أيرلندا', -6.26749, 53.3441, '{"source": "unhcr_hdx", "iso3": "IRL", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "IRL", "point_is": "capital", "asylum_country_name": "Ireland"}'::jsonb),
  ('Iraq', 'العراق', 44.394, 33.3302, '{"source": "unhcr_hdx", "iso3": "IRQ", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "IRQ", "point_is": "capital", "asylum_country_name": "Iraq"}'::jsonb),
  ('Iceland', 'آيسلندا', -21.8952, 64.1353, '{"source": "unhcr_hdx", "iso3": "ISL", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ISL", "point_is": "capital", "asylum_country_name": "Iceland"}'::jsonb),
  ('Israel', 'إسرائيل', 35.2035, 31.7717, '{"source": "unhcr_hdx", "iso3": "ISR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ISR", "point_is": "capital", "asylum_country_name": "Israel"}'::jsonb),
  ('Italy', 'إيطاليا', 12.4823, 41.8955, '{"source": "unhcr_hdx", "iso3": "ITA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ITA", "point_is": "capital", "asylum_country_name": "Italy"}'::jsonb),
  ('Jordan', 'الأردن', 35.9263, 31.9497, '{"source": "unhcr_hdx", "iso3": "JOR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "JOR", "point_is": "capital", "asylum_country_name": "Jordan"}'::jsonb),
  ('Japan', 'اليابان', 139.77, 35.67, '{"source": "unhcr_hdx", "iso3": "JPN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "JPN", "point_is": "capital", "asylum_country_name": "Japan"}'::jsonb),
  ('Kazakhstan', 'كازاخستان', 71.4382, 51.1879, '{"source": "unhcr_hdx", "iso3": "KAZ", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "KAZ", "point_is": "capital", "asylum_country_name": "Kazakhstan"}'::jsonb),
  ('Kyrgyzstan', 'قيرغيزستان', 74.6057, 42.8851, '{"source": "unhcr_hdx", "iso3": "KGZ", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "KGZ", "point_is": "capital", "asylum_country_name": "Kyrgyzstan"}'::jsonb),
  ('Cambodia', 'كمبوديا', 104.874, 11.5556, '{"source": "unhcr_hdx", "iso3": "KHM", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "KHM", "point_is": "capital", "asylum_country_name": "Cambodia"}'::jsonb),
  ('Republic of Korea', 'كوريا الجنوبية', 126.957, 37.5323, '{"source": "unhcr_hdx", "iso3": "KOR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "KOR", "point_is": "capital", "asylum_country_name": "Republic of Korea"}'::jsonb),
  ('Kuwait', 'الكويت', 47.9824, 29.3721, '{"source": "unhcr_hdx", "iso3": "KWT", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "KWT", "point_is": "capital", "asylum_country_name": "Kuwait"}'::jsonb),
  ('Lebanon', 'لبنان', 35.5134, 33.8872, '{"source": "unhcr_hdx", "iso3": "LBN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "LBN", "point_is": "capital", "asylum_country_name": "Lebanon"}'::jsonb),
  ('Liberia', 'ليبيريا', -10.7957, 6.30039, '{"source": "unhcr_hdx", "iso3": "LBR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "LBR", "point_is": "capital", "asylum_country_name": "Liberia"}'::jsonb),
  ('Libya', 'ليبيا', 13.1072, 32.8578, '{"source": "unhcr_hdx", "iso3": "LBY", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "LBY", "point_is": "capital", "asylum_country_name": "Libya"}'::jsonb),
  ('Liechtenstein', 'ليختنشتاين', 9.52148, 47.1411, '{"source": "unhcr_hdx", "iso3": "LIE", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "LIE", "point_is": "capital", "asylum_country_name": "Liechtenstein"}'::jsonb),
  ('Sri Lanka', 'سريلانكا', 79.8528, 6.92148, '{"source": "unhcr_hdx", "iso3": "LKA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "LKA", "point_is": "capital", "asylum_country_name": "Sri Lanka"}'::jsonb),
  ('Lithuania', 'ليتوانيا', 25.2799, 54.6896, '{"source": "unhcr_hdx", "iso3": "LTU", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "LTU", "point_is": "capital", "asylum_country_name": "Lithuania"}'::jsonb),
  ('Luxembourg', 'لوكسمبورغ', 6.1296, 49.61, '{"source": "unhcr_hdx", "iso3": "LUX", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "LUX", "point_is": "capital", "asylum_country_name": "Luxembourg"}'::jsonb),
  ('Latvia', 'لاتفيا', 24.1048, 56.9465, '{"source": "unhcr_hdx", "iso3": "LVA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "LVA", "point_is": "capital", "asylum_country_name": "Latvia"}'::jsonb),
  ('Morocco', 'المغرب', -6.8704, 33.9905, '{"source": "unhcr_hdx", "iso3": "MAR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "MAR", "point_is": "capital", "asylum_country_name": "Morocco"}'::jsonb),
  ('Republic of Moldova', 'مولدوفا', 28.8497, 47.0167, '{"source": "unhcr_hdx", "iso3": "MDA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "MDA", "point_is": "capital", "asylum_country_name": "Republic of Moldova"}'::jsonb),
  ('Madagascar', 'مدغشقر', 45.7167, -20.4667, '{"source": "unhcr_hdx", "iso3": "MDG", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "MDG", "point_is": "capital", "asylum_country_name": "Madagascar"}'::jsonb),
  ('Mexico', 'المكسيك', -99.1276, 19.427, '{"source": "unhcr_hdx", "iso3": "MEX", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "MEX", "point_is": "capital", "asylum_country_name": "Mexico"}'::jsonb),
  ('North Macedonia', 'مقدونيا الشمالية', 21.4361, 42.0024, '{"source": "unhcr_hdx", "iso3": "MKD", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "MKD", "point_is": "capital", "asylum_country_name": "North Macedonia"}'::jsonb),
  ('Malta', 'مالطا', 14.5189, 35.9042, '{"source": "unhcr_hdx", "iso3": "MLT", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "MLT", "point_is": "capital", "asylum_country_name": "Malta"}'::jsonb),
  ('Montenegro', 'الجبل الأسود', 19.2595, 42.4602, '{"source": "unhcr_hdx", "iso3": "MNE", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "MNE", "point_is": "capital", "asylum_country_name": "Montenegro"}'::jsonb),
  ('Mozambique', 'موزمبيق', 32.5713, -25.9664, '{"source": "unhcr_hdx", "iso3": "MOZ", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "MOZ", "point_is": "capital", "asylum_country_name": "Mozambique"}'::jsonb),
  ('Mauritania', 'موريتانيا', -15.9824, 18.2367, '{"source": "unhcr_hdx", "iso3": "MRT", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "MRT", "point_is": "capital", "asylum_country_name": "Mauritania"}'::jsonb),
  ('Malaysia', 'ماليزيا', 101.684, 3.12433, '{"source": "unhcr_hdx", "iso3": "MYS", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "MYS", "point_is": "capital", "asylum_country_name": "Malaysia"}'::jsonb),
  ('Niger', 'النيجر', 2.1073, 13.514, '{"source": "unhcr_hdx", "iso3": "NER", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "NER", "point_is": "capital", "asylum_country_name": "Niger"}'::jsonb),
  ('Nigeria', 'نيجيريا', 7.48906, 9.05804, '{"source": "unhcr_hdx", "iso3": "NGA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "NGA", "point_is": "capital", "asylum_country_name": "Nigeria"}'::jsonb),
  ('Netherlands (Kingdom of the)', 'هولندا', 4.89095, 52.3738, '{"source": "unhcr_hdx", "iso3": "NLD", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "NLD", "point_is": "capital", "asylum_country_name": "Netherlands (Kingdom of the)"}'::jsonb),
  ('Norway', 'النرويج', 10.7387, 59.9138, '{"source": "unhcr_hdx", "iso3": "NOR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "NOR", "point_is": "capital", "asylum_country_name": "Norway"}'::jsonb),
  ('Naoero', 'ناورو', 166.920867, -0.5477, '{"source": "unhcr_hdx", "iso3": "NRU", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "NRU", "point_is": "capital", "asylum_country_name": "Naoero"}'::jsonb),
  ('New Zealand', 'نيوزيلندا', 174.776, -41.2865, '{"source": "unhcr_hdx", "iso3": "NZL", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "NZL", "point_is": "capital", "asylum_country_name": "New Zealand"}'::jsonb),
  ('Pakistan', 'باكستان', 72.8, 30.5167, '{"source": "unhcr_hdx", "iso3": "PAK", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "PAK", "point_is": "capital", "asylum_country_name": "Pakistan"}'::jsonb),
  ('Peru', 'بيرو', -77.0465, -12.0931, '{"source": "unhcr_hdx", "iso3": "PER", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "PER", "point_is": "capital", "asylum_country_name": "Peru"}'::jsonb),
  ('Philippines', 'الفلبين', 121.035, 14.5515, '{"source": "unhcr_hdx", "iso3": "PHL", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "PHL", "point_is": "capital", "asylum_country_name": "Philippines"}'::jsonb),
  ('Poland', 'بولندا', 21.02, 52.26, '{"source": "unhcr_hdx", "iso3": "POL", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "POL", "point_is": "capital", "asylum_country_name": "Poland"}'::jsonb),
  ('Portugal', 'البرتغال', -9.13552, 38.7072, '{"source": "unhcr_hdx", "iso3": "PRT", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "PRT", "point_is": "capital", "asylum_country_name": "Portugal"}'::jsonb),
  ('Paraguay', 'باراغواي', -57.6362, -25.3005, '{"source": "unhcr_hdx", "iso3": "PRY", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "PRY", "point_is": "capital", "asylum_country_name": "Paraguay"}'::jsonb),
  ('Qatar', 'قطر', 51.5082, 25.2948, '{"source": "unhcr_hdx", "iso3": "QAT", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "QAT", "point_is": "capital", "asylum_country_name": "Qatar"}'::jsonb),
  ('Romania', 'رومانيا', 26.0979, 44.4479, '{"source": "unhcr_hdx", "iso3": "ROU", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ROU", "point_is": "capital", "asylum_country_name": "Romania"}'::jsonb),
  ('Russian Federation', 'روسيا', 37.6176, 55.7558, '{"source": "unhcr_hdx", "iso3": "RUS", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "RUS", "point_is": "capital", "asylum_country_name": "Russian Federation"}'::jsonb),
  ('Saudi Arabia', 'السعودية', 46.6977, 24.6748, '{"source": "unhcr_hdx", "iso3": "SAU", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "SAU", "point_is": "capital", "asylum_country_name": "Saudi Arabia"}'::jsonb),
  ('Sudan', 'السودان', 32.5363, 15.5932, '{"source": "unhcr_hdx", "iso3": "SDN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "SDN", "point_is": "capital", "asylum_country_name": "Sudan"}'::jsonb),
  ('Senegal', 'السنغال', -17.4734, 14.7247, '{"source": "unhcr_hdx", "iso3": "SEN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "SEN", "point_is": "capital", "asylum_country_name": "Senegal"}'::jsonb),
  ('Somalia', 'الصومال', 45.3254, 2.07515, '{"source": "unhcr_hdx", "iso3": "SOM", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "SOM", "point_is": "capital", "asylum_country_name": "Somalia"}'::jsonb),
  ('Serbia', 'صربيا', 20.4656, 44.8024, '{"source": "unhcr_hdx", "iso3": "SRB", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "SRB", "point_is": "capital", "asylum_country_name": "Serbia"}'::jsonb),
  ('Slovakia', 'سلوفاكيا', 17.1073, 48.1484, '{"source": "unhcr_hdx", "iso3": "SVK", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "SVK", "point_is": "capital", "asylum_country_name": "Slovakia"}'::jsonb),
  ('Slovenia', 'سلوفينيا', 14.5044, 46.0546, '{"source": "unhcr_hdx", "iso3": "SVN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "SVN", "point_is": "capital", "asylum_country_name": "Slovenia"}'::jsonb),
  ('Sweden', 'السويد', 18.0645, 59.3327, '{"source": "unhcr_hdx", "iso3": "SWE", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "SWE", "point_is": "capital", "asylum_country_name": "Sweden"}'::jsonb),
  ('Syrian Arab Republic', 'سوريا', 36.3119, 33.5146, '{"source": "unhcr_hdx", "iso3": "SYR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "SYR", "point_is": "capital", "asylum_country_name": "Syrian Arab Republic"}'::jsonb),
  ('Chad', 'تشاد', 15.0445, 12.1048, '{"source": "unhcr_hdx", "iso3": "TCD", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "TCD", "point_is": "capital", "asylum_country_name": "Chad"}'::jsonb),
  ('Togo', 'توغو', 1.2255, 6.1228, '{"source": "unhcr_hdx", "iso3": "TGO", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "TGO", "point_is": "capital", "asylum_country_name": "Togo"}'::jsonb),
  ('Thailand', 'تايلاند', 100.521, 13.7308, '{"source": "unhcr_hdx", "iso3": "THA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "THA", "point_is": "capital", "asylum_country_name": "Thailand"}'::jsonb),
  ('Tunisia', 'تونس', 10.21, 36.7899, '{"source": "unhcr_hdx", "iso3": "TUN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "TUN", "point_is": "capital", "asylum_country_name": "Tunisia"}'::jsonb),
  ('Türkiye', 'تركيا', 32.3606, 39.7153, '{"source": "unhcr_hdx", "iso3": "TUR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "TUR", "point_is": "capital", "asylum_country_name": "Türkiye"}'::jsonb),
  ('United Republic of Tanzania', 'تنزانيا', 35.7382, -6.17486, '{"source": "unhcr_hdx", "iso3": "TZA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "TZA", "point_is": "capital", "asylum_country_name": "United Republic of Tanzania"}'::jsonb),
  ('Uganda', 'أوغندا', 32.5729, 0.314269, '{"source": "unhcr_hdx", "iso3": "UGA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "UGA", "point_is": "capital", "asylum_country_name": "Uganda"}'::jsonb),
  ('Ukraine', 'أوكرانيا', 30.5038, 50.4536, '{"source": "unhcr_hdx", "iso3": "UKR", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "UKR", "point_is": "capital", "asylum_country_name": "Ukraine"}'::jsonb),
  ('Uruguay', 'الأوروغواي', -56.0675, -34.8941, '{"source": "unhcr_hdx", "iso3": "URY", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "URY", "point_is": "capital", "asylum_country_name": "Uruguay"}'::jsonb),
  ('United States of America', 'الولايات المتحدة الأمريكية', -77.032, 38.8895, '{"source": "unhcr_hdx", "iso3": "USA", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "USA", "point_is": "capital", "asylum_country_name": "United States of America"}'::jsonb),
  ('Uzbekistan', 'أوزبكستان', 69.269, 41.3052, '{"source": "unhcr_hdx", "iso3": "UZB", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "UZB", "point_is": "capital", "asylum_country_name": "Uzbekistan"}'::jsonb),
  ('Venezuela (Bolivarian Republic of)', 'فنزويلا', -69.8371, 9.08165, '{"source": "unhcr_hdx", "iso3": "VEN", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "VEN", "point_is": "capital", "asylum_country_name": "Venezuela (Bolivarian Republic of)"}'::jsonb),
  ('Yemen', 'اليمن', 44.2075, 15.352, '{"source": "unhcr_hdx", "iso3": "YEM", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "YEM", "point_is": "capital", "asylum_country_name": "Yemen"}'::jsonb),
  ('South Africa', 'جنوب أفريقيا', 28.1871, -25.746, '{"source": "unhcr_hdx", "iso3": "ZAF", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ZAF", "point_is": "capital", "asylum_country_name": "South Africa"}'::jsonb),
  ('Zambia', 'زامبيا', 28.2937, -15.3982, '{"source": "unhcr_hdx", "iso3": "ZMB", "point": "capital city, World Bank country API"}'::jsonb, '{"iso3": "ZMB", "point_is": "capital", "asylum_country_name": "Zambia"}'::jsonb)
) AS v(name_en, name_ar, lon, lat, source_refs, attrs)
WHERE NOT EXISTS (SELECT 1 FROM place p WHERE p.kind = 'country' AND p.attrs->>'iso3' = v.attrs->>'iso3');

UPDATE observation o
   SET place_id = p.place_id,
       attrs = o.attrs || jsonb_build_object('place_fix_133', 'country of asylum by ISO3; place was NULL')
  FROM dataset d, place p
 WHERE d.key = 'unhcr_population_hdx' AND o.dataset_id = d.dataset_id
   AND upper_inf(o.sys_period) AND o.place_id IS NULL
   AND p.kind = 'country' AND p.merged_into IS NULL
   AND p.attrs->>'iso3' = o.attrs->>'asylum_country_code'
   AND o.attrs->>'asylum_country_code' <> 'PSE';

COMMIT;
