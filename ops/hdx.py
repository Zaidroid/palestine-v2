"""What the three HDX fetchers share: one way to read a dataset's own record on
the Humanitarian Data Exchange, and one way to write down what the publisher
says about its date and its licence.

HDX is a CKAN site and needs no key:

    https://data.humdata.org/api/3/action/package_show?id=<dataset-slug>

A dataset carries `dataset_date` (the period the contributor says the data
covers, written "[2015-06-01T00:00:00 TO 2015-06-01T23:59:59]"), its licence
(`license_id`, `license_title`, `license_url`), the contributing organisation,
the `dataset_source` (who made the data, which is often somebody else), and
its resources, each with its own `last_modified` (the day the file was last
replaced) and download URL.

THE VINTAGE. A register (one row per school, per village boundary, per barrier
segment) has no event date; what a reader needs is the date the publisher says
the register is as of. That is `dataset_date`, and it is what `vintage` holds
for a register. For a series that grows (WFP's prices) the useful date is the
day the publisher last replaced the file, the resource's `last_modified`.
Either way the four values travel together into the raw file's metadata:

    vintage             the date, YYYY-MM-DD
    vintage_basis       which HDX field it is, and what the other field says
    vintage_url         the dataset's page
    vintage_checked_at  when this fetch read it
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ops import fetchlib as fl

API = "https://data.humdata.org/api/3/action"
PAGE = "https://data.humdata.org/dataset/"

_RANGE = re.compile(r"\[\s*(\d{4}-\d{2}-\d{2})[T ][^\]]*?\bTO\b\s*(\d{4}-\d{2}-\d{2}|\*)")


def package(slug: str, timeout: int = 60) -> dict:
    doc = fl.get_json(f"{API}/package_show?id={slug}", timeout=timeout)
    if not doc.get("success") or not isinstance(doc.get("result"), dict):
        raise ValueError(f"HDX package_show({slug}) did not return a dataset")
    return doc["result"]


def search(query: str, rows: int = 100, timeout: int = 90) -> list[dict]:
    doc = fl.get_json(f"{API}/package_search?{query}&rows={rows}", timeout=timeout)
    if not doc.get("success"):
        raise ValueError("HDX package_search failed")
    return (doc.get("result") or {}).get("results") or []


def date_range(dataset_date: str | None) -> tuple[str | None, str | None]:
    """'[2015-06-01T00:00:00 TO 2015-06-01T23:59:59]' → ('2015-06-01', '2015-06-01').
    An open end ('TO *') is None."""
    m = _RANGE.search(dataset_date or "")
    if not m:
        return None, None
    return m.group(1), (None if m.group(2) == "*" else m.group(2))


def day(stamp: str | None) -> str | None:
    """'2021-06-10T09:47:11.782170' → '2021-06-10'."""
    s = str(stamp or "")[:10]
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


def resource(pkg: dict, *, name: re.Pattern | None = None,
             fmt: str | None = None) -> dict | None:
    """The first resource whose name matches, or whose format is `fmt`."""
    for r in pkg.get("resources") or []:
        if name is not None and name.search(r.get("name") or ""):
            return r
        if fmt is not None and (r.get("format") or "").lower() == fmt.lower():
            return r
    return None


def stamp(pkg: dict, res: dict | None, *, kind: str, checked_at: str | None = None,
          says: str | None = None) -> dict:
    """What the publisher says, for a raw file's metadata.

    kind = "register": vintage is the end of `dataset_date` (the as-of date).
    kind = "series":   vintage is the resource's `last_modified` (the last
                       replacement of the file); `data_through` carries the end
                       of `dataset_date`.
    `says` is appended to the basis: what the dataset's own description adds
    about its date, in the fetcher's words.
    """
    start, end = date_range(pkg.get("dataset_date"))
    modified = day((res or {}).get("last_modified")) or day(pkg.get("last_modified"))
    created = day(pkg.get("metadata_created"))
    page = PAGE + str(pkg.get("name"))
    if kind == "register":
        vintage = end or start
        if start and end and start != end:
            basis = (f"HDX dataset_date, the period the contributor gives for the register "
                     f"({start} to {end}); the file was last replaced on HDX on {modified}")
        elif vintage is not None and vintage == created:
            # the reference date is only the day of the upload: say so, rather
            # than let an upload day read as the date of a survey
            basis = ("HDX dataset_date, which is the day the dataset was put on HDX "
                     "(metadata_created)")
        else:
            basis = (f"HDX dataset_date, the day the contributor says the register is as of; "
                     f"the file was last replaced on HDX on {modified} (resource last_modified)")
        if vintage is None:
            vintage, basis = modified, ("HDX resource last_modified (the dataset carries no "
                                        "dataset_date)")
    elif kind == "series":
        vintage = modified
        basis = (f"HDX resource last_modified, the day the publisher last replaced the file; "
                 f"dataset_date says it covers {start} to {end or 'the present'}")
    else:
        raise ValueError(f"kind {kind!r}")
    if says:
        basis = f"{basis}; {says}"
    org = pkg.get("organization") or {}
    out = {
        "vintage": vintage,
        "vintage_basis": basis,
        "vintage_url": page,
        "vintage_checked_at": checked_at or datetime.now(timezone.utc).isoformat(),
        "hdx_dataset": pkg.get("name"),
        "hdx_title": pkg.get("title"),
        "dataset_date": pkg.get("dataset_date"),
        "hdx_created": pkg.get("metadata_created"),
        "resource_name": (res or {}).get("name"),
        "resource_url": (res or {}).get("url"),
        "resource_last_modified": (res or {}).get("last_modified"),
        "publisher": org.get("title"),
        "publisher_hdx_org": org.get("name"),
        "dataset_source": pkg.get("dataset_source"),
        "license_id": pkg.get("license_id"),
        "license_title": pkg.get("license_title"),
        "license_url": pkg.get("license_url"),
        "license_other": pkg.get("license_other") or None,
    }
    if kind == "series":
        out["data_from"], out["data_through"] = start, end
    return out


def refuse(label: str, why: str, dry: bool, **extra):
    """One ledger line, then the refusal. A dry run leaves no line: a rehearsal
    must not count as an attempt in the radar's streak."""
    if not dry:
        fl.event(label, "refused", why=why[:200], **extra)
    raise fl.FetchRefused(f"{label}: {why} — keeping the file already on disk")


def jsnum(text):
    """A number the way v1's JavaScript wrote it into JSON: parseFloat, and an
    integral value without a fraction (2, never 2.0). The databank compares a
    row's attrs as JSON text, so 2.0 against a held 2 would read as a revision
    of every such row."""
    if text is None:
        return None
    try:
        f = float(str(text).strip())
    except ValueError:
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return int(f) if f.is_integer() and abs(f) < 2 ** 53 else f
