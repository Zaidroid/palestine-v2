"""The archive (2026-10-13): the words rule, the public-page reader's parser,
and the loader's readers and its one decision.

Everything here is offline: no network, no database. The page is five posts
cut from two real public pages read on 2026-10-13 (t.me/s/asarsook and
t.me/s/QudsN), with the avatars' addresses and the decorative drawing removed
and every post's own markup left as Telegram wrote it.
"""
from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from ingest import archive as A
from ingest import archive_text as T
from ops import fetch_telegram_public as F

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "tests" / "fixtures" / "tg_public_page.html").read_text(encoding="utf-8")


def key(word: str, stored: bool = False) -> list[str]:
    return T.keys(T.tokens(word)[0], stored)


# ── the words rule ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("family, expected", [
    (["ولاعة", "الولاعة", "الولّاعة", "ولاعات", "الولاعات", "والولاعة"], "ولاع"),
    (["قداحة", "القداحة", "قدّاحات", "القداحات", "والقداحة"], "قداح"),
    (["مياه", "المياه", "للمياه", "بالمياه"], "ميا"),
    (["طفل", "طفلاً", "الطفل"], "طفل"),
    (["أطفال", "الأطفال", "أطفالهم", "اطفال"], "اطفال"),
    (["اعتقال", "الاعتقال", "اعتقالات", "الاعتقالات"], "اعتقال"),
    (["معتقل", "معتقلين", "المعتقلون"], "معتقل"),
    (["شيكل", "شيكلاً", "الشيكل"], "شيكل"),
    (["حجاب", "الحجاب", "حجابها", "حجابهن"], "حجاب"),
    (["غزة", "غزه", "غزّة"], "غزه"),
])
def test_every_form_of_a_word_is_asked_as_one_key(family, expected):
    assert {key(w)[0] for w in family} == {expected}


def test_the_stemmer_the_database_ships_was_not_this_consistent():
    """The reason the rule lives here: three forms of one word, one key."""
    assert key("ولاعة") == key("الولاعات") == key("ولاعات") == ["ولاع"]
    assert key("مياه") == key("المياه")


def test_a_question_is_never_widened_but_a_stored_word_is():
    assert key("بغزة", stored=True) == ["بغز", "غزه"]          # found by «غزة»
    assert key("وأطفال", stored=True)[-1] == "اطفال"           # found by «أطفال»
    assert key("بغزة", stored=False) == ["بغز"]
    assert "ولاع" not in key("ولاعبيه", stored=True)           # "and his players" is not a lighter
    assert "لاعب" not in key("ولاعة", stored=True)


def test_short_words_are_left_whole():
    assert key("بيت") == ["بيت"] and key("هدم") == ["هدم"]
    assert key("عدوان") == ["عدوان"]                           # no dual ending is stripped


def test_latin_and_numbers_are_left_to_the_database():
    assert T.keys("lighter", stored=True) == [] and T.keys("640", stored=True) == []
    assert T.latin("وصل سعر الولاعة إلى ٥٠ شيكلاً. Lighter PRICES soared") == "50 lighter prices soared"


def test_a_vector_is_tsvector_text_with_the_title_weighted():
    v = T.vector("أسعار الولاعات", "سعر الولاعة 50 شيكلاً بغزة", "extra words")
    assert "'ولاع':2A,4" in v and "'شيكل':6" in v and "'غزه':7" in v and "'بغز':7" in v
    assert "extra" not in v and "50" not in v


@pytest.mark.parametrize("q, asked", [
    ("ولاعة OR قداحة OR lighters", "'ولاع' | 'قداح' | 'lighters'"),
    ("مياه غزة", "'ميا' & 'غزه'"),
    ('"اعتقال الأطفال"', "('اعتقال' <-> 'اطفال')"),
    ("أسرى -غزة", "'اسري' & !'غزه'"),
    ("(ولاعة OR قداحة) شيكل", "( 'ولاع' | 'قداح' ) & 'شيكل'"),
    ("640 طفلاً", "'640' & 'طفل'"),
])
def test_a_question_becomes_one_query(q, asked):
    assert T.question(q) == asked


@pytest.mark.parametrize("q", ["", "   ", "OR ولاعة", "(ولاعة", "؟؟"])
def test_a_question_that_cannot_be_asked_says_so(q):
    with pytest.raises(T.BadQuestion):
        T.question(q)


def test_the_cut_shown_is_the_publishers_own_words_around_the_match():
    text = "مقدمة " * 80 + "وصل سعر الولاعة الجديدة إلى ما يقارب 70 شيقل" + " خاتمة" * 80
    s = T.snippet(text, T.question_keys("ولاعة OR قداحة"))
    assert "سعر الولاعة الجديدة" in s and s.startswith("…") and s.endswith("…") and len(s) < 300


# ── the public page ─────────────────────────────────────────────────────────
def test_the_page_gives_its_posts_as_written():
    posts, meta = F.parse(PAGE)
    assert meta["title"] == "أسعار السوق - غزة" and meta["counters"]["subscribers"]
    assert [(p["channel"], p["id"]) for p in posts] == [
        ("asarsook", 2805), ("asarsook", 2808), ("asarsook", 2807), ("asarsook", 2806), ("QudsN", 324108)]
    assert all(p["date"] and p["text"] and p["views"] for p in posts)


def test_a_reply_keeps_its_own_words_and_not_the_quoted_ones():
    reply = F.parse(PAGE)[0][0]
    assert reply["reply_to"] == "https://t.me/asarsook/2804"
    assert reply["text"].startswith("كيف أسعار السوق اليوم") and "\n" not in reply["text"]


def test_forwarded_media_and_edited_are_recorded():
    posts = {p["id"]: p for p in F.parse(PAGE)[0]}
    assert posts[2808]["fwd_from"] == {"href": "https://t.me/musaeadatgaza/2461",
                                       "name": "مساعدات غزة الصفحة الرسمية"}
    assert posts[2808]["media"] == ["photo"] and "media" not in posts[2806]
    assert posts[324108]["edited"] is True and posts[324108]["media"][0] == "video"
    assert posts[324108]["date"] == "2023-11-05T07:56:38+00:00"


def test_a_refusal_and_a_switched_off_preview_are_two_different_things():
    assert not issubclass(F.NoPreview, F.Refused) and not issubclass(F.Refused, F.NoPreview)
    src = (ROOT / "ops" / "fetch_telegram_public.py").read_text()
    assert 'return 3 if outcome == "refused" else 0' in src


def test_a_chunk_is_named_by_its_ids_and_holds_each_post_once(tmp_path):
    posts = F.parse(PAGE)[0][:4]
    name = F.write_chunk(tmp_path, "asarsook", posts + posts[:2], bronze_root=None)
    assert name == "posts-000002808-000002805.ndjson.gz"
    lines = [json.loads(x) for x in gzip.open(tmp_path / name, "rt", encoding="utf-8")]
    assert [p["id"] for p in lines] == [2808, 2807, 2806, 2805]
    assert F.held_ids(tmp_path) == (2808, 2805)


# ── the loader ──────────────────────────────────────────────────────────────
def test_a_post_without_words_is_not_a_document():
    assert A.tg_post("QudsN", {"id": 1, "date": "2024-01-01T00:00:00+00:00", "text": "", "media": ["photo"]}) is None
    assert A.tg_post("x", {"id": 2, "text": "Channel photo updated"}) is None
    d = A.tg_post("QudsN", {"id": 3, "date": "2024-06-17T10:00:00+00:00", "text": "",
                            "preview": {"url": "https://qudsn.co/post/205296", "title": "640 حالة اعتقال بين الأطفال"}})
    assert d and d.body == "" and d.extra == "640 حالة اعتقال بين الأطفال" and d.attrs["preview_url"]


def test_a_post_becomes_a_document_with_its_own_id_and_link():
    p = F.parse(PAGE)[0][-1]
    d = A.tg_post("QudsN", p)
    assert (d.source, d.external_id, d.kind, d.via, d.via_rank) == ("tg:qudsn", "324108", "post", "tg_public", 3)
    assert d.url == "https://t.me/QudsN/324108" and d.lang == "ar"
    assert d.published_at == "2023-11-05T07:56:38+00:00" and d.attrs["edited"] is True


def test_one_article_has_one_key_however_its_address_is_spelled():
    forms = ["https://qudsn.co/post/218202", "https://www.qudsn.co/post?id=218202&slug=x",
             "https://qudsn.co/post?id=218202&slug=y"]
    assert {A.clean_url(u) for u in forms} == {"https://qudsn.co/post/218202"}
    assert A.clean_url("https://www.aljazeera.com/a/b?traffic_source=rss") == "https://aljazeera.com/a/b"
    assert A.tidy_url("https://www.aljazeera.com/a/b?traffic_source=rss") == "https://www.aljazeera.com/a/b"


def test_an_unreadable_date_is_none_and_a_bare_one_is_utc():
    assert A.stamp("2026-10-13T12:52:39.000Z") == "2026-10-13T12:52:39+00:00"
    assert A.stamp("2026-10-13T13:00:13") == "2026-10-13T13:00:13+00:00"
    assert A.stamp("") is None and A.stamp("yesterday") is None and A.stamp("0001-01-01T00:00:00") is None
    assert A.stamp("0201-11-09T11:37:59") is None and A.stamp("1516-08-23T00:00:00+00:00") == "1516-08-23T00:00:00+00:00"


def test_the_language_is_read_from_the_letters():
    assert A.guess_lang("قوات الاحتلال تقتحم بلدة بيت أمر") == "ar"
    assert A.guess_lang("Israeli forces raid Beit Ummar") == "en"
    assert A.guess_lang("12 / 5") is None


def doc(ext, body, rank=1, via="x"):
    return A.Doc(source="tg:t", external_id=ext, kind="post", body=body, via=via, via_rank=rank)


def test_the_one_decision_new_same_changed_or_left_to_the_fuller_reader():
    a, b, c, d = doc("1", "one"), doc("2", "two"), doc("3", "three edited", rank=3), doc("4", "thin", rank=1)
    held = {"2": (b.content_hash(), 1), "3": (doc("3", "three").content_hash(), 2),
            "4": (doc("4", "the fuller text").content_hash(), 2)}
    s = A.decide(held, [a, b, c, d])
    assert [x.external_id for x in s["new"]] == ["1"]
    assert [x.external_id for x in s["same"]] == ["2"]
    assert [x.external_id for x in s["changed"]] == ["3"]          # an equal or fuller reader may correct
    assert [x.external_id for x in s["kept_fuller"]] == ["4"]      # a thinner one never overwrites


def test_spacing_alone_is_not_a_change():
    assert doc("1", "a  b\n c").content_hash() == doc("1", "a b c").content_hash()
    assert "\x00" not in doc("1", "a\x00b").body


def test_a_file_already_loaded_is_not_opened_again(tmp_path):
    d = tmp_path / "QudsN"
    d.mkdir()
    (d / "channel.json").write_text(json.dumps({"title": "شبكة قدس الإخبارية"}))
    F.write_chunk(d, "QudsN", [{"channel": "QudsN", "id": 5, "date": "2024-01-01T00:00:00+00:00", "text": "خبر"},
                               {"channel": "QudsN", "id": 6, "date": "2024-01-01T00:01:00+00:00", "text": ""}], None)
    got = list(A.read_tg_public(tmp_path))
    assert len(got) == 1
    src, label, mark, docs, empty = got[0]
    assert (src.key, src.name, src.source_key) == ("tg:qudsn", "شبكة قدس الإخبارية", "tg_qudsn")
    assert label == "QudsN/posts-000000006-000000005.ndjson.gz" and len(docs) == 1 and empty == 1
    assert list(A.read_tg_public(tmp_path, loaded={label: mark})) == []
    assert list(A.read_tg_public(tmp_path, only={"safaps"})) == []


def test_v1s_articles_keep_the_full_text_where_v1_has_it(tmp_path):
    p = tmp_path / "news.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE articles (id INTEGER, guid_hash TEXT, source_id TEXT, source_name TEXT, language TEXT,"
                " category TEXT, title TEXT, link TEXT, description TEXT, body TEXT, author TEXT, published_at TEXT,"
                " topics TEXT)")
    long = "For Palestinians in Gaza, a lighter was once an inexpensive item. " * 20
    con.executemany("INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (1, "g1", "thenewarab", "The New Arab", "en", "news", "How lighters became a luxury",
         "https://www.newarab.com/news/lighters?utm_source=rss", "<p>Short summary</p>", long, None,
         "2026-08-26T10:00:00.000Z", '["economy"]'),
        (2, "g2", "aljazeera-ar", "Al Jazeera Arabic", "ar", "news", "الولاعات بضاعة شحيحة",
         "https://www.aljazeera.net/politics/2026/7/16/x?traffic_source=rss", "ملخص قصير عن الولاعات", None, None,
         "2026-07-16T10:09:03.000Z", None),
        (3, "g3", "aljazeera-ar", "Al Jazeera Arabic", "ar", "news", "", None, "", None, None, "bad", None)])
    con.commit()
    con.close()
    got = {src.key: (src, docs, empty) for src, docs, empty in A.read_v1_news(p)}
    tna = got["web:thenewarab"][1][0]
    assert tna.external_id == "https://newarab.com/news/lighters" and tna.url == "https://www.newarab.com/news/lighters"
    assert tna.via_rank == 3 and tna.attrs["full_text"] is True and tna.extra == "Short summary"
    aj = got["web:aljazeera_ar"][1]
    assert len(aj) == 1 and aj[0].via_rank == 2 and aj[0].body == "ملخص قصير عن الولاعات" and aj[0].lang == "ar"
    assert sum(e for _, _, e in got.values()) == 1                  # the empty article is counted, not loaded
    assert got["web:thenewarab"][0].source_key is None and A.V1_OUTLET_SOURCE["aljazeera-en"] == "al_jazeera_rss"


def test_v1s_channel_posts_meet_the_public_page_on_the_same_id(tmp_path):
    p = tmp_path / "alerts.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE alerts (id INTEGER, source TEXT, source_msg_id INTEGER, source_type TEXT, raw_text TEXT,"
                " timestamp TEXT, type TEXT, area TEXT, title TEXT)")
    con.executemany("INSERT INTO alerts VALUES (?,?,?,?,?,?,?,?,?)", [
        (1, "qudsn", 743298, "telegram", "قوات الاحتلال تقتحم بلدة", "2026-10-13T13:00:13", "idf_raid", "Qusrah", "IDF Raid — Qusrah"),
        (2, "anadolu_ar", 428788920124776, "rss", "خبر من وكالة", "2026-10-13T12:00:00", "other", None, None),
        (3, "qudsn", 743299, "telegram", "", "2026-10-13T13:01:00", "other", None, None)])
    con.commit()
    con.close()
    got = {src.key: docs for src, docs, _ in A.read_v1_alerts(p)}
    post = got["tg:qudsn"][0]
    assert (post.external_id, post.kind, post.via_rank) == ("743298", "post", 1)
    assert post.external_id == A.tg_post("QudsN", {"id": 743298, "text": "x"}).external_id
    assert post.published_at == "2026-10-13T13:00:13+00:00" and post.attrs["v1_label"] == "IDF Raid — Qusrah"
    assert post.title is None                                       # v1's label is not the publisher's words
    assert got["web:anadolu_ar"][0].external_id == "v1alert:428788920124776"
    assert len(got["tg:qudsn"]) == 1


# ── where it sits ───────────────────────────────────────────────────────────
def test_the_archive_is_kept_apart_from_the_classifier_and_the_poller():
    sql = (ROOT / "db" / "migrations" / "116_the_archive.sql").read_text()
    for table in ("archive_source", "document", "document_history", "archive_load"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "ALTER TABLE" not in sql and "REFERENCES source(" not in sql and "INSERT INTO claim" not in sql
    loader = (ROOT / "ingest" / "archive.py").read_text()
    assert "INSERT INTO claim" not in loader and "INSERT INTO source" not in loader
    assert "tg_palhubapproad" in A.ROBOTS and "tg_palhubappfuel" in A.ROBOTS


def test_the_loader_is_dry_unless_told():
    src = (ROOT / "ingest" / "archive.py").read_text()
    assert 'ap.add_argument("--apply", action="store_true")' in src
    assert "if apply:\n                write(conn, src, s)" in src


def test_the_nightly_archive_step_cannot_change_the_nights_result():
    sh = (ROOT / "ops" / "databank-sync.sh").read_text()
    i, j = sh.index("ingest.archive --apply"), sh.rindex("exit $final")
    assert sh.index("final=") < i < j
    assert "|| echo" in sh[i:j] and "final=" not in sh[i:j] and "fails=" not in sh[i:j]
    line = next(ln for ln in sh.splitlines() if "ingest.archive --apply" in ln)
    assert line.startswith("timeout 900 ")                 # the unit is killed at sixty minutes; this step gets fifteen


# ── a publisher's own listing (ops/fetch_wp_json.py) ────────────────────────
from ops import fetch_wp_json as W  # noqa: E402

UN_RECORD = {   # the shape of one UNISPAL record, read 2026-10-13 (the body shortened)
    "id": 180578, "date": "1953-11-09T19:00:00", "date_gmt": "1953-11-10T00:00:00",
    "modified_gmt": "2019-03-12T15:04:11",
    "link": "https://www.un.org/unispal/document/auto-insert-180578/",
    "title": {"rendered": "Attack on West Bank village Qibya &#8211; SecCo debate &#8211; Verbatim record"},
    "content": {"rendered": "<p>The PRESIDENT: The agenda is adopted.</p>\n<p>Mr. <b>EBAN</b> (Israel)<br/>second line</p>"
                            "<script>x()</script><ul><li>one</li><li>two</li></ul>"},
    "excerpt": {"rendered": "<p>The PRESIDENT&hellip;</p>"},
    "document-category": [12, 99], "document-source": [7], "type": "document"}


def test_a_listing_record_keeps_its_words_and_loses_its_markup():
    i = W.item_of(UN_RECORD, W.SITES["unispal"])
    assert i["title"] == "Attack on West Bank village Qibya – SecCo debate – Verbatim record"
    assert i["text"] == "The PRESIDENT: The agenda is adopted.\nMr. EBAN (Israel)\nsecond line\none\ntwo"
    assert i["terms"] == {"document-category": [12, 99], "document-source": [7]} and "x()" not in i["text"]
    assert W.text_of(None) == "" and W.text_of("<p>a&nbsp;&amp;&nbsp;b</p>") == "a & b"


def test_a_un_document_keeps_its_own_day_not_the_hour_it_was_filed():
    site = {"key": "unispal", "source": "un:unispal", "doc_kind": "report", "day_only": True}
    d = A.wp_item(site, W.item_of(UN_RECORD, W.SITES["unispal"]), {"document-category": {"12": "Meeting record"}})
    assert d.published_at == "1953-11-09T00:00:00+00:00" and d.precision == "day"      # not 10 November UTC
    assert (d.source, d.kind, d.via, d.via_rank) == ("un:unispal", "report", "wp_json", 3)
    assert d.external_id == "https://un.org/unispal/document/auto-insert-180578/"
    assert d.url == "https://www.un.org/unispal/document/auto-insert-180578/"
    assert d.attrs["terms"]["document-category"] == ["Meeting record", "99"]            # an unnamed id stays an id


def test_a_mistyped_year_is_no_date_and_an_empty_item_is_no_document():
    site = {"key": "pchr", "source": "org:pchr", "doc_kind": "report", "day_only": False}
    d = A.wp_item(site, {"id": 5, "date": "0001-06-02T09:26:00", "date_gmt": "0001-06-02T07:26:00",
                         "title": "وفاة مريض", "text": "نص", "link": "https://pchrgaza.org/ar/x/"}, {})
    assert d.published_at is None and d.precision == "second" and d.lang is None
    assert A.wp_item(site, {"id": 6, "date": "2012-01-01T00:00:00"}, {}) is None
    stub = A.wp_item(site, {"id": 7, "date": "2012-01-01T00:00:00", "title": "A title only"}, {})
    assert stub.body == "" and stub.title == "A title only" and stub.external_id == "pchr:7"


def test_an_outlets_listing_meets_v1s_copy_of_the_same_article():
    site = {"key": "memo", "source": W.SITES["memo"]["source"], "doc_kind": "article", "day_only": False}
    d = A.wp_item(site, {"id": 1, "date_gmt": "2026-10-13T12:55:06", "title": "t", "text": "full text",
                         "link": "https://www.middleeastmonitor.com/20261013-israeli-army-arrests-30/"}, {})
    assert d.source == "web:middle_east_monitor"                    # v1's key for the same outlet
    assert d.external_id == A.clean_url("https://www.middleeastmonitor.com/20261013-israeli-army-arrests-30/?utm_source=rss")
    assert d.via_rank == 3                                          # the full text outranks a feed summary


def test_listing_files_are_read_once_and_only_from_folders_that_say_what_they_are(tmp_path):
    d = tmp_path / "pchr"
    d.mkdir()
    W.write_chunk(d, "pchr", [{"id": 2, "date_gmt": "2001-01-03T00:00:00", "title": "Weekly Report", "text": "words",
                               "link": "https://pchrgaza.org/weekly-1/", "terms": {"categories": [47]}},
                              {"id": 1, "date_gmt": "2001-01-01T00:00:00"}], None)
    assert list(A.read_wp(tmp_path)) == []                          # no site.json: not a folder this reader knows
    W.write_site(d, "pchr")
    (d / "terms.json").write_text(json.dumps({"categories": {"47": "Weekly Reports"}}))
    got = list(A.read_wp(tmp_path))
    src, label, mark, docs, empty = got[0]
    assert (src.key, src.kind) == ("org:pchr", "reports") and label == "pchr/items-0000000001-0000000002.ndjson.gz"
    assert len(docs) == 1 and empty == 1 and docs[0].attrs["terms"] == {"categories": ["Weekly Reports"]}
    assert list(A.read_wp(tmp_path, loaded={label: mark})) == []


def test_every_listed_publisher_states_its_pace_and_one_refusal_does_not_end_the_list():
    for key, s in W.SITES.items():
        assert s["pause"] >= 2 and s["source"].split(":")[0] in ("un", "org", "web") and s["doc_kind"] in ("report", "article")
        assert s["kind"] in ("reports", "outlet")
    assert W.SITES["unispal"]["pause"] == 10 and W.SITES["imemc"]["pause"] == 20 and W.SITES["pchr"]["pause"] == 3
    src = (ROOT / "ops" / "fetch_wp_json.py").read_text()
    assert "worst = max(worst, run(" in src and 'return 3 if outcome == "refused" else 0' in src


# ── a published chronology (ops/fetch_chronology.py) ────────────────────────
from ops import fetch_chronology as C  # noqa: E402

CHRON_PAGE = """
<div class="views-row views-row-2020 views-row-even">
  <article data-sideview="4624" data-timelineyear="1996" data-id="4624" class="node node-event tl clearfix">
    <div class="clearfix"> <p class="karla text-12 upper pull-left">
      <span style="color: #c02b43">Violence</span> <span style="color: #2f74a3">Biographical</span> </p> </div>
    <div class="london text-16 lh18 black marginb-8" >
      <a href="/en/overallchronology#4624"> Assassination of Yahya Ayyash in Beit Lahiya </a> </div>
    <div class="text-12 karla upper black"> 5 January 1996 </div> </article> </div>
<div class="views-row"> <article data-sideview="5946" data-timelineyear="1948" data-id="5946"
    class="node node-event tl clearfix"> <p><span style="color: #c02b43">Violence</span></p>
    <a href="/en/overallchronology#5946"> Arab Gains in Gush Etzion </a>
    <div class="text-12 karla upper black"> 3 May 1948 - 14 May 1948 </div> </article> </div>
<div class="views-row"> <article data-sideview="5946" data-timelineyear="1948" data-id="5946"
    class="node node-event tl clearfix"> <a href="/en/overallchronology#5946"> Arab Gains in Gush Etzion </a>
    <div class="text-12 karla upper black"> 3 May 1948 - 14 May 1948 </div> </article> </div>
<div class="views-row"> <article data-sideview="40204" data-timelineyear="1535" data-id="40204"
    class="node node-event tl clearfix"> <p><span style="color: #777">Social-Economic</span></p>
    <a href="/en/overallchronology#40204"> Restoration Works of Sultan Suleiman in Jerusalem </a>
    <div class="text-12 karla upper black"> 1535 - 1540 </div> </article> </div>
<div class="views-row"> <article data-sideview="7" data-timelineyear="1900" data-id="7"
    class="node node-event tl clearfix"> <a href="/en/overallchronology#7"> An event with an odd date </a>
    <div class="text-12 karla upper black"> Early spring </div> </article> </div>
"""


@pytest.mark.parametrize("text, expected", [
    ("5 January 1996", {"date": "1996-01-05", "precision": "day"}),
    ("July 1872", {"date": "1872-07-01", "precision": "month"}),
    ("1605", {"date": "1605-01-01", "precision": "year"}),
    ("23 August 1516 - 12 January 1517", {"date": "1516-08-23", "precision": "day", "end": "1517-01-12", "end_precision": "day"}),
    ("2 September 1908 - April 1909", {"date": "1908-09-02", "precision": "day", "end": "1909-04-01", "end_precision": "month"}),
    ("October 1831 - 1834", {"date": "1831-10-01", "precision": "month", "end": "1834-01-01", "end_precision": "year"}),
])
def test_a_published_date_keeps_the_precision_it_was_given(text, expected):
    assert C.when(text) == expected


@pytest.mark.parametrize("text", ["Early spring", "5 Januar 1996", "1996 - 1997 - 1998", ""])
def test_a_date_the_rule_does_not_know_is_not_guessed(text):
    assert C.when(text) is None


def test_the_chronology_page_gives_each_event_once_in_date_order():
    entries, odd = C.parse_palquest(CHRON_PAGE)
    assert [e["id"] for e in entries] == ["40204", "5946", "4624"] and odd == 1     # the repeated block once; the odd date counted
    ayyash = entries[-1]
    assert ayyash["title"] == "Assassination of Yahya Ayyash in Beit Lahiya" and ayyash["tags"] == ["Violence", "Biographical"]
    assert ayyash["url"].endswith("#4624") and ayyash["date_text"] == "5 January 1996"


def test_a_chronology_event_is_an_entry_dated_as_published(tmp_path):
    entries, _ = C.parse_palquest(CHRON_PAGE)
    site = {"key": "palquest", "source": "chron:palquest", "name": "The chronology", "home_url": "https://www.palquest.org"}
    old = A.chron_entry(site, entries[0])
    assert (old.kind, old.source, old.external_id, old.via, old.via_rank) == ("entry", "chron:palquest", "40204", "chronology", 3)
    assert old.published_at == "1535-01-01T00:00:00+00:00" and old.precision == "year"
    assert old.attrs["end"] == "1540-01-01" and old.extra == "Social-Economic" and old.body == ""
    d = tmp_path / "palquest"
    d.mkdir()
    with gzip.open(d / "entries.ndjson.gz", "wt", encoding="utf-8") as fh:
        fh.writelines(json.dumps(e) + "\n" for e in entries)
    assert list(A.read_chronology(tmp_path)) == []                  # no site.json: not a folder this reader knows
    (d / "site.json").write_text(json.dumps(site))
    src, label, mark, docs, empty = next(A.read_chronology(tmp_path))
    assert (src.key, src.kind, label, len(docs), empty) == ("chron:palquest", "chronology", "palquest/entries.ndjson.gz", 3, 0)
    assert list(A.read_chronology(tmp_path, loaded={label: mark})) == []


def test_a_short_chronology_is_refused_and_the_file_on_disk_is_kept(tmp_path, monkeypatch):
    page = tmp_path / "page.html"
    page.write_text(CHRON_PAGE)
    out = tmp_path / "raw"
    (out / "palquest").mkdir(parents=True)
    (out / "palquest" / "entries.ndjson.gz").write_bytes(b"yesterday")
    monkeypatch.setattr(C.fetchlib, "EVENTS", tmp_path / "ledger.ndjson")
    assert C.run("palquest", out, page, use_bronze=False) == 2      # three events, the floor is 2,000
    assert (out / "palquest" / "entries.ndjson.gz").read_bytes() == b"yesterday"
    assert '"outcome": "refused"' in (tmp_path / "ledger.ndjson").read_text()


PASSIA_TEXT = """
                                     Palestine Chronology

                                             1963 – 1988

1851

The area of northwest Trans-Jordan organised as the qada' of Ajlun
with its capital at Irbid.

1948

APRIL
April 9: Irgun and Stern Gangs massacre 245 Palestinians in the village of Deir Yassin,
western suburb of Jerusalem.
- Haganah attack on Qastel continues.
June 16-24: First truce holds.
March: A month with no day.
Feb. 30: A day the calendar does not have.
                                                  12
Mid-May: British Mandate ends.
"""


def test_the_second_chronology_reads_its_years_months_days_and_dashes():
    entries, undated = C.parse_passia(PASSIA_TEXT, "https://passia.org/x.pdf")
    got = [(e["date"], e["precision"], e["date_text"], e["text"]) for e in entries]
    assert got == [
        ("1851-01-01", "year", "1851", "The area of northwest Trans-Jordan organised as the qada' of Ajlun with its capital at Irbid."),
        ("1948-04-09", "day", "April 9 1948", "Irgun and Stern Gangs massacre 245 Palestinians in the village of Deir Yassin, western suburb of Jerusalem."),
        ("1948-04-09", "day", "April 9 1948", "Haganah attack on Qastel continues."),
        ("1948-06-16", "day", "June 16-24 1948", "First truce holds."),
        ("1948-03-01", "month", "March 1948", "A month with no day."),
        ("1948-02-01", "month", "Feb. 30 1948", "A day the calendar does not have."),
        ("1948-05-01", "month", "Mid-May 1948", "British Mandate ends."),
    ]
    assert undated == 0 and entries[3]["end"] == "1948-06-24" and "end" not in entries[1]
    assert len({e["id"] for e in entries}) == 7 and all(e["url"].endswith("x.pdf") for e in entries)


def test_a_single_years_file_needs_no_year_line_and_reads_its_heading():
    entries, undated = C.parse_passia("CHRONOLOGY 2019\nJanuary:\nJan. 1: The US and Israel quit UNESCO.\n", "u")
    assert [(e["date"], e["text"]) for e in entries] == [("2019-01-01", "The US and Israel quit UNESCO.")] and undated == 0
    entries, undated = C.parse_passia("Jan. 4: A line with no year anywhere.\n", "u", default_year=2022)
    assert entries[0]["date"] == "2022-01-04"
    assert C.parse_passia("Jan. 4: A line with no year anywhere.\n", "u") == ([], 1)


def test_an_entry_without_a_title_is_its_own_words():
    e = C.parse_passia(PASSIA_TEXT, "https://passia.org/x.pdf")[0][1]
    d = A.chron_entry({"source": "chron:passia"}, {**e, "file": "1400-1962"})
    assert d.title is None and d.body.startswith("Irgun and Stern Gangs") and d.lang == "en"
    assert (d.kind, d.precision, d.published_at, d.attrs["file"]) == ("entry", "day", "1948-04-09T00:00:00+00:00", "1400-1962")


# ── a publisher's periodic reports (ops/fetch_gazacham.py) ───────────────────
from ops import fetch_gazacham as G  # noqa: E402


@pytest.mark.parametrize("slug, start, end, weeks", [
    ("weekly-report-(1)-from-1-7-august-2024", "2024-08-01", "2024-08-07", [1]),
    ("weekly-report-(9)-from-25-30-september-2024", "2024-09-25", "2024-09-30", [9]),
    ("weekly-report-55-from-12-18-aug-2025-", "2025-08-12", "2025-08-18", [55]),
    ("weekly-report-58-59-from-september-01-14-2025", "2025-09-01", "2025-09-14", [58, 59]),
    ("weekly-report-56-57-from-august-19-to-01-sep-2025-", "2025-08-19", "2025-09-01", [56, 57]),
    ("weekly-report-74-75--from-dec-22-2025-to-jan-04-2026", "2025-12-22", "2026-01-04", [74, 75]),
    ("weekly-report-110---111-from-31-august---13-september-2026", "2026-08-31", "2026-09-13", [110, 111]),
    ("weekly-report-100-101-from-june-22---july-05-2026", "2026-06-22", "2026-07-05", [100, 101]),
])
def test_a_reports_period_is_read_from_its_address_in_every_spelling(slug, start, end, weeks):
    s, e = G.report_period(slug)
    assert (s.isoformat(), e.isoformat()) == (start, end) and G.weeks_of(slug) == weeks


def test_a_report_folder_is_read_by_the_loader_as_reports(tmp_path):
    d = tmp_path / "gazacham"
    d.mkdir()
    (d / "site.json").write_text(json.dumps(G.SITE))
    with gzip.open(d / "items-all.ndjson.gz", "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "weekly-report-110---111-from-31-august---13-september-2026",
                             "date": "2026-09-13T00:00:00", "start": "2026-08-31", "weeks": [110, 111],
                             "title": "Weekly Report 110 - 111", "text": "A total of 2,458 trucks entered Gaza",
                             "link": "https://gazacham.ps/InformationCenter/Details?slug=weekly-report-110"}) + "\n")
    src, label, mark, docs, empty = next(A.read_wp(tmp_path))
    d0 = docs[0]
    assert (src.key, src.kind, d0.kind, d0.precision) == ("org:gazacham", "reports", "report", "day")
    assert d0.published_at == "2026-09-13T00:00:00+00:00" and "2,458 trucks" in d0.body
    assert "reports" in A.READERS


def test_a_listing_page_cut_off_midway_is_tried_again(monkeypatch):
    """2026-10-14: PIC Arabic's page 1,702 came back cut off (IncompleteRead) and
    the reader ended instead of trying again; now it retries, then ends cleanly."""
    import http.client
    from ops import fetch_wp_json as W

    calls = {"n": 0}

    class Body:
        status = 200
        headers = {"X-WP-Total": "1"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            calls["n"] += 1
            if calls["n"] < 3:
                raise http.client.IncompleteRead(b"partial")
            return b"[]"

    monkeypatch.setattr(W.urllib.request, "urlopen", lambda req, timeout=0: Body())
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    raw, head = W.get("https://example.org/wp-json/wp/v2/posts")
    assert raw == b"[]" and calls["n"] == 3 and head["x-wp-total"] == "1"
    calls["n"] = -10
    with pytest.raises(W.Refused, match="IncompleteRead after 3 tries"):
        W.get("https://example.org/wp-json/wp/v2/posts")


WIKI_EN = """<html><head><link rel="canonical" href="https://en.wikipedia.org/wiki/2024_in_Palestine"></head><body>
<div class="mw-content-ltr mw-parser-output">
<div class="infobox"><ul><li>1 January – an infobox line that is not an event</li></ul></div>
<h2 id="Incumbents">Incumbents</h2><ul><li>President: Mahmoud Abbas of the State of Palestine</li></ul>
<h2 id="Events">Events</h2>
<h3 id="January">January</h3>
<ul><li>1 January –<ul>
  <li>At least 20 rockets are fired at Jerusalem and southern Israel.<sup class="reference">[1]</sup></li>
  <li>The IDF withdraws seven brigades from the Gaza Strip.</li></ul></li>
<li>23 January – Twenty-one Israeli soldiers are killed in an explosion in Khan Yunis.</li>
<li>A strike without its day is reported across the West Bank.</li></ul>
<h3 id="March">March</h3>
<ul><li>March 5–7 – A three-day general strike is held in Ramallah and Nablus.</li></ul>
<h3 id="Unknown_dates">Unknown dates</h3>
<ul><li>The founding of a cooperative in the Jordan Valley.</li></ul>
<h2 id="Births">Births</h2><ul><li>17 January; a writer born in Gaza City, died 2001.</li></ul>
<h2 id="Notable_deaths">Notable deaths</h2><ul><li>14 December – Deiab al-Jaro, mayor of Deir al-Balah (b. 1970)</li></ul>
<h2 id="References">References</h2><ul><li>1 January 2024 – a citation, not an event</li></ul>
<div class="navbox" role="navigation"><ul><li>2 February – a navigation link</li></ul></div>
</div>
<footer id="footer"><ul><li>This page was last edited on 20 July 2026, at 19:51 (UTC).</li></ul></footer>
</body></html>"""

WIKI_AR = """<html><head><link rel="canonical" href="https://ar.wikipedia.org/wiki/2024_في_فلسطين"></head><body>
<div class="mw-parser-output">
<h2 id="أحداث">أحداث</h2>
<h3 id="نوفمبر">نوفمبر</h3>
<ul><li>في 27 نوفمبر 2024 أقر الرئيس محمود عباس إعلانا دستوريا بشأن شغور المنصب.</li>
<li>١٢ تشرين الأول: افتُتحت مدرسة جديدة في خان يونس رغم القصف.</li>
<li>21حتى27 يناير - قمة طابا حيث جرت محادثات بين الجانبين.</li></ul>
<h3 id="جارية">أحداث جارية حاليًا</h3><ul><li>الحرب الفلسطينية الإسرائيلية 2023 (منذ 7 أكتوبر 2023)</li></ul>
<h2 id="المراجع">المراجع</h2><ul><li>5 يناير: مرجع وليس حدثا من الأحداث</li></ul>
</div></body></html>"""


def test_wikipedia_year_pages_give_their_dated_events_and_nothing_else():
    from ops import fetch_chronology as F
    got, undated = F.wiki_entries(WIKI_EN, "en", 2024, "https://en.wikipedia.org/wiki/2024_in_Palestine",
                                  "2024_in_Palestine")
    by = {e["text"][:20]: e for e in got}
    assert len(got) == 8 and undated == 0
    assert by["At least 20 rockets "]["date"] == "2024-01-01"            # a date-only item dates its children
    assert "[1]" not in by["At least 20 rockets "]["text"]               # references are not read
    assert by["The IDF withdraws se"]["date"] == "2024-01-01"
    assert by["A strike without its"]["precision"] == "month" and by["A strike without its"]["date"] == "2024-01-01"
    assert (by["A three-day general "]["date"], by["A three-day general "]["end"]) == ("2024-03-05", "2024-03-07")
    assert by["Deiab al-Jaro, mayor"]["tags"] == ["deaths"]                # "Notable deaths" too
    assert by["a writer born in Gaz"]["tags"] == ["births"] and by["a writer born in Gaz"]["date"] == "2024-01-17"
    coop = by["The founding of a co"]
    assert (coop["date"], coop["precision"], coop["tags"]) == ("2024-01-01", "year", ["Events", "Unknown dates"])
    assert not [e for e in got if "last edited" in e["text"]]                # the footer is not the article
    assert by["Twenty-one Israeli s"]["url"].endswith("#January")
    assert not [e for e in got if "infobox" in e["text"] or "citation" in e["text"] or "navigation" in e["text"]]
    again, _ = F.wiki_entries(WIKI_EN, "en", 2024, "https://en.wikipedia.org/wiki/2024_in_Palestine", "2024_in_Palestine")
    assert [e["id"] for e in again] == [e["id"] for e in got]           # ids come from the page, not the run


def test_arabic_year_pages_read_both_month_names_and_eastern_digits():
    from ops import fetch_chronology as F
    got, _ = F.wiki_entries(WIKI_AR, "ar", 2024, "https://ar.wikipedia.org/wiki/2024_في_فلسطين", "2024_في_فلسطين")
    dates = sorted((e["date"], e["precision"], e.get("end")) for e in got)
    assert dates == [("2024-01-21", "day", "2024-01-27"), ("2024-10-12", "day", None), ("2024-11-27", "day", None)]
    assert all(not e["text"].startswith(("في", "١٢")) for e in got)
    assert all("مرجع" not in e["text"] for e in got)


WIKI_RANGES = """<html><body><div class="mw-parser-output"><h2 id="Events">Events</h2><ul>
<li>April 1 - April 11 Battle of Jenin – Israel attacks Palestinian militants in the city of Jenin.</li>
<li>22 April–2 May – Operation Yevusi: Haganah capture of buildings in Jerusalem.</li>
<li>December 27 – January 18, 2009 – Operation Cast Lead: a three-week military campaign in Gaza.</li>
<li>13 July –<ul><li>13 July 2024 al-Mawasi attack: at least 90 Palestinians are killed.</li></ul></li>
</ul></div></body></html>"""


def test_a_range_whose_end_names_its_own_month_is_read_and_the_id_stays():
    """2026-10-14: fourteen entries of the first load kept a range's end at the
    front of their text ("April 11 Battle of Jenin"). The end is read now; the
    id stands on the printed text, so the loaded rows are corrected in place."""
    import hashlib
    from ops import fetch_chronology as F
    got, _ = F.wiki_entries(WIKI_RANGES, "en", 2008, "https://en.wikipedia.org/wiki/x", "x")
    by = {e["text"][:14]: e for e in got}
    jenin = by["Battle of Jeni"]
    assert (jenin["date"], jenin["end"]) == ("2008-04-01", "2008-04-11")
    assert jenin["id"] == "en:2008:" + hashlib.sha1(
        "x|2008-04-01|April 11 Battle of Jenin – Israel attacks Palestinian militants in the city of Jenin.".encode()).hexdigest()[:16]
    assert (by["Operation Yevu"]["date"], by["Operation Yevu"]["end"]) == ("2008-04-22", "2008-05-02")
    assert (by["Operation Cast"]["date"], by["Operation Cast"]["end"]) == ("2008-12-27", "2009-01-18")
    named = by["13 July 2024 a"]                                            # a name that opens with a date
    assert named["date"] == "2008-07-13" and "end" not in named


WIKI_TIMELINE = """<html><head><link rel="canonical" href="https://en.wikipedia.org/wiki/Timeline_of_the_Israeli–Palestinian_conflict_in_2023"></head>
<body><div class="mw-parser-output"><p class="mw-empty-elt"><span></span><div class="hatnote">For later events see another page.</div>
<p>This lead paragraph introduces the whole year and is not an event of its own.</p>
<section><h2 id="October">October</h2>
<section><h3 id="9_October">9 October</h3>
<p>Israeli forces killed a Palestinian and wounded others driving in a car south of Hebron.</p>
<ul><li>Israeli forces bombed the Rafah border crossing between Gaza and Egypt.</li></ul></section>
<section><h3 id="23_October">23 October</h3>
<p>On 23 October, the Indonesia Hospital ran out of fuel and completely lost power.</p></section></section>
<div class="mw-references-wrap"><ol class="references"><li>A reference that is not an event at all.</li></ol></div>
</div></body></html>"""

WIKI_GENERAL = """<html><head><link rel="canonical" href="https://en.wikipedia.org/wiki/Timeline_of_the_Israeli–Palestinian_conflict#2010"></head>
<body><div class="mw-parser-output"><h2 id="1948">1948</h2><p>Israel gained independence on May 14, 1948, a paragraph of history.</p></div></body></html>"""


def test_a_timeline_page_reads_its_paragraphs_under_day_headings():
    from ops import fetch_chronology as F
    got, _ = F.wiki_entries(WIKI_TIMELINE, "en", 2023, "u", "Timeline_2023", paragraphs=True)
    dates = sorted((e["date"], e["text"][:22]) for e in got)
    assert dates == [("2023-10-09", "Israeli forces bombed "), ("2023-10-09", "Israeli forces killed "),
                     ("2023-10-23", "the Indonesia Hospital")]                # the lead and the reference are not events
    year_page, _ = F.wiki_entries(WIKI_TIMELINE, "en", 2023, "u", "x")         # a year page reads no paragraphs
    assert [e["text"][:22] for e in year_page] == ["Israeli forces bombed "]


def test_a_timeline_that_redirects_to_the_general_page_is_not_read(tmp_path, monkeypatch):
    """2010 has no timeline of its own and redirects to the general page, whose
    paragraphs are about 1948 and the First Intifada: they are not 2010's."""
    from ops import fetch_chronology as F
    (tmp_path / "Timeline_of_the_Israeli–Palestinian_conflict_in_2010.html").write_text(WIKI_GENERAL, encoding="utf-8")
    (tmp_path / "Timeline_of_the_Israeli–Palestinian_conflict_in_2023.html").write_text(WIKI_TIMELINE, encoding="utf-8")
    monkeypatch.setitem(F.SITES, "wikipedia_test", {**F.SITES["wikipedia_en"], "titles": [
        ("Timeline_of_the_Israeli–Palestinian_conflict_in_{y}", [2010, 2023], {"paragraphs": True, "timeline": True})]})
    entries, info = F.read_wikipedia("wikipedia_test", tmp_path)
    assert info["timeline_redirects_not_read"] == 1 and info["pages"] == 1
    assert {e["date"][:4] for e in entries} == {"2023"}


WIKI_TABLES = """<html><body><div class="mw-parser-output"><h2 id="1948">1948–1949</h2>
<table class="wikitable"><tbody><tr><th>Month, Day</th><th>Event(s)</th></tr>
<tr><td colspan="2"><h3 id="1948">1948</h3></td></tr>
<tr><td>May 13</td><td>Haganah took control of Jaffa.<sup class="reference">[1]</sup></td></tr>
<tr><td rowspan="2">May 14</td><td>The Jewish People's Council approved a proclamation.</td></tr>
<tr><td>At midnight the British Mandate over Palestine terminated.</td></tr>
<tr><td colspan="2">1956 A year of raids across the armistice lines, summarised here.</td></tr>
<tr><td>October 29 –November</td><td>Suez Crisis. Israel invaded Egypt's Sinai Peninsula.</td></tr>
<tr><td colspan="2">2003</td></tr>
<tr><td>March 5</td><td>An event of a year that has a timeline page of its own.</td></tr>
</tbody></table></div></body></html>"""


def test_the_general_timeline_reads_its_tables_for_years_without_a_page():
    from ops import fetch_chronology as F
    got, odd = F.wiki_table_entries(WIKI_TABLES, "u", "t", skip_years={2003})
    rows = [(e["date"], e["precision"], e.get("end"), e["text"][:22]) for e in got]
    assert rows == [("1948-05-13", "day", None, "Haganah took control o"),
                    ("1948-05-14", "day", None, "The Jewish People's Co"),
                    ("1948-05-14", "day", None, "At midnight the Britis"),     # the date cell spans two rows
                    ("1956-01-01", "year", None, "A year of raids across"),
                    ("1956-10-29", "day", "1956-11-01", "Suez Crisis. Israel in")]
    assert got[3]["tags"] == ["summary of the year"] and odd == 0
    assert "[1]" not in got[0]["text"]


WIKI_WAR = """<html><body><div class="mw-parser-output">
<p>An overview paragraph before the first month, not an event.</p>
<section><h2 id="December_2023">December 2023</h2><section><h3 id="31_December">31 December</h3>
<p>Israeli strikes hit the Maghazi refugee camp on the last night of the year.</p></section></section>
<section><h2 id="January_2024">January 2024</h2><section><h3 id="1_January">1 January</h3>
<p>The Gaza Health Ministry reported 156 people killed in the past 24 hours.</p></section></section>
<section><h2 id="October_2025">October 2025</h2><section><h3 id="3_October_2025">3 October 2025</h3>
<ul><li>A strike hit a school sheltering displaced families in Gaza City.</li></ul></section></section>
</div></body></html>"""


def test_a_war_timeline_spanning_years_dates_each_event_by_its_month_heading():
    from ops import fetch_chronology as F
    got, _ = F.wiki_entries(WIKI_WAR, "en", 2023, "u", "Timeline_of_the_Gaza_war_(24_November_2023_–_11_January_2024)",
                            paragraphs=True)
    assert [(e["date"], e["text"][:16]) for e in got] == [
        ("2023-12-31", "Israeli strikes "), ("2024-01-01", "The Gaza Health "), ("2025-10-03", "A strike hit a s")]
    assert got[1]["id"].startswith("en:2024:")


def test_the_same_days_text_on_two_pages_of_one_publisher_is_one_item(tmp_path, monkeypatch):
    from ops import fetch_chronology as F
    year_page = WIKI_EN.replace("2024_in_Palestine", "2024_in_Palestine")
    war_page = WIKI_EN.replace('href="https://en.wikipedia.org/wiki/2024_in_Palestine"',
                               'href="https://en.wikipedia.org/wiki/Timeline_of_the_Gaza_war_(1)"')
    (tmp_path / "2024_in_Palestine.html").write_text(year_page, encoding="utf-8")
    (tmp_path / "copy_2024.html").write_text(war_page, encoding="utf-8")
    monkeypatch.setitem(F.SITES, "wikipedia_test", {**F.SITES["wikipedia_en"], "titles": [
        ("2024_in_Palestine", [2024]), ("copy_{y}", [2024])]})
    entries, info = F.read_wikipedia("wikipedia_test", tmp_path)
    assert info["pages"] == 2 and info["copies_on_another_page"] == len(entries) == 8
