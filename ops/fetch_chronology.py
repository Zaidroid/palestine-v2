"""Read a published chronology of dated events into the archive's raw tree.

    .venv/bin/python -m ops.fetch_chronology palquest
    .venv/bin/python -m ops.fetch_chronology palquest --from-file page.html   # parse a page already in hand
    .venv/bin/python -m ops.fetch_chronology wikipedia_en wikipedia_ar          # the year pages, slowly
    .venv/bin/python -m ops.fetch_chronology wikipedia_ar --from-dir DIR        # parse pages already fetched

WHY. Zaid, 13 October 2026: the archive should reach "as much as possible
from 1948". Channels begin in the 2010s and outlets' archives around 2000;
for the decades before, the dated backbone is the chronologies scholars have
already compiled. The first is the Interactive Encyclopedia of the Palestine
Question (the Institute for Palestine Studies with the Palestinian Museum):
its whole "overall chronology" is one page, measured that day at 2,541 events
from 1516 to 2026, each with a date or a date range, a title and one or more
of twelve kinds (Diplomatic, Violence, Colonization, Legal ...).

ONE REQUEST. The page is asked for once (the site's robots file sets a
crawl-delay of ten seconds and forbids only the chronology's query forms,
which this does not use). The event descriptions load by script and are not
taken; an entry is its date, title and kinds, with a link to the event.

WIKIPEDIA (2026-10-14). Its year pages list dated events: English "YYYY in
Palestine" and "YYYY in Mandatory Palestine", Arabic «YYYY في فلسطين». They are
read as ordinary article pages (/wiki/...), which the robots file allows; its
API paths (/w/, /api/) are disallowed to crawlers and are not used. One page
every three seconds; a page that does not exist (404) is skipped. Every list
item under an events or deaths heading that carries a date, or sits under a
month heading, is an entry; a date-only item gives its date to the items
nested under it. Entry ids come from the page, the date and the text, so an
edited event later arrives as a new entry and the earlier one is kept.
Licence: CC BY-SA 4.0 (attribution, share-alike); every entry links its page.

THE POSTURE (ops/fetchlib.py): atomic, FLOORED (fewer than 2,000 events is
refused and the file on disk is kept), ledgered as `chronology:<key>`.

WHAT IT WRITES, under data/raw/chronology/<key>/:
  entries.ndjson.gz   one event a line: id, date, precision (day | month |
                      year), end and end_precision when it is a range,
                      date_text as published, title, tags, url
  site.json           the publisher, as the loader needs it
and the page as it arrived, gzipped, in bronze (`chron_<key>`).
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import html as html_mod
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest import bronze                                       # noqa: E402
from ops import fetchlib                                        # noqa: E402

UA = "palestine-v2 archive reader (personal research)"
UA_WIKI = "zaidlab-palestine-archive/1.0 (https://zaidlab.xyz; personal research archive; one page every three seconds)"
OUT = ROOT / "data" / "raw" / "chronology"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
SITES = {
    "palquest": {"name": "Interactive Encyclopedia of the Palestine Question, overall chronology"
                         " (Institute for Palestine Studies and the Palestinian Museum)",
                 "home_url": "https://www.palquest.org/en/overallchronology",
                 "page": "https://www.palquest.org/en/timeline/overallchronology-slim1",
                 "source": "chron:palquest", "floor": 2000},
    "passia": {"name": "PASSIA Palestine Chronology (Palestinian Academic Society for the Study of"
                       " International Affairs, Jerusalem)",
               "home_url": "https://passia.org/palestine-chronology/",
               "page": "https://passia.org/palestine-chronology/",
               "source": "chron:passia", "floor": 4000},
    "wikipedia_en": {"name": "Wikipedia (English), the year pages: 'YYYY in Palestine', 'YYYY in Mandatory Palestine'",
                     "home_url": "https://en.wikipedia.org/wiki/List_of_years_in_Palestine",
                     "page": "https://en.wikipedia.org/wiki/", "source": "chron:wikipedia_en", "lang": "en",
                     "titles": [("{y}_in_Mandatory_Palestine", range(1917, 1949)), ("{y}_in_Palestine", range(1900, 2027))],
                     "floor": 2000},
    "wikipedia_ar": {"name": "ويكيبيديا العربية، صفحات السنوات: «YYYY في فلسطين»",
                     "home_url": "https://ar.wikipedia.org/",
                     "page": "https://ar.wikipedia.org/wiki/", "source": "chron:wikipedia_ar", "lang": "ar",
                     "titles": [("{y}_في_فلسطين", range(1900, 2027))],
                     "floor": 800},
}
_EVENT = re.compile(r'<article\s+data-sideview="\d+"\s+data-timelineyear="(-?\d+)"\s+data-id="(\d+)"\s+'
                    r'class="node node-event tl clearfix"\s*>(.*?)</article>', re.S)
_TITLE = re.compile(r'<a\s+href="/en/overallchronology#\d+"\s*>\s*(.*?)\s*</a>', re.S)
_DATE = re.compile(r'<div\s+class="text-12 karla upper black"\s*>\s*(.*?)\s*</div>', re.S)
_TAG = re.compile(r'<span\s+style="color:\s*#[0-9a-fA-F]+"\s*>([^<]+)</span>')
_WHEN = re.compile(r"^(?:(\d{1,2})\s+)?(?:([A-Za-z]+)\s+)?(\d{3,4})$")


def _text(s: str) -> str:
    return html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def one_date(s: str) -> tuple[str, str] | None:
    """'5 January 1996' | 'July 1872' | '1605' → (ISO day, precision)."""
    m = _WHEN.match(s.strip())
    if not m:
        return None
    day, month, year = m.groups()
    if month and month.lower() not in MONTHS:
        return None
    mo = MONTHS[month.lower()] if month else 1
    precision = "day" if day else ("month" if month else "year")
    return f"{int(year):04d}-{mo:02d}-{int(day or 1):02d}", precision


def when(s: str) -> dict | None:
    """A date or a range as published → date, precision and, for a range, end
    and end_precision. None when the text is not a date this rule knows."""
    parts = [p.strip() for p in re.split(r"\s+[-–]\s+", s.strip())]
    if len(parts) > 2:
        return None
    a = one_date(parts[0])
    if a is None:
        return None
    out = {"date": a[0], "precision": a[1]}
    if len(parts) == 2:
        b = one_date(parts[1])
        if b is None:
            return None
        out.update(end=b[0], end_precision=b[1])
    return out


def parse_palquest(page: str) -> tuple[list[dict], int]:
    """The page → its events, each once (the page repeats an event under every
    year a range touches), and how many date texts were not understood."""
    seen: dict[str, dict] = {}
    odd = 0
    for _year, eid, body in _EVENT.findall(page):
        if eid in seen:
            continue
        t, d = _TITLE.search(body), _DATE.search(body)
        if not (t and d):
            odd += 1
            continue
        date_text = _text(d.group(1))
        w = when(date_text)
        if w is None:
            odd += 1
            continue
        seen[eid] = {"id": eid, **w, "date_text": date_text, "title": _text(t.group(1)),
                     "tags": [html_mod.unescape(x).strip() for x in _TAG.findall(body)],
                     "url": f"https://www.palquest.org/en/overallchronology#{eid}"}
    return sorted(seen.values(), key=lambda e: (e["date"], int(e["id"]))), odd


_P_MONTH = (r"(Jan|Feb|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?")
_P_ENTRY = re.compile(rf"^{_P_MONTH}(?:\s+(\d{{1,2}})(?:\s*[-–/]\s*(\d{{1,2}}))?)?\s*:\s*(.*)$")
_P_LOOSE = re.compile(rf"^(?:(?:Mid|Early|Late|End of|Beginning of|Start of)[- ]+)?{_P_MONTH}"
                      rf"(?:\s*[-–/]\s*{_P_MONTH})?(?:\s+\d{{1,2}})?\s*:\s*(.*)$", re.I)
_P_DASH = re.compile(r"^[-–•]\s+(.*)$")
_P_YEAR = re.compile(r"^(1[4-9]\d\d|20\d\d)$")
_P_MON = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12}


_P_HEAD = re.compile(r"^(?:palestine\s+)?chronology(?:\s+(\d{4}))?$", re.I)
_P_MONTH_ONLY = re.compile(r"^(january|february|march|april|may|june|july|august|september|october|november|december)"
                           r"\s*:?$", re.I)


def parse_passia(text: str, url: str, default_year: int | None = None) -> tuple[list[dict], int]:
    """One PASSIA chronology file as text (pdftotext -layout) → its entries,
    and how many lines stood under no year and were not taken.

    The files have one shape from 1911 on: a year on a line of its own (or in
    the heading, "CHRONOLOGY 2019"; a month's name alone is a divider), then
    `Jan. 5: …`, `June 16-24: …`, `March: …`; a line that begins with a dash is
    one more event of the same date; other lines continue the entry above.
    Before the months begin, a year's heading is followed by plain sentences,
    which are taken as one entry of that year."""
    import hashlib
    entries: list[dict] = []
    year: int | None = default_year
    cur: dict | None = None
    undated = 0

    def close() -> None:
        nonlocal cur
        if cur and cur["text"].strip():
            cur["text"] = " ".join(cur["text"].split())
            cur["id"] = cur["date"] + ":" + hashlib.sha1(cur["text"].encode("utf-8")).hexdigest()[:10]
            entries.append(cur)
        cur = None

    def start(month: int | None, day: str | None, end: str | None, date_text: str, first: str) -> None:
        nonlocal cur
        close()
        if day:
            try:
                datetime.date(year, month, int(day))
            except ValueError:                          # "Feb. 30" in the source: keep the month, say what was printed
                day = None
        precision = "day" if day else ("month" if month else "year")
        cur = {"date": f"{year:04d}-{month or 1:02d}-{int(day or 1):02d}", "precision": precision,
               "date_text": f"{date_text} {year}".strip(), "text": first, "url": url}
        if end and day and int(end) > int(day):
            cur.update(end=f"{year:04d}-{month:02d}-{int(end):02d}", end_precision="day")

    for raw in text.replace("\f", "\n").split("\n"):
        line = raw.strip()
        if not line or re.fullmatch(r"\d{1,3}", line) or re.fullmatch(r"\d{4}\s*[-–]\s*\d{4}", line) \
                or _P_MONTH_ONLY.match(line):
            continue
        h = _P_HEAD.match(line)
        if h:                                           # "Palestine Chronology", "CHRONOLOGY 2019"
            if h.group(1):
                close()
                year = int(h.group(1))
            continue
        if _P_YEAR.match(line):
            close()
            year = int(line)
            continue
        if year is None:
            undated += 1
            continue
        m = _P_ENTRY.match(line)
        if m:
            start(_P_MON[m.group(1)[:3].lower()], m.group(2), m.group(3), line.split(":", 1)[0], m.group(4))
            continue
        m = _P_LOOSE.match(line)
        if m:
            start(_P_MON[m.group(1)[:3].lower()], None, None, line.split(":", 1)[0], m.group(3))
            continue
        m = _P_DASH.match(line)
        if m and cur is not None:
            month, day = int(cur["date"][5:7]), cur["date"][8:10]
            prev = cur
            start(month if prev["precision"] != "year" else None, day if prev["precision"] == "day" else None,
                  None, prev["date_text"].rsplit(" ", 1)[0], m.group(1))
            if prev.get("end"):
                cur.update(end=prev["end"], end_precision="day")
            continue
        if cur is None:
            start(None, None, None, "", line)                       # sentences under a bare year
        else:
            cur["text"] += " " + line
    close()
    return entries, undated


def read_passia(out: Path, from_dir: Path | None) -> tuple[list[dict], dict]:
    """Every chronology file PASSIA's index links, as entries. Asks the index
    once and each file once, two seconds apart; a dead link (404) is skipped and
    named, any other refusal ends the run."""
    import subprocess
    import tempfile
    import time
    import urllib.error
    import urllib.parse
    site = SITES["passia"]
    info: dict = {"files": 0, "missing": [], "undated_lines": 0}
    entries: list[dict] = []
    work = from_dir or Path(tempfile.mkdtemp(prefix="passia-"))
    if from_dir:
        files = {p.stem: json.loads((from_dir / "index.json").read_text())["files"][p.stem]["url"]
                 for p in sorted(from_dir.glob("*.pdf"))}
    else:
        req = urllib.request.Request(site["page"], headers={"User-Agent": UA})
        index = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
        files = {}
        for href, text in re.findall(r'href="([^"]+\.pdf)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{1,60})', index):
            label = html_mod.unescape(text).replace("\xa0", " ").replace("•", "").strip()
            if re.fullmatch(r"\d{4}(\s*[–-]\s*\d{4})?", label):
                files[re.sub(r"\s*[–-]\s*", "-", label)] = urllib.parse.urljoin("https://passia.org/", href)
        for label, url in list(files.items()):
            time.sleep(2.2)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                    (work / f"{label}.pdf").write_bytes(r.read())
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                info["missing"].append(label)
                del files[label]
    for label, url in files.items():
        pdf = work / f"{label}.pdf"
        bronze.put("chron_passia", pdf.read_bytes(), "pdf", url=url)
        text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, check=True).stdout.decode(
            "utf-8", "replace")
        got, undated = parse_passia(text, url, int(label) if label.isdigit() else None)
        for e in got:
            e["file"] = label
        entries.extend(got)
        info["files"] += 1
        info["undated_lines"] += undated
    seen: dict[str, dict] = {}
    for e in entries:
        seen.setdefault(e["id"], e)
    return sorted(seen.values(), key=lambda e: (e["date"], e["id"])), info


_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_AR_MONTHS = {"يناير": 1, "كانون الثاني": 1, "فبراير": 2, "شباط": 2, "مارس": 3, "آذار": 3, "أبريل": 4, "إبريل": 4,
              "ابريل": 4, "نيسان": 4, "مايو": 5, "أيار": 5, "يونيو": 6, "يونيه": 6, "حزيران": 6, "يوليو": 7,
              "يوليه": 7, "تموز": 7, "أغسطس": 8, "آب": 8, "سبتمبر": 9, "أيلول": 9, "أكتوبر": 10,
              "تشرين الأول": 10, "نوفمبر": 11, "تشرين الثاني": 11, "ديسمبر": 12, "كانون الأول": 12}
_AR_MONTH = "|".join(sorted(map(re.escape, _AR_MONTHS), key=len, reverse=True))
_EN_MONTH = "January|February|March|April|May|June|July|August|September|October|November|December"
_SEP = r"\s*(?:[–—:;؛-]|$)\s*"
_RANGE = r"\s*(?:[–-]|حتى|إلى|الى)\s*"
_W_EN = [re.compile(rf"^(?:On\s+)?(\d{{1,2}})(?:{_RANGE}(\d{{1,2}}))?\s+({_EN_MONTH})(?:\s+\d{{4}})?(?:\s*,\s*|{_SEP})(.*)$", re.S),
         re.compile(rf"^(?:On\s+)?({_EN_MONTH})\s+(\d{{1,2}})(?:{_RANGE}(\d{{1,2}}))?(?:,?\s+\d{{4}})?(?:\s*,\s*|{_SEP})(.*)$", re.S)]
_W_EN_MONTH = re.compile(rf"^(?:In\s+)?({_EN_MONTH})(?:\s+\d{{4}})?\s*[–—:;-]\s*(.*)$", re.S)
_W_AR = re.compile(rf"^(?:في\s+)?(\d{{1,2}})(?:{_RANGE}(\d{{1,2}}))?\s*({_AR_MONTH})(?:\s+\d{{4}})?(?:\s*[،,]\s*|{_SEP}|\s+)(.*)$", re.S)
_W_AR_MONTH = re.compile(rf"^(?:في\s+)?(?:شهر\s+)?({_AR_MONTH})(?:\s+\d{{4}})?\s*[–—:؛;-]\s*(.*)$", re.S)
_W_SKIP = re.compile(r"^(incumbents|see also|references|external links|further reading|notes|sources|bibliography|"
                     r"citations|ongoing|ongoing events|المسؤولون|المراجع|مراجع|انظر أيضا|انظر أيضًا|وصلات خارجية|"
                     r"مصادر|ملاحظات|قراءات إضافية|استشهادات|أصحاب المناصب|المناصب القيادية|شاغلو المناصب|"
                     r"أحداث جارية|أحداث جارية حاليا|أحداث جارية حاليًا)$", re.I)
_W_DEATHS = re.compile(r"^(notable deaths|deaths|الوفيات|وفيات)$", re.I)
_W_BIRTHS = re.compile(r"^(notable births|births|المواليد|مواليد)$", re.I)
_W_NOT_READ = ("navbox", "reflist", "refbegin", "reference", "mw-editsection", "infobox", "sidebar", "hatnote",
               "thumb", "toc", "catlinks", "noprint", "metadata", "ambox", "mw-references-wrap", "printfooter",
               "gallery", "mw-empty-elt")


def wiki_items(page: str) -> list[dict]:
    """The list items of a Wikipedia article's text, each with the headings it
    sits under, its own text (nested items apart) and the item it is nested in.
    Navigation boxes, references, tables, infoboxes and edit links are not read."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.on, self.stack, self.skip = 0, [], 0
            self.heads: dict = {}
            self.head = None
            self.items: list[dict] = []
            self.open: list[int] = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            cls = (a.get("class") or "").split()
            if "mw-parser-output" in cls and not self.on:
                self.on = 1
                self.stack.append(("content", tag))                  # reading stops where the article's text ends
                return
            if not self.on or tag in ("br", "img", "meta", "link", "wbr", "hr", "input"):
                return
            if self.skip or tag in ("style", "script", "sup", "table", "figure") or any(c in cls for c in _W_NOT_READ) \
                    or a.get("role") == "navigation":
                self.skip += 1
                self.stack.append(("skip", tag))
                return
            self.stack.append(tag)
            if tag in ("h2", "h3", "h4"):
                self.head = (tag, [])
            elif tag == "li":
                self.items.append({"heads": dict(self.heads), "text": [], "parent": self.open[-1] if self.open else None})
                self.open.append(len(self.items) - 1)

        def handle_endtag(self, tag):
            if not self.on or tag in ("br", "img", "meta", "link", "wbr", "hr", "input"):
                return
            # close up to the matching tag: the parser does not repair a page's stray tags
            while self.stack:
                top = self.stack.pop()
                name = top[1] if isinstance(top, tuple) else top
                if isinstance(top, tuple) and top[0] == "content":
                    self.on = 0
                    self.stack.clear()
                    break
                if isinstance(top, tuple):
                    self.skip -= 1
                elif name in ("h2", "h3", "h4") and self.head:
                    text = re.sub(r"\s+", " ", "".join(self.head[1])).strip()
                    self.heads = {k: v for k, v in self.heads.items() if k < name}
                    self.heads[name] = text
                    self.head = None
                elif name == "li" and self.open:
                    self.open.pop()
                if name == tag:
                    break

        def handle_data(self, data):
            if not self.on or self.skip:
                return
            if self.head is not None:
                self.head[1].append(data)
            elif self.open:
                self.items[self.open[-1]]["text"].append(data)

    p = P()
    p.feed(page)
    for it in p.items:
        it["text"] = re.sub(r"\s+", " ", "".join(it["text"])).replace("\u200f", "").strip()
    return p.items


def _wiki_date(text: str, lang: str, year: int, month: int | None) -> tuple[dict | None, str]:
    """The date an item opens with, and the rest of its text."""
    t = text.translate(_AR_DIGITS)
    if lang == "ar":
        m = _W_AR.match(t)
        if m:
            d1, d2, mon, rest = m.groups()
            return {"day": int(d1), "end_day": int(d2) if d2 else None, "month": _AR_MONTHS[mon]}, rest.strip()
        m = _W_AR_MONTH.match(t)
        if m:
            return {"day": None, "month": _AR_MONTHS[m.group(1)]}, m.group(2).strip()
    else:
        m = _W_EN[0].match(t)
        if m:
            d1, d2, mon, rest = m.groups()
            return {"day": int(d1), "end_day": int(d2) if d2 else None, "month": MONTHS[mon.lower()]}, rest.strip()
        m = _W_EN[1].match(t)
        if m:
            mon, d1, d2, rest = m.groups()
            return {"day": int(d1), "end_day": int(d2) if d2 else None, "month": MONTHS[mon.lower()]}, rest.strip()
        m = _W_EN_MONTH.match(t)
        if m:
            return {"day": None, "month": MONTHS[m.group(1).lower()]}, m.group(2).strip()
    return None, text


def _month_of(head: str | None, lang: str) -> int | None:
    if not head:
        return None
    h = head.strip().translate(_AR_DIGITS)
    if lang == "ar":
        for name, n in _AR_MONTHS.items():
            if h == name or h.startswith(name + " "):
                return n
        return None
    return MONTHS.get(h.split()[0].lower()) if h.split() else None


def wiki_entries(page: str, lang: str, year: int, url: str, title: str) -> tuple[list[dict], int]:
    """A year page → its entries, and the number of items left out because their
    day does not exist (31 February). An item with no day or month of its own
    and none from a heading is an entry of the year (precision: year), tagged
    with its heading ("Unknown dates", «تأسيسات»)."""
    import hashlib
    items = wiki_items(page)
    dates: dict[int, dict | None] = {}
    out, undated = [], 0
    for i, it in enumerate(items):
        h2 = it["heads"].get("h2", "")
        if not h2 or _W_SKIP.match(h2):
            continue
        sub = it["heads"].get("h3") or it["heads"].get("h4")
        if sub and _W_SKIP.match(sub):
            continue
        month = _month_of(sub, lang) or _month_of(h2, lang)
        got, rest = _wiki_date(it["text"], lang, year, month)
        if got is None and it["parent"] is not None and dates.get(it["parent"]):
            got, rest = dict(dates[it["parent"]]), it["text"]              # a date-only item's children
        dates[i] = got
        rest = rest.strip(" –—-:")
        if not rest or len(rest) < 12:
            continue                                                      # a date alone, or a stub
        if got and got.get("day") is None:
            entry = {"date": datetime.date(year, got["month"], 1).isoformat(), "precision": "month"}
        elif got:
            mo = got["month"]
            try:
                day = datetime.date(year, mo, got["day"])
            except ValueError:
                undated += 1
                continue
            entry = {"date": day.isoformat(), "precision": "day"}
            if got.get("end_day") and got["end_day"] > got["day"]:
                try:
                    entry.update(end=datetime.date(year, mo, got["end_day"]).isoformat(), end_precision="day")
                except ValueError:
                    pass
        elif month:
            entry = {"date": datetime.date(year, month, 1).isoformat(), "precision": "month"}
        else:
            entry = {"date": datetime.date(year, 1, 1).isoformat(), "precision": "year"}
        anchor = (sub or h2).replace(" ", "_")
        tags = ["deaths"] if _W_DEATHS.match(h2) else ["births"] if _W_BIRTHS.match(h2) else []
        if entry["precision"] == "year":
            tags = tags or [h2]
        key = f"{title}|{entry['date']}|{rest}"
        entry.update(id=f"{lang}:{year}:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16],
                     text=rest, url=f"{url}#{anchor}", date_text=it["text"][:80], file=title,
                     tags=tags + ([sub] if sub and not month and sub not in tags else []))
        out.append({k: v for k, v in entry.items() if v not in (None, "", [])})
    return out, undated


def read_wikipedia(key: str, from_dir: Path | None, pause: float = 3.0,
                   cache_root: Path | None = None) -> tuple[list[dict], dict]:
    """Every year page of one Wikipedia that exists, as entries. A page that
    does not exist (404) is skipped; any other refusal ends the run with what
    was read kept out of it (nothing is written unless the floor is met)."""
    import time
    import urllib.error
    import urllib.parse
    site = SITES[key]
    lang = site["lang"]
    info: dict = {"pages": 0, "pages_missing": 0, "days_that_do_not_exist": 0, "redirected": []}
    seen_pages: set[str] = set()
    entries: dict[str, dict] = {}
    cache = from_dir or ((cache_root or ROOT / "data" / "cache" / "wikipedia") / lang)
    cache.mkdir(parents=True, exist_ok=True)
    for pattern, years in site["titles"]:
        for y in years:
            title = pattern.format(y=y)
            f = cache / f"{title}.html"
            url = site["page"] + urllib.parse.quote(title)
            if f.exists():
                page, final = f.read_text(encoding="utf-8"), url
            elif from_dir:
                continue
            else:
                time.sleep(pause)
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": UA_WIKI})
                    with urllib.request.urlopen(req, timeout=90) as r:
                        page, final = r.read().decode("utf-8", "replace"), r.geturl()
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        info["pages_missing"] += 1
                        continue
                    raise
                f.write_text(page, encoding="utf-8")
                bronze.put(f"chron_{key}", page, "html", url=final)
            canon = re.search(r'<link rel="canonical" href="([^"]+)"', page)
            canon = canon.group(1) if canon else url
            if canon in seen_pages:
                info["redirected"].append(title)
                continue                                                  # a redirect to a page already read
            seen_pages.add(canon)
            got, undated = wiki_entries(page, lang, y, canon, title)
            info["pages"] += 1
            info["days_that_do_not_exist"] += undated
            for e in got:
                entries.setdefault(e["id"], e)
    return sorted(entries.values(), key=lambda e: (e["date"], e["id"])), info


def run(key: str, out: Path, from_file: Path | None, use_bronze: bool) -> int:
    site = SITES[key]
    label = f"chronology:{key}"
    try:
        if from_file:
            page = from_file.read_text(encoding="utf-8", errors="replace")
        else:
            req = urllib.request.Request(site["page"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                page = r.read().decode("utf-8", "replace")
    except Exception as e:                                       # noqa: BLE001
        fetchlib.event(label, "failed", why=f"{type(e).__name__}: {e}"[:200])
        print(f"{key}: not read ({type(e).__name__}); the file on disk is kept")
        return 1
    entries, odd = parse_palquest(page)
    return write(key, out, entries, {"not_understood": odd}, page if use_bronze else None)


def write(key: str, out: Path, entries: list[dict], facts: dict, page: str | None) -> int:
    site = SITES[key]
    label = f"chronology:{key}"
    try:
        fetchlib.check_floor(label, len(entries), site["floor"])
    except fetchlib.FetchRefused as e:
        print(str(e))
        return 2
    d = out / key
    d.mkdir(parents=True, exist_ok=True)
    if page is not None:
        bronze.put(f"chron_{key}", page, "html", url=site["page"])
    body = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries).encode("utf-8")
    tmp = d / "entries.ndjson.gz.tmp"
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(body)
    tmp.replace(d / "entries.ndjson.gz")
    (d / "site.json").write_text(json.dumps(
        {"key": key, "name": site["name"], "home_url": site["home_url"], "source": site["source"],
         **({"lang": site["lang"]} if site.get("lang") else {})},
        ensure_ascii=False, indent=1))
    if page is None and key == "passia":
        bronze.put(f"chron_{key}", body, "ndjson", url=site["page"])
    fetchlib.event(label, "ok", rows=len(entries), first=entries[0]["date"], last=entries[-1]["date"], **facts)
    print(f"{key}: {len(entries):,} events, {entries[0]['date']} to {entries[-1]['date']} · {facts}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sites", nargs="+", choices=sorted(SITES))
    ap.add_argument("--from-file", type=Path, help="palquest: parse a page already in hand instead of asking for it")
    ap.add_argument("--from-dir", type=Path, help="passia: parse the files already in this folder (with index.json); "
                                                  "wikipedia_*: parse the pages already in this folder")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--cache", type=Path, help="wikipedia_*: where fetched pages are kept, one folder per language "
                                               "(default data/cache/wikipedia); a page already there is not asked for again")
    ap.add_argument("--no-bronze", action="store_true")
    a = ap.parse_args()
    worst = 0
    for k in a.sites:
        if k == "passia":
            try:
                entries, info = read_passia(a.out, a.from_dir)
            except Exception as e:                                   # noqa: BLE001
                fetchlib.event("chronology:passia", "failed", why=f"{type(e).__name__}: {e}"[:200])
                print(f"passia: not read ({type(e).__name__}: {e}); the file on disk is kept")
                worst = max(worst, 1)
                continue
            worst = max(worst, write(k, a.out, entries, info, None))
        elif k.startswith("wikipedia_"):
            try:
                entries, info = read_wikipedia(k, a.from_dir, cache_root=a.cache)
            except Exception as e:                                   # noqa: BLE001
                fetchlib.event(f"chronology:{k}", "failed", why=f"{type(e).__name__}: {e}"[:200])
                print(f"{k}: not read ({type(e).__name__}: {e}); the file on disk is kept")
                worst = max(worst, 1)
                continue
            info["redirected"] = len(info["redirected"])
            worst = max(worst, write(k, a.out, entries, info, None))
        else:
            worst = max(worst, run(k, a.out, a.from_file, not a.no_bronze))
    return worst


if __name__ == "__main__":
    sys.exit(main())
