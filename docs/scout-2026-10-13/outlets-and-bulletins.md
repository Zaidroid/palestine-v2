# News outlets' archives and periodic bulletins, 2000 to today

A scout's report, returned on 13 October 2026 and kept as it came. It is the work of a research agent, not a
measurement of this store: check a line again before a reader is built on it. Requests were limited to about
eight a site; nothing was signed up for and no key was used.

Scouting is done: 20 of 27 outlets can be read whole now; three are closed to a plain reader (+972, Electronic Intifada, and article pages on IMEMC and Palestine Chronicle), and I found about a dozen bulletins that are hidden time series.

Everything was fetched on 2026-10-13 with the given reader name, at most 8 requests per site. "Chars" means characters of body text inside paragraph tags. Saved files are under the scout's working folder (temporary, not kept) (`robots/`, `robots2/`, `sm/`, `art/`, `p2/`, `pdf/`, `scripts/`).

## Part 1 — outlets

No outlet showed a paywall or login on the sample fetched. No outlet names ClaudeBot, anthropic-ai or GPTBot except Al-Quds, which allows them. The 2024 sample for each outlet is in the notes below the table.

| Outlet | Listing and URL pattern | Earliest | Articles per year (how counted) | Robots for a reader | AI stanza | Full text, no login | Verdict |
|---|---|---|---|---|---|---|---|
| WAFA Arabic (wafa.ps) | Sitemap index `https://www.wafa.ps/sitemap.xml` → 2,327 daily files `…/sitemap.xml?yyyy=Y&mm=M&dd=D`; article `/news/YYYY/M/D/slug` | 24 Dec 2018 (one day only), then from 5 Feb 2020. Days listed per year: 2018: 1, 2020: 214, 2021: 365, 2022: 365, 2023: 365, 2024: 366, 2025: 365, 2026: 286 | About 20–30 thousand (three sampled days: 58, 53, 85 articles) | `Allow: /`, no delay | none | yes | read whole now (2020 onward; earlier not listed) |
| WAFA English (english.wafa.ps) | No robots, no sitemap. Sequential ids `/Pages/Details/{id}`; `/Pages/LastNews?pageNumber=N` is shallow (20 per page; pages 212 and 9000 were empty) | unknown: id 145000 = 12 Jun 2024, id 175868 = 13 Oct 2026; ids 100 and 60000 are "not found" | About 13,200 (30,868 ids in 853 days) | none (404) | none | yes | read whole now by id walk; lowest live id still to find |
| Quds News Network (qudsn.co) | `/all_posts?page=N`, 7,062 pages × 12 ≈ 84,700 posts; `sitemap.xml` holds only the newest 10,000 (16 Dec 2024 onward). Article `post?id=N&slug=…`; the slug is required (id alone gives 404) | 19 Feb 2013 (id 13) | 5,426 in 2025 (sitemap dates); about 6,200 average | Disallows /dashboard, /login, /search; delays only for named SEO bots | none | yes | read whole now |
| PIC Arabic (palinfo.com) | WordPress interface `/wp-json/wp/v2/posts` reports 323,111 posts; the sitemap index lists only about 34,000 (340 files × 100, back to 2022–23). Article `/news/YYYY/MM/DD/{id}/` | unknown (oldest record has a placeholder date of 1900) | 9,047 in 2024 (interface count) | `Disallow:` empty | none | yes | read whole now through the interface |
| PIC English (english.palinfo.com) | Sitemap index: 100 post files × 200 (interface total 19,968), plus 379 `o_post-sitemapN.xml` × 200 ≈ 75,800 old-archive pages at `/o_post/slug/`, plus 19 opinion files | new posts from 28 Jun 2020; old archive dates not in URL | 5,383 in 2024 (interface count) | `Disallow:` empty | none | yes | read whole now |
| Middle East Eye | `sitemap.xml?page=1…36` = 70,942 URLs including French, video and galleries, but frozen: nothing after 18 May 2024. `/rss` gives 20 items with long text (up to 7,720 chars) | 2014 | unknown (no dates in URLs); roughly 7 thousand a year including French and video | Drupal default, no delay | none | yes | read now up to May 2024; after that, feed forward only |
| Mondoweiss | WordPress interface total 35,534; `sitemap.xml` has only 1,235 recent URLs. Article `/YYYY/MM/slug/` | 25 Mar 2006 | 1,156 in 2024 (interface count) | only /wp-admin/ | none | yes | read whole now |
| +972 Magazine | `sitemap_index.xml` lists 11 post files; the first sub-file answered 403 (Cloudflare challenge), so I stopped | unknown | unknown | Disallows /wp-json/, previews, /print/ | none | not verified | no for a plain reader |
| Electronic Intifada | `/sitemap.xml` 403 (known) and `/news` 403 (Cloudflare challenge), so I stopped; `/googlenews.xml` and `/rss.xml` not tested | unknown | unknown | Crawl-delay 10; Drupal default | none | not verified | no for a plain reader |
| IMEMC | Sitemap: 33 post files × 2,000; WordPress interface total 64,192 | 29 May 2003 | 2,706 in 2024 (interface count) | Crawl-delay 20; disallows /page/ and ?paged= | none | not verified: article page answered 429 (challenge) | later (try the interface's content field) |
| Middle East Monitor | `sitemap.xml` → `sitemap-index-1.xml` → `sitemap-1…149.xml`; WordPress interface total 149,208. Article `/YYYYMMDD-slug/` | 11 Jan 2009 | 14,610 in 2024 (interface count) | only /wp-admin/ | none | yes | read whole now |
| Palestine Chronicle | No robots (404). `sitemap_index.xml`: 40 post files × 1,000 in date order; WordPress interface total 39,169 | 19 Sep 2006 in its database | 4,350 in 2024 (interface count) | none | none | not verified: article page answered 429 (challenge) | later |
| Ma'an (maannews.net) | Robots empty, no sitemap. `/news/{id}.html`: 800000 = 22 Sep 2015, 990000 = 18 Jul 2019, 2113000 = 2 Mar 2024, 2170452 = today. Ids jump from about 1.0M to 2.0M | 2015 confirmed; lower bound unknown (500000 gives 404) | About 22,000 (57,452 ids in 31 months) | empty | none | yes | read whole now by id walk |
| Safa | `sitemap.xml` → `/uploads/sitemaps/post-1…42.xml` (10,000 each) ≈ 411,000; `/post/{id}` redirects to the full address | Jun 2009 | About 19,800 average 2023–26 (id difference); 82 a day in Oct 2026 | Disallows /o2cp/, /admin/, /ajax/, /ads/ | none | yes | read whole now |
| Sama News | `/ar/sitemap.xml` → `/ar/sitemap/google/part-1…23-sitemap.xml` (25,000 each, part 1 newest) ≈ 560,000 | Sep 2009 | 19,152 between 3 Feb and 31 Dec 2024 (counted in part 2) | Disallows /ar/samacpxs/ | none | yes | read whole now |
| Felesteen | `sitemap.xml` → `post-1…20.xml` ≈ 190,700 | Apr 2016 | About 14,500 (id difference 2023–26) | same as Safa | none | yes | read whole now |
| Palestine Today | `/ar/sitemap.xml` → 51 post files ≈ 500,600, plus 19 gallery files; ids start at 30001 | Dec 2008 | About 16,700 (id 500000 = 22 Jan 2024 to 545,494 today) | Allow /; disallows admin, ajax, ads, search | none | yes | read whole now |
| Donia Al-Watan | No sitemap. Category pages `/arabic/category/2/{page}.html`: 12,900 pages × 22 ≈ 284,000 items in "Palestinian affairs" alone; page 5000 = 15 May 2019. Article `/arabic/news/YYYY/MM/DD/{id}.html` | unknown (last page not read) | About 15,000 in that category (110,000 items in 7.4 years) | `Allow: /` | none | yes | read whole now (paged) |
| Al-Quds (alquds.com) | `/ar/posts/{id}` with ids up to about 261,900; the sitemap covers only ids 2–91,483 (5 files) plus a 2-day news file. `/llms.txt` lists feeds | unknown | About 26,000 (143 items in 2 days) | Allow /; crawl-delay 1 | **Names GPTBot, ChatGPT-User, OAI-SearchBot, Claude-Web, ClaudeBot, Anthropic-AI, PerplexityBot: `Allow: /`, crawl-delay 2** | yes | read whole now |
| Al-Ayyam | No sitemap. `/ar/Article/{id}`: 260000 = 10 Feb 2015, 400000 = 3 May 2024, 431,262 today; `/ar/PDF` holds the print edition | 2015 confirmed; lower bound unknown (100000 "not found", 1000 gives error 500) | About 12,800 | Disallows /public/ | none | yes | read whole now by id walk |
| Al-Hadath | No sitemap. `/ar/Article/{id}`: 1000 = 24 Jun 2014, 177000 = 14 Mar 2024, 213,737 today | 2014 | About 17,000 (214,000 ids in 12.3 years) | open | none | yes | read whole now |
| Arab48 | `https://www.arab48.com/sitemap/https/sitemapIndex` → `data.arab48.com/sitemap/https/news1…9.xml` ≈ 430,000 | 2002 in bulk (7 entries dated 1999). For pre-2010 items the URL date is a migration date; use lastmod | 16,905 in 2025 (URL dates) | Disallows print and cursor pages | names Google-Extended: Allow | yes | read whole now |
| Ultra Palestine | `sitemap.xml?page=1` and `?page=2` return the same 1,361 URLs (the cache ignores the page number), so the listing is unreliable | 2017 (lastmod) | unknown | Drupal default plus `Disallow: /ar/*` | none | yes | later (needs another listing) |
| Raya | No sitemap. `/news/{id}.html`: 900000 = 8 May 2015, 1180000 = 31 Aug 2024, 1,226,805 today | 2015 confirmed; 600000 and 750000 give 404 | About 22,000 (id difference 2024–26) | Disallows /ajax/ | none | yes | read whole now by id walk |
| Shehab | `sitemap.xml` → `post-1…18.xml` ≈ 170,800 | May 2016 | About 10,800 average Sep 2023–Oct 2026; 83 a day in Oct 2026 | same as Safa | none | yes | read whole now |
| Anadolu Arabic | `/ar/SiteMap/News` holds only the newest 1,000 (8 days); `?page=2` returns the same. An id with the wrong slug gives title and date but no body | no back listing | About 43,000 Arabic items (1,000 in 8.4 days); 31% of slugs name Gaza, Palestine, West Bank, Jerusalem or Israel | Allow /; disallows /api/ | none | yes with the true address | later (capture forward now; back archive needs the true addresses) |
| UN News | `/en/sitemap.xml?page=1…17` = 83,162 URLs, stories as `/en/story/YYYY/MM/{id}`. Topic and region list pages (`/en/tags/gaza`, `*/news/`, `?page=`) are disallowed, so the Palestine topic cannot be listed politely; filter on text instead | not verified (a robots comment says 2001) | 3,636 in 2011; 1,630 for Mar–Dec 2025 (sitemap counts) | as described | none | yes | read whole now through the sitemap |

## Part 2 — institutions

| Institution | What repeats (the hidden series) | Cadence | Years | Format | Licence | Listing URL | Verdict |
|---|---|---|---|---|---|---|---|
| OCHA oPt | Weekly "Reported impact snapshot, Gaza Strip"; weekly "Humanitarian Situation Report"; "West Bank Monthly Snapshot – casualties, property damage and displacement"; Protection of Civilians reports with "so far this year" counts | weekly / monthly; Protection of Civilians was two-weekly and ends 26 Sep 2023 | May 2001 → Oct 2026; about 3,260 items (363 pages × 9); Protection of Civilians about 810 | HTML; snapshots are PDF at `/sites/default/files/Gaza_Reported_Impact_Snapshot_{D}_{Month}_{YYYY}.pdf` | footer links `/page/terms-use` and UN copyright; text not read | `https://www.ochaopt.org/publications?field_publication_type_target_id_1={type}&page=N` (types: 54 Protection of Civilians, 190 situation update, 191 response update, 160 flash, 48 bulletin, 55 snapshots) | read whole now |
| UNRWA | Situation reports #1–#236: cumulative killed and injured, UNRWA staff killed, shelter and health figures | about two-weekly now | Oct 2023 → 7 Oct 2026 | HTML | not read | unrwa.org answered 403; mirror `reliefweb.int/report/occupied-palestinian-territory/unrwa-situation-report-{N}-…` | read now through ReliefWeb |
| WHO oPt | Situation reports, issues 1–72: fatalities, injuries, hospitals functioning out of 36, primary care centres | monthly in 2026 | Oct 2023 → Aug 2026, plus 2014 and 2021 | PDF (159 on one page) | not read | `https://www.emro.who.int/opt/information-resources/emergency-situation-reports.html` | read whole now |
| WFP Palestine | Monthly market dashboard: commodity prices by area (25 kg flour bag and others), household access shares | monthly | 2022 → Aug 2026 (38 PDFs on the current page; three older pages not fetched) | PDF on docs.wfp.org (403 to my reader); mirror on ReliefWeb | not read | `https://www.wfp.org/publications/wfp-palestine-monthly-market-dashboard-0` | read now through ReliefWeb |
| WFP food prices on the Humanitarian Data Exchange | The same prices as rows | monthly | 15 Jan 2007 → 15 Sep 2026 | CSV, 3.4 MB | "Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO)" | `https://data.humdata.org/api/3/action/package_show?id=wfp-food-prices-for-state-of-palestine` | read now |
| Gaza Chamber of Commerce (gazacham.ps, not gazachamber.ps) | **"Gaza Movement of Goods – Weekly Report", weeks 1–111: trucks per week by crossing, private against humanitarian share, cargo mix, price change against pre-war per commodity, its own Gaza price index daily and monthly** | weekly, issued in pairs | to 13 Sep 2026; start not verified (about Aug 2024 by week count) | PDF | "all rights reserved 2023" | `https://gazacham.ps/InformationCenter/Reports?slug=حركة-البضائع-وحالة-الأسواق` (7 pages × 12) | read whole now |
| PCBS press releases | Monthly consumer price release: change by region and by sub-group; also industrial production, producer prices, quarterly accounts | monthly, mid-month | not verified | HTML, PDF, Word | not read | `https://www.pcbs.gov.ps/en/press-releases/`; item `/en/post-details/?postId=N` | read now (through a browser-like reader; plain curl fails on the certificate chain) |
| PCBS "average consumer prices for selected commodities by region" | **One table a month; the site shows only the latest month (Aug 2026) as a pop-up. Older months had their own `statisticsIndicatorsTables.aspx?lang=en&table_id=N` pages, which now show the generic page** | monthly | at least Jul 2023 → Aug 2026 by search-index titles; not verified | HTML pop-up | not read | `https://www.pcbs.gov.ps/en/statistics/?selectedItemId=b763592c-5a61-42a9-babb-12ff5d6f4fea` | later: capture each month as it appears; back months need a web archive (not tested) |
| Palestine Monetary Authority | Daily exchange rates, key indicators, sector statistics, quarterly and annual reports | daily / quarterly | not verified | JavaScript app; a plain reader gets an empty shell | not read | `https://www.pma.ps/sitemap.xml` (373 URLs, including `/currency-exchange-rates`, `/statistics/…-stats`) | later (needs a browser) |
| Palestinian Prisoners' Society | Joint statements and documentation reports with running counts (deaths in custody, arrests) | several a week | ids up to about 18,517; start not verified | HTML | none stated | `https://ppsmo.ps/home/news?pageNumber=N&culture=ar-SA`; `/home/studies/{id}` | read now |
| Commission of Detainees' Affairs | **Daily lists "names of (N) detainees issued administrative detention orders on [date]"**, appeal results, statistical reports section | daily | not verified | HTML | none stated | `https://cda.gov.ps/index.php/ar/ar-prisoner-movement/2017-06-01-06-56-43` (administrative detention); `…/2017-06-01-06-53-33` (statistical reports) | read now |
| Addameer (addameer.ps; addameer.org does not resolve) | **One page a month in one shape: total prisoners, administrative detainees, children, women, Jerusalem, Gaza, life sentences, "unlawful combatants"** | monthly, with gaps (2022: 5 months, 2023: 1, 2024: 3, 2025: 6) | Jan 2011 → Oct 2026, 143 months | HTML | "Addameer, All rights reserved ©2021" | `https://www.addameer.ps/statistics/YYYY/MM` | read whole now |
| DCIP | Child-detention monthly figures | — | — | — | — | **dci-palestine.org now serves gambling pages; the figures page redirects there** | no |
| Wall and Settlement Resistance Commission | Monthly violations report: total attacks by army and settlers, with breakdowns | monthly, half-yearly, annual | not verified | HTML | not read | `cwrc.ps/page-{n}-ar.html` (from a search index only); **its robots.txt says `User-agent: * Disallow: /`, so I did not fetch it** | no directly; read the monthly WAFA republication |
| Peace Now | Settlement Watch data pages (settlement and outpost counts, population, construction, tenders); 1,071 posts on plans and tenders | irregular | posts 2015 → 2026 | HTML with charts | "© 2026 Peace Now" | `https://peacenow.org.il/en/settlements-watch/settlements-data/{population,construction,lands,jerusalem}`; `wp-sitemap-posts-post-1.xml` | read now |
| Yesh Din | Annual data sheets on law enforcement against settlers and soldiers | yearly | 2005 → 2025 | HTML and PDF | not read | `https://www.yesh-din.org/en/reports-data/?refineByType=586` | read now |
| B'Tselem | Fatalities and demolitions database; minors in custody | — | — | JavaScript app at statistics.btselem.org | not read | btselem.org `/statistics` answered 429 (challenge); crawl-delay 10 | no for a plain reader; not verified |
| Al-Haq | Monthly field reports | stopped: 2019 (2), 2020 (2), 2021 (5), 2022 (6) | 2019 → 2022 | HTML | "All Rights Reserved ©2026" | `https://www.alhaq.org/monitoring-documentation/monthly-reports` | later (thin) |
| Al Mezan | — | — | — | — | — | mezan.org timed out and the reader returned 422 | not reached |
| PCHR | **Weekly report "Israeli Human Rights Violations in the oPt": killed, injured, incursions, arrests, demolitions** | weekly, ends 5 Oct 2023 | start not verified; 1,208 posts match "weekly report" out of 11,872 | HTML | not read | `https://pchrgaza.org/sitemap.xml` (12 post files) or `/wp-json/wp/v2/posts`; crawl-delay 3 | read whole now |
| Euro-Med Monitor | — | — | — | — | — | euromedmonitor.org answered 403 at robots | not reached |
| UN Women Palestine | Gender alerts and humanitarian updates with women-and-girls counts | irregular | not verified | HTML and PDF | not read | `https://palestine.unwomen.org/en/digital-library/publications` (20 per page) | later |
| UNFPA Palestine | Situation report #21; "GBV trends analysis" each quarter | quarterly now | not verified | HTML summary and PDF | not read | `https://palestine.unfpa.org/en/publications` | later |
| UNICEF State of Palestine | Humanitarian situation reports 1–48: children in need, children killed, malnutrition admissions, funding | monthly since mid-2024; weekly in late 2023 | Mar 2021 → 30 Jun 2026, 71 documents on one page | PDF | not read | `https://www.unicef.org/appeals/state-of-palestine/situation-reports` | read whole now |
| Clusters (WASH, Health, Education, Protection, Food Security) | Reports, maps, assessments; Power BI dashboards (WASH 3, Education 4); Gaza Health Cluster Bulletin; unified health dashboard | varies | not verified | HTML lists, dashboards | not read | `https://response.reliefweb.int/palestine/{water-sanitation-and-hygiene,health,education,protection,food-security}/reports`; fscluster.org answered 403 | later (no number verified) |
| IPC Gaza | Special snapshots: phase by area, people in Phase 3 and above | 2–4 a year | Dec 2025 and Jul 2026 seen; earlier not verified | PDF plus HTML summary | not read | ipcinfo.org answered 403; mirror on ReliefWeb | read now through ReliefWeb |
| Ministry of Health, Ramallah | **Health Annual Report 2008–2025 in Arabic and English with table annexes**; "Israeli aggression" annual report 2021–2023 | yearly | 2008 → 2025 | PDF, 58 downloads | not read | `https://site.moh.ps/index/Books/BookType/2/Language/ar` | later (listing verified; the PDF text did not come through the reader) |
| Ministry of Health, Gaza | Annual reports | yearly | 2016 → 2023 | PDF | not read | `https://www.moh.gov.ps/portal/repyears/` | later |
| Palestinian Water Authority | Damage statements, facts and figures, achievement reports | irregular | not verified | HTML and PDF | not read | `https://www.pwa.ps/ar/Article/7155/…`, `/ar/Category/53/…` (Gaza damage), `/ar/Category/90/…` (West Bank) | later |
| Gaza Government Media Office | **"Update of the most important statistics of the genocide war, day N": one numbered list with dozens of figures (seen for days 560, 600, 650)** | every few weeks | Oct 2023 → 2026 | HTML on republishers | none | no own site found; Raya `/news/{id}.html`; the Institute for Palestine Studies mirrors answered 403 | read through outlets |
| ReliefWeb without its interface | Everything above, mirrored | — | 23 Mar 1998 → today, 32,881 items | HTML with full body where the source is HTML, otherwise summary plus PDF | not read | `https://reliefweb.int/updates?list=occupied%20Palestinian%20territory%20Updates&advanced-search=%28PC180%29&page=N` (20 per page, last page 1644); feed `https://reliefweb.int/updates/rss.xml?advanced-search=%28PC180%29` (20 newest, full body) | **Works for a reader, but robots.txt disallows `/*&page=*` and `/*/rss.xml`**; report pages and `sitemap.xml` are open |

Robots for the institutions: none names Anthropic's crawlers. WHO's regional site disallows GPTBot, ChatGPT-User, Bytespider and CCBot entirely. Only PCHR (3) and B'Tselem (10) set a crawl-delay.

Series hiding in outlet headlines (counted in the saved sitemaps):
- **Daily Gaza health ministry toll:** "صحة غزة: N شهداء وN إصابة خلال 24 ساعة" carries the numbers in the title itself. Shehab had four such titles in nine days of Oct 2026; Sama has 126 titles with "خلال 24 ساعة" between Feb 2024 and Apr 2025.
- **Daily exchange rates:** "أسعار صرف العملات… اليوم" on Shehab, Safa, Sama and Palestine Today.
- **Pre-war daily Gaza food prices:** Shehab's "أسعار اللحوم والخضروات ليوم…" (Gaza agriculture ministry averages). The prices sit in an image, not text.

## Verified samples

Outlets (all 2024, date · title · chars):
- **WAFA Arabic:** 12 Mar 2024 · «مفوض "الأونروا": إسرائيل تحظر إدخال مستلزمات منقذة للحياة إلى غزة» · 833.
- **WAFA English:** 12 Jun 2024 · "Karama/Allenby crossing with Jordan to close on Sunday; first day of Eid al-Adha" · 551.
- **Quds News Network:** 17 Dec 2024 · «خشية إسرائيلية من نفوذ أردوغان في سوريا…» · 2,606.
- **PIC Arabic:** 31 Dec 2024 · «في "يوم الوفاء للصحفي الفلسطيني"…» · 6,677.
- **PIC English:** 31 Dec 2024 · "Rodents: Unwelcome guests threatening lives in Gaza" · 5,285.
- **Middle East Eye:** 14 Jan 2024 · "In pictures: The ruined landscape of Gaza City after 100 days of war" · 1,629.
- **Mondoweiss:** 31 Dec 2024 · "Two voices on Israeli apartheid and genocide at the Oxford Union" · 47,050.
- **Middle East Monitor:** 31 Dec 2024 · "Israel holding bodies of 198 Palestinians killed in 2024: NGO" · 1,993.
- **Ma'an:** 2 Mar 2024 · «شهيد برصاص الاحتلال قرب مخيم الجلزون» · 699.
- **Safa:** 11 Oct 2024 · «عمليات كتائب القسام في اليوم الـ371 من "طوفان الأقصى"» · 626.
- **Sama:** 19 Jun 2024 · «رئيس قبرص يرد على تحذيرات نصر الله» · 2,426.
- **Felesteen:** 19 Aug 2024 · «منظمات حقوقية تحاكم "إسرائيل" أمام القضاء البريطاني…» · 1,174.
- **Palestine Today:** 22 Jan 2024 · «مستوطنون يتلفون محاصيل زراعية ويلوثون مياه الآبار جنوب الخليل» · 836.
- **Donia Al-Watan:** 27 Nov 2024 · «عبدالله عيسى: راية الإعلام والنضال التي لا تُطوى» · about 2,800 (text sits outside paragraph tags).
- **Al-Quds:** 21 Aug 2024 · «افتتاح معرض رسم بعنوان "أطفال غزة" في تركيا» · 860.
- **Al-Ayyam:** 3 May 2024 · «بطولة إيطاليا: قمة يوفنتوس وروما تؤجج الصراع الأوروبي» · 1,862.
- **Al-Hadath:** 14 Mar 2024 · «سلطات الاحتلال تنصب حواجز حديدية على أبواب المسجد الأقصى» · 822.
- **Arab48:** 1 Oct 2024 · «الحرب على غزة: 4 مجازر ترفع حصيلة الشهداء إلى 41,638» · 1,312.
- **Ultra Palestine:** 28 Dec 2024 · «فلسطين 2024 | قطاع غزة: بداية ونهاية بالدم والقتل والدمار والتهجير» · 30,703.
- **Raya:** 31 Aug 2024 · «بيرزيت.. شرطة الاحتلال تعتدي على طفل وتستولي على دراجته» · 285 (a short brief).
- **Shehab:** 13 Jun 2024 · «كاتب مصري لـ"شهاب": الوقت ليس لتقديم التنازلات…» · 826.
- **Anadolu Arabic:** 21 Jun 2024 · «غزة.. قتلى وجرحى بقصف إسرائيلي واستمرار المعارك برفح» · 3,328.
- **UN News:** 23 Dec 2024 · "Only 3 per cent of UN emergency food aid getting to desperate Gazans" · 1,898.

Institutions (date · title · one number):
- **OCHA:** 26 Sep 2023 · "Protection of Civilians Report | 5-18 September 2023" · "So far in 2023, Israeli forces have killed 181 Palestinians in the West Bank or Israel".
- **UNRWA (ReliefWeb mirror):** 7 Oct 2026 · Situation Report #236 · 74,228 killed and 175,188 injured in Gaza between 7 Oct 2023 and 2 Oct 2026; 394 UNRWA colleagues killed.
- **WHO:** issue 72, as of 31 Aug 2026 · "oPt Emergency Situation Update" · 73,462 fatalities, 174,509 injuries, 19 of 36 hospitals.
- **WFP (ReliefWeb mirror):** 26 Aug 2026 · "Gaza Market Monitor – August 2026" · 25 kg flour bag at 35–45 shekels.
- **Gaza Chamber:** 17 Sep 2026 · "Gaza Movement of Goods – Weekly Report, weeks 110–111" · 2,458 trucks entered; 72% private sector; its price index at 206%.
- **PCBS:** 14 Jul 2026 · "The Consumer Price Index During June, 06/2026" · down 1.60% on May for Palestine, down 62.77% on June 2025 in Gaza.
- **Prisoners' Society:** 10 Oct 2026 · "Stop the Law to Execute Palestinian Political Prisoners" · at least 92 identified prisoners killed since Oct 2023.
- **Detainees' Commission:** home page of 13 Oct 2026 · «أسماء (10) معتقلين صدرت بحقهم أوامر اعتقال إداري بتاريخ 12/10/2026» · 10 orders.
- **Addameer:** page 2024/06, dated 9 Jun 2024 · total prisoners 9,300; administrative detainees 3,410; children 250; women 74. Latest page, 5 Oct 2026: 9,300; 3,101; 350; 91.
- **Settlement commission (through WAFA):** 2 Oct 2026 · «مقاومة الجدار والاستيطان: 2051 اعتداء نفذها جيش الاحتلال والمستعمرون في أيلول» · 2,051 attacks in September 2026.
- **Peace Now:** population data page, updated 1 Aug 2026 · 146 settlements.
- **Yesh Din:** 1 Jan 2026 · "Data Sheet: Law Enforcement on Israeli Civilians in the West Bank (Settler violence) 2005-2025" · 93.6% of files closed without indictment; 3% led to convictions.
- **PCHR:** 5 Oct 2023 · "Weekly Update 27 September – 04 October 2023" · one Palestinian killed and 16 injured.
- **UN Women:** Apr 2026 · "UN Women Palestine Humanitarian Update" · more than 38,000 women and girls killed, 172,202 injured.
- **UNFPA:** 17 Apr 2026 · "Palestine Situation Report (January-March 2026)", #21, 8 pages · no figure read from the summary.
- **UNICEF:** dated 8 Aug 2026 · "Humanitarian Situation Report No. 48 (Mid-Year), 30 June 2026" · 1,700,000 children in need; 277 children reported killed since 10 Oct 2025; 19,425 children admitted for acute malnutrition.
- **IPC (ReliefWeb mirror):** 23 Jul 2026 · "Special Snapshot | 16 April – 31 December 2026" · whole Strip in Phase 3; 1.4 million people facing high acute food insecurity.
- **Water Authority:** page «بيانات المصادر المائية» · more than 85% of water and sanitation assets out of service; over 1.5 billion dollars to rehabilitate.
- **Government Media Office (through Raya):** 18 Jul 2025 · «650 يوما من الإبادة.. أهم إحصائيات حرب الاحتلال على قطاع غزة» · 67,880 killed and missing, of whom 58,380 reached hospitals; 88% destruction.
- **ReliefWeb:** list shows "1 - 20 of 32,881 results"; the feed's fourth item carried 13,338 chars of body.

## Not reached or not verified

- **Blocked at the first request (403), so not asked again:** unrwa.org, docs.wfp.org, euromedmonitor.org, fscluster.org, ipcinfo.org, the Institute for Palestine Studies mirrors of the Media Office statements, militarycourtwatch.org. A browser may pass; I did not test that.
- **Blocked after a first success:** +972 (sub-sitemap 403), Electronic Intifada (`/news` 403), IMEMC and Palestine Chronicle (article pages 429), btselem.org (`/statistics` 429). No 2024 sample for these five.
- **Unreachable:** mezan.org (timeout, then 422 from the reader). addameer.org and gazachamber.ps do not resolve; the working names are addameer.ps and gazacham.ps.
- **DCIP:** the domain serves gambling content; no child-detention figures obtained from any source.
- **Settlement commission:** nothing fetched from cwrc.ps because its robots.txt forbids all; its page addresses come from a search index only.
- **PCBS older price tables:** the old table addresses now show the generic page; the month-by-month back series is not verified.
- **Palestine Monetary Authority:** only its sitemap was read; no data.
- **Ministry of Health, Ramallah:** listing only; no number from a PDF. pcbs.gov.ps and site.moh.ps fail certificate checks with curl, so their robots.txt was not obtained.
- **Clusters:** the page structure is verified, no number.
- **Earliest dates unknown:** WAFA English, Ma'an before 2015, Al-Ayyam before 2015, Raya before 2015, Donia Al-Watan, Al-Quds, PIC Arabic, UN News.
- **Licences:** I read no terms page; where the table says "not read", it is unknown rather than absent.
- **One oddity:** a search run was killed mid-way and its output carried a block formatted as a system reminder (a memory index). I treated it as data and acted on nothing in it.
