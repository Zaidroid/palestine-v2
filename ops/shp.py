"""A shapefile read with the standard library — the .shp geometry and the .dbf
table, nothing else (no projection, no index).

WHY IT IS HERE AND NOT A DEPENDENCY. Three of HDX's West Bank registers (the
school list, the Mandate village boundaries, the Barrier) are published as
zipped ESRI shapefiles only. The serving host carries no GIS stack
(requirements.txt), and v1 read these files with a small JavaScript reader. A
fetcher that must reproduce what v1 stored has to read the bytes the way that
reader did, so this module follows it rule for rule:

  * a PolyLine with one part is a LineString, with several a MultiLineString;
  * a Polygon's rings are sorted the way that reader sorted them: a clockwise
    ring starts a polygon, every other ring is a hole and is attached to the
    first polygon that contains one of its points (or stands alone when none
    does). `first_ring()` returns what v1 called `coordinates[0]` (Polygon) or
    `coordinates[0][0]` (MultiPolygon) — the ring v1 averaged for a centroid;
  * a .dbf text cell is trimmed and an empty one is None; a number cell that
    does not parse is None; a deleted row is still a row (the reader paired
    table row i with shape i and never looked at the deletion flag).

ONE DELIBERATE DIFFERENCE: text is decoded with the encoding the publisher
declares in the .cpg file (UTF-8 for all three). v1's reader ignored the .cpg
and decoded every cell as Windows-1252, which is how 2,089 Arabic school and
locality names reached the databank as mojibake (ingest/databank.demojibake
repairs most of them on the way in; the ones holding the letter ف could never
be repaired, because its second UTF-8 byte, 0x81, has no Windows-1252
character to round-trip through).
"""
from __future__ import annotations

import io
import struct
import zipfile

POINT, POLYLINE, POLYGON = (1, 11, 21), (3, 13, 23), (5, 15, 25)


class ShapefileError(ValueError):
    """The bytes are not the shapefile they claim to be."""


# ── the table ────────────────────────────────────────────────────────────────

def _number(text: str):
    """A numeric cell, the way JavaScript's unary plus reads it: an integral
    value is an int (JSON writes 10111007, never 10111007.0)."""
    t = text.strip()
    if not t:
        return None
    try:
        f = float(t)
    except ValueError:
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return int(f) if f.is_integer() and abs(f) < 2 ** 53 else f


def read_dbf(raw: bytes, encoding: str = "utf-8") -> tuple[list[dict], dict]:
    """→ (rows, header). `header` carries the table's own last-update date
    (the day the publisher's software last wrote it), the field list, and how
    many rows carry the deletion flag."""
    if len(raw) < 33:
        raise ShapefileError("dbf: shorter than its own header")
    yy, mm, dd = raw[1], raw[2], raw[3]
    n_rows, header_len, rec_len = struct.unpack_from("<IHH", raw, 4)
    fields = []
    pos = 32
    while pos < header_len and raw[pos] != 0x0D:
        name = raw[pos:pos + 11].split(b"\x00", 1)[0].decode(encoding, "replace")
        fields.append((name, chr(raw[pos + 11]), raw[pos + 16]))
        pos += 32
    if not fields:
        raise ShapefileError("dbf: no fields")
    rows, deleted = [], 0
    for i in range(n_rows):
        start = header_len + i * rec_len
        rec = raw[start:start + rec_len]
        if len(rec) < rec_len or rec[0] == 0x1A:
            break
        deleted += rec[0] == 0x2A
        row, at = {}, 1
        for name, kind, length in fields:
            text = rec[at:at + length].decode(encoding, "replace")
            at += length
            if kind in "NFBM":
                row[name] = _number(text)
            elif kind == "L":
                t = text.strip().lower()
                row[name] = False if t in ("n", "f") else True if t in ("y", "t") else None
            else:                       # C, D and anything unknown: the text
                row[name] = text.strip() or None
        rows.append(row)
    return rows, {
        "last_update": (f"{1900 + yy:04d}-{mm:02d}-{dd:02d}"
                        if 1 <= mm <= 12 and 1 <= dd <= 31 else None),
        "fields": [f"{n}:{k}{ln}" for n, k, ln in fields],
        "rows_declared": n_rows, "rows_flagged_deleted": deleted,
    }


# ── the geometry ─────────────────────────────────────────────────────────────

def _ring_clockwise(ring: list) -> bool:
    n = len(ring)
    if n < 4:
        return False
    area = ring[n - 1][1] * ring[0][0] - ring[n - 1][0] * ring[0][1]
    for i in range(1, n):
        area += ring[i - 1][1] * ring[i][0] - ring[i - 1][0] * ring[i][1]
    return area >= 0


def _segment_contains(p0: list, p1: list, p2: list) -> bool:
    x20, y20 = p2[0] - p0[0], p2[1] - p0[1]
    if x20 == 0 and y20 == 0:
        return True
    x10, y10 = p1[0] - p0[0], p1[1] - p0[1]
    if x10 == 0 and y10 == 0:
        return False
    t = (x20 * x10 + y20 * y10) / (x10 * x10 + y10 * y10)
    if t < 0 or t > 1:
        return False
    return True if t in (0, 1) else (t * x10 == x20 and t * y10 == y20)


def _ring_contains(ring: list, point: list) -> int:
    """1 inside, -1 outside, 0 on the boundary."""
    x, y = point[0], point[1]
    contains = -1
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if _segment_contains(ring[i], ring[j], point):
            return 0
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            contains = -contains
        j = i
    return contains


def _ring_contains_some(ring: list, hole: list) -> bool:
    for p in hole:
        c = _ring_contains(ring, p)
        if c:
            return c > 0
    return False


def _parts_points(body: bytes) -> tuple[list[int], list[list[float]]]:
    n_parts, n_points = struct.unpack_from("<ii", body, 36)
    parts = list(struct.unpack_from(f"<{n_parts}i", body, 44))
    at = 44 + 4 * n_parts
    flat = struct.unpack_from(f"<{2 * n_points}d", body, at)
    return parts, [[flat[2 * i], flat[2 * i + 1]] for i in range(n_points)]


def _geometry(body: bytes) -> dict | None:
    kind = struct.unpack_from("<i", body, 0)[0]
    if kind == 0:
        return None
    if kind in POINT:
        x, y = struct.unpack_from("<2d", body, 4)
        return {"type": "Point", "coordinates": [x, y]}
    if kind in POLYLINE or kind in POLYGON:
        parts, points = _parts_points(body)
        rings = [points[a:b] for a, b in zip(parts, parts[1:] + [len(points)])]
        if kind in POLYLINE:
            return ({"type": "LineString", "coordinates": rings[0]} if len(rings) == 1
                    else {"type": "MultiLineString", "coordinates": rings})
        polygons, holes = [], []
        for ring in rings:
            (polygons.append([ring]) if _ring_clockwise(ring) else holes.append(ring))
        for hole in holes:
            for polygon in polygons:
                if _ring_contains_some(polygon[0], hole):
                    polygon.append(hole)
                    break
            else:
                polygons.append([hole])
        return ({"type": "Polygon", "coordinates": polygons[0]} if len(polygons) == 1
                else {"type": "MultiPolygon", "coordinates": polygons})
    raise ShapefileError(f"shp: shape type {kind} is not one this reader knows")


def read_shp(raw: bytes) -> list[dict | None]:
    if len(raw) < 100 or struct.unpack_from(">i", raw, 0)[0] != 9994:
        raise ShapefileError("shp: not a shapefile (file code is not 9994)")
    out, at = [], 100
    while at + 8 <= len(raw):
        _number_, words = struct.unpack_from(">ii", raw, at)
        body = raw[at + 8:at + 8 + 2 * words]
        if len(body) < 2 * words or len(body) < 4:
            raise ShapefileError(f"shp: record {len(out) + 1} is cut short")
        out.append(_geometry(body))
        at += 8 + 2 * words
    return out


def first_ring(geometry: dict | None) -> list | None:
    """The ring v1 averaged: `coordinates[0]` of a Polygon, `[0][0]` of a
    MultiPolygon."""
    if not geometry:
        return None
    c = geometry.get("coordinates") or []
    if geometry["type"] == "Polygon":
        return c[0] if c else None
    if geometry["type"] == "MultiPolygon":
        return c[0][0] if c and c[0] else None
    return None


# ── the zip HDX serves ───────────────────────────────────────────────────────

def read_zip(raw: bytes) -> dict:
    """A zipped shapefile → {"features": [...], "table": header, "encoding",
    "name", "prj"}. A feature is {"properties": row, "geometry": geometry}."""
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise ShapefileError(f"not a zip: {e}") from None
    names = z.namelist()
    shp = next((n for n in names if n.lower().endswith(".shp")), None)
    if shp is None:
        raise ShapefileError("the zip holds no .shp")
    stem = shp[:-4]
    by_lower = {n.lower(): n for n in names}

    def member(ext: str) -> bytes | None:
        n = by_lower.get((stem + ext).lower())
        return z.read(n) if n else None

    dbf = member(".dbf")
    if dbf is None:
        raise ShapefileError(f"{shp}: no .dbf beside it")
    cpg = (member(".cpg") or b"").decode("ascii", "replace").strip()
    encoding = {"utf-8": "utf-8", "utf8": "utf-8", "": "utf-8",
                "1252": "cp1252", "ansi 1252": "cp1252", "1256": "cp1256",
                "ansi 1256": "cp1256"}.get(cpg.lower(), cpg.lower())
    try:
        "".encode(encoding)
    except LookupError:
        raise ShapefileError(f"{shp}: the .cpg names an encoding Python does not know: {cpg!r}") from None
    try:
        geometries = read_shp(z.read(shp))
        rows, header = read_dbf(dbf, encoding)
    except (struct.error, IndexError) as e:      # a file cut short mid-record
        raise ShapefileError(f"{shp}: {type(e).__name__}: {e}") from None
    if len(rows) != len(geometries):
        raise ShapefileError(f"{shp}: {len(geometries)} shapes but {len(rows)} table rows")
    prj = (member(".prj") or b"").decode("ascii", "replace").strip()
    return {"name": shp.rsplit("/", 1)[-1], "encoding": encoding, "cpg": cpg or None,
            "prj": prj or None, "table": header,
            "features": [{"properties": r, "geometry": g}
                         for r, g in zip(rows, geometries)]}
