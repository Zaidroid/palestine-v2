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
