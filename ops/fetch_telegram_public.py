"""Read a public Telegram channel's whole history from Telegram's own public web
page (t.me/s/<channel>) — no account, no session, nothing joined.

    .venv/bin/python -m ops.fetch_telegram_public QudsN            # back through history
    .venv/bin/python -m ops.fetch_telegram_public QudsN --new      # only what is newer than held
    .venv/bin/python -m ops.fetch_telegram_public QudsN --pages 5  # a short trial
    .venv/bin/python -m ops.fetch_telegram_public QudsN safaps --until 2023-10-01   # the war years first

WHY THIS EXISTS. The poller reads a channel from the day the account joined
it, so the store's news begins in the summer of 2026 and a war that began in
October 2023 is not in it (measured 2026-10-13: of 143,472 messages, the only
ones older than June 2026 are the Ministry of Health's). The account is the
scarcest asset in this system and is not spent on history. A public channel
with its preview switched on serves the same posts, twenty to a page, to any
browser: `?before=<id>` pages back, `?after=<id>` pages forward. Measured the
same day: Quds News about 436,000 post numbers since 7 October 2023, Safa
about 248,000, the Palestinian Information Center about 285,000.

THE POSTURE (ops/fetchlib.py), and one rule of its own:

  SLOW       one page every `--pause` seconds (default 3) with a little jitter.
  STOPS AT THE FIRST REFUSAL. Any answer that is not HTTP 200 ends the run
             with exit 3 and a `refused` line in the ledger. It is not retried
             and not worked around: a refusal is the publisher's answer.
             A channel whose preview is switched off is a different thing
             (`no_preview`): it is skipped and the run goes on.
             A dropped connection is retried three times, a minute apart.
  RESUMABLE  `cursor.json` holds the next `before`; a killed run loses at most
             the chunk it was filling and re-reads it.
  ATOMIC     every chunk is written to a temp file and renamed.
  LEDGERED   one line per run to ops/fetch-events.ndjson, label
             `tg_public:<channel>`.
  STOP FILE  `touch data/raw/tg_public/STOP` (or `<channel>/STOP`) ends the
             run cleanly after the page in hand. Remove it to run again.
  ONE AT A TIME. A second reader on the same folder exits at once (exit 4).

WHAT IT WRITES, under --out (default data/raw/tg_public):

  <channel>/posts-<newest id>-<oldest id>.ndjson.gz   the record: one post a line
  <channel>/cursor.json                               where the run stands
  <channel>/channel.json                              title and counters as the page gives them

and, under --cache (default data/cache/tg_public_html), each page as it
arrived, gzipped. The cache is a convenience for re-parsing without asking
Telegram again; it can be deleted, the post files cannot. Each post file is
also archived in bronze (source key `tgpub_<channel>`) so the nightly backup
carries it before any loader has run.

A POST, as written: channel, id, date (the page's own ISO stamp), text (line
breaks kept), links (every href in the text), media (kinds, in order), views
(as shown, e.g. "12.3K"), and when present: fwd_from {name, href}, reply_to,
preview {url, site, title, description}, author, edited.
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import bronze                                       # noqa: E402
from ops import fetchlib                                        # noqa: E402

UA = "palestine-v2 archive reader (personal research)"
OUT = ROOT / "data" / "raw" / "tg_public"
CACHE = ROOT / "data" / "cache" / "tg_public_html"
CHUNK_PAGES = 200            # about 4,000 posts a file
VOID = {"br", "img", "meta", "link", "input", "hr", "source", "area", "base", "col", "embed", "wbr"}
MEDIA = {"tgme_widget_message_photo_wrap": "photo", "tgme_widget_message_video_player": "video",
         "tgme_widget_message_document_wrap": "document", "tgme_widget_message_voice_player": "voice",
         "tgme_widget_message_poll": "poll", "tgme_widget_message_location_wrap": "location",
         "tgme_widget_message_sticker_wrap": "sticker", "tgme_widget_message_roundvideo_player": "video",
         "message_media_not_supported_wrap": "unsupported"}
CAPTURE = {"js-message_text": "text", "tgme_widget_message_views": "views",
           "tgme_widget_message_forwarded_from_name": "fwd_name",
           "tgme_widget_message_from_author": "author", "tgme_widget_message_meta": "meta",
           "link_preview_site_name": "pv_site", "link_preview_title": "pv_title",
           "link_preview_description": "pv_description"}


class Refused(Exception):
    """Telegram answered, and the answer was not the page."""


class NoPreview(Exception):
    """The channel has its public preview switched off (or does not exist):
    the owner's setting, not a refusal. This channel is skipped, the run goes on."""


class Page(HTMLParser):
    """One public page → its posts. A stack of open tags decides where a post
    and each captured field end, so nested markup inside a text cannot close
    it early."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: list[dict] = []
        self.meta: dict = {}
        self.stack: list[str] = []
        self.cur: dict | None = None
        self.cur_depth = 0
        self.caps: list[list] = []          # [field, depth at start, pieces]
        self.counter: str | None = None

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._data("\n")
        elif tag not in VOID:               # e.g. <path .../> inside an svg
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self._data("\n")
            return
        if tag in VOID:
            return
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        self.stack.append(tag)
        depth = len(self.stack)
        if self.cur is None:
            if tag == "div" and "tgme_widget_message" in cls and a.get("data-post"):
                ch, _, pid = a["data-post"].partition("/")
                self.cur = {"channel": ch, "id": int(pid.split("?")[0]), "date": None, "text": [],
                            "links": [], "media": []}
                self.cur_depth = depth
            elif tag == "span" and "counter_value" in cls:
                self.caps.append(["counter_value", depth, []])
            elif tag == "span" and "counter_type" in cls:
                self.caps.append(["counter_type", depth, []])
            elif tag == "div" and "tgme_channel_info_header_title" in cls:
                self.caps.append(["title", depth, []])
            return
        c = self.cur
        for k, kind in MEDIA.items():
            if k in cls:
                c["media"].append(kind)
        if tag == "time" and a.get("datetime") and self._in("meta"):
            c["date"] = a["datetime"]
        if tag == "a":
            href = a.get("href") or ""
            if "tgme_widget_message_reply" in cls:
                c["reply_to"] = href
            elif "tgme_widget_message_link_preview" in cls:
                c.setdefault("preview", {})["url"] = href
            elif "tgme_widget_message_forwarded_from_name" in cls:
                c.setdefault("fwd_from", {})["href"] = href
            elif href and self._in("text") and not self._in("reply"):
                c["links"].append(href)
        if "tgme_widget_message_reply" in cls:
            self.caps.append(["reply", depth, []])          # swallows the quoted text
        for k, field in CAPTURE.items():
            if k in cls and not (field == "text" and self._in("reply")):
                self.caps.append([field, depth, []])

    def handle_endtag(self, tag):
        if tag in VOID or tag not in self.stack:
            return
        while self.stack and self.stack.pop() != tag:
            pass
        depth = len(self.stack)
        while self.caps and self.caps[-1][1] > depth:
            field, _, pieces = self.caps.pop()
            self._close(field, "".join(pieces))
        if self.cur is not None and depth < self.cur_depth:
            c = self.cur
            c["text"] = "\n".join(t for t in c["text"] if t)
            for k in ("links", "media"):
                if not c[k]:
                    del c[k]
            self.posts.append(c)
            self.cur = None

    def handle_data(self, data):
        self._data(data)

    def _data(self, s: str) -> None:
        for cap in self.caps:
            cap[2].append(s)

    def _in(self, field: str) -> bool:
        return any(c[0] == field for c in self.caps)

    def _close(self, field: str, value: str) -> None:
        value = value.strip()
        if field == "counter_value":
            self.counter = value
        elif field == "counter_type":
            if self.counter is not None:
                self.meta.setdefault("counters", {})[value] = self.counter
            self.counter = None
        elif field == "title":
            self.meta["title"] = " ".join(value.split())
        elif self.cur is None or field == "reply":
            return
        elif field == "text":
            self.cur["text"].append("\n".join(ln.rstrip() for ln in value.split("\n")).strip())
        elif field == "meta":
            if "edited" in value:
                self.cur["edited"] = True
        elif field == "fwd_name":
            self.cur.setdefault("fwd_from", {})["name"] = value
        elif field.startswith("pv_"):
            if value:
                self.cur.setdefault("preview", {})[field[3:]] = " ".join(value.split())
        elif value:
            self.cur[field] = value


def parse(html: str) -> tuple[list[dict], dict]:
    p = Page()
    p.feed(html)
    p.close()
    return p.posts, p.meta


def get(url: str, tries: int = 3) -> str:
    """The page, or Refused. A dropped connection is retried; an HTTP answer
    that is not 200 never is."""
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
            with urllib.request.urlopen(req, timeout=40) as r:
                if r.status != 200:
                    raise Refused(f"HTTP {r.status}")
                if "/s/" not in r.geturl():
                    raise NoPreview(f"redirected to {r.geturl()}")
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise Refused(f"HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries:
                raise Refused(f"network: {type(e).__name__} after {tries} tries") from None
            time.sleep(60 * attempt)
    raise Refused("unreachable")


def write_chunk(d: Path, channel: str, posts: list[dict], bronze_root: Path | None) -> str:
    posts = sorted({p["id"]: p for p in posts}.values(), key=lambda p: -p["id"])
    name = f"posts-{posts[0]['id']:09d}-{posts[-1]['id']:09d}.ndjson.gz"
    body = "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in posts).encode("utf-8")
    tmp = d / (name + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(body)
    tmp.replace(d / name)
    if bronze_root is not None:
        keep = bronze.BRONZE
        bronze.BRONZE = bronze_root
        try:
            bronze.put(f"tgpub_{channel}", body, "ndjson", url=f"https://t.me/s/{channel}")
        finally:
            bronze.BRONZE = keep
    return name


def held_ids(d: Path) -> tuple[int | None, int | None]:
    """(newest, oldest) post id in the files already written."""
    hi = lo = None
    for f in d.glob("posts-*.ndjson.gz"):
        a, b = f.name[6:-10].split("-")
        hi = max(hi or 0, int(a))
        lo = min(lo or int(b), int(b))
    return hi, lo


def run(channel: str, out: Path, cache: Path, pause: float, pages: int | None,
        new: bool, bronze_root: Path | None, until: str | None = None) -> int:
    d = out / channel
    d.mkdir(parents=True, exist_ok=True)
    cdir = cache / channel
    cdir.mkdir(parents=True, exist_ok=True)
    label = f"tg_public:{channel}"
    cur_path = d / "cursor.json"
    cursor = json.loads(cur_path.read_text()) if cur_path.exists() else {}
    hi, lo = held_ids(d)
    if new:
        mark, param = hi or 0, "after"
    else:
        mark, param = cursor.get("before"), "before"
        if cursor.get("done"):
            print(f"{channel}: history already read to its first post ({cursor.get('oldest_date')})")
            return 0
        if until and (cursor.get("oldest_date") or "9")[:10] < until:
            return 0                # this slice is already read
    buf: list[dict] = []
    n_pages = n_posts = 0
    outcome, why = "ok", ""
    oldest = cursor.get("oldest_date")
    newest = cursor.get("newest_date")

    def flush() -> None:
        nonlocal buf
        if buf:
            name = write_chunk(d, channel, buf, bronze_root)
            print(f"  wrote {name} ({len(buf):,} posts)", flush=True)
            buf = []
        if not new:
            cursor.update({"before": mark, "oldest_date": oldest, "newest_date": newest,
                           "pages": cursor.get("pages", 0) + n_pages_since[0],
                           "posts": cursor.get("posts", 0) + n_posts_since[0],
                           "updated": datetime.now(timezone.utc).isoformat()})
            n_pages_since[0] = n_posts_since[0] = 0
            tmp = cur_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cursor, ensure_ascii=False, indent=1))
            tmp.replace(cur_path)

    n_pages_since, n_posts_since = [0], [0]
    try:
        while pages is None or n_pages < pages:
            if (out / "STOP").exists() or (d / "STOP").exists():
                outcome, why = "stopped", "stop file"
                break
            url = f"https://t.me/s/{channel}" + (f"?{param}={mark}" if mark is not None else "")
            html = get(url)
            posts, meta = parse(html)
            n_pages += 1
            n_pages_since[0] += 1
            with gzip.open(cdir / f"{param}-{mark if mark is not None else 'latest'}.html.gz", "wb") as fh:
                fh.write(html.encode("utf-8"))
            if meta and not (d / "channel.json").exists():
                (d / "channel.json").write_text(json.dumps(
                    {**meta, "channel": channel, "read_at": datetime.now(timezone.utc).isoformat()},
                    ensure_ascii=False, indent=1))
            if not posts:
                if mark is None:
                    raise NoPreview("the page shows no posts")
                if new:
                    outcome, why = "ok", "nothing newer"
                else:
                    cursor["done"] = True
                    outcome, why = "done", "reached the first post"
                break
            ids = [p["id"] for p in posts]
            dated = sorted(p["date"] for p in posts if p.get("date"))
            if dated:
                oldest = min(oldest or dated[0], dated[0])
                newest = max(newest or dated[-1], dated[-1])
            buf.extend(posts)
            n_posts += len(posts)
            n_posts_since[0] += len(posts)
            nxt = max(ids) if new else min(ids)
            if nxt == mark:
                raise Refused(f"the page did not move past {mark}")
            mark = nxt
            if until and not new and oldest and oldest[:10] < until:
                outcome, why = "ok", f"read back past {until}"
                break
            if n_pages % CHUNK_PAGES == 0:
                flush()
                print(f"{channel}: {cursor.get('pages', n_pages):,} pages, back to {oldest and oldest[:10]}", flush=True)
            time.sleep(pause + random.uniform(0, pause / 4))
    except Refused as e:
        outcome, why = "refused", str(e)
    except NoPreview as e:
        outcome, why = "no_preview", str(e)
    finally:
        flush()
    fetchlib.event(label, outcome, pages=n_pages, rows=n_posts, oldest=oldest, newest=newest,
                   direction="new" if new else "back", **({"why": why} if why else {}))
    print(f"{channel}: {outcome}{' (' + why + ')' if why else ''} · {n_pages:,} pages, {n_posts:,} posts this run"
          f" · held back to {oldest and oldest[:10]}", flush=True)
    return 3 if outcome == "refused" else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("channels", nargs="+")
    ap.add_argument("--new", action="store_true", help="only posts newer than the newest held")
    ap.add_argument("--pages", type=int, help="stop after this many pages (a trial)")
    ap.add_argument("--pause", type=float, default=3.0)
    ap.add_argument("--until", help="stop a channel once it is read back past this day (YYYY-MM-DD); the cursor stays, a later run goes on")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--bronze-root", type=Path, default=bronze.BRONZE,
                    help="where post files are archived (default: this tree's data/bronze)")
    ap.add_argument("--no-bronze", action="store_true")
    a = ap.parse_args()
    # One reader at a time on a folder: two would double the pace Telegram sees
    # and write the same cursor.
    a.out.mkdir(parents=True, exist_ok=True)
    lock = open(a.out / ".reader.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another reader is already running on this folder; not starting a second")
        return 4
    for ch in a.channels:
        rc = run(ch, a.out, a.cache, a.pause, a.pages, a.new, None if a.no_bronze else a.bronze_root, a.until)
        if rc:                      # a refusal ends the whole run, not just this channel
            return rc
        if (a.out / "STOP").exists():
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
