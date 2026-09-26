"""Write docs/audit-2026-09-25/plan/STATUS.md: every plan task, done or open, with its commit.

    python3 docs/audit-2026-09-25/plan/gen_status.py

After fixing a task: add the commit and the finding ids it closes to `C` (or to
`PARTIAL` with what is left), update the suite numbers in the header text, and
re-run. The task list itself is read from the NN-area.md files.

WARNING (2026-09-26): `C` below is behind STATUS.md — rows were recorded by hand
after 2026-09-25, and a re-run printed 59 done where STATUS.md held 144. Edit
STATUS.md by hand, or bring `C` up to date first.
"""
import json, re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLAN = REPO / "docs/audit-2026-09-25/plan"
idx = json.loads((PLAN / "_index.json").read_text())

C = {  # commit -> (short subject, finding ids)
    "74d914b": ("parser: closures, questions and forecasts no longer read as open",
                "F001 F005 F006 F002 F003 F019 F020 F021 F013 F022 F014 F023 F015 F024"),
    "d952350": ("route: G2 coverage, doubts for slow, direction reconciliation; exit closures always spoken",
                "F071 F318 F320 F011"),
    "932004f": ("belief: the both row is the worse direction; crowd never feeds incidents; a stranger cannot blind a channel",
                "F008 F016 F377 F012 F017"),
    "c530211": ("renderers: per-direction ages, honest not-found, no closure behind an unknown direction",
                "F009 F035 F044 F045 F046 F049 F050 F052 F053"),
    "1d5115c": ("renderers: crossings decayed vs no source; place_profile window, kind, anchor, age, failures",
                "F010 F055 F058 F059 F060"),
    "a348ccf": ("transport: bounded batches/bodies, tokens die with their key, PKCE required, SSE reset",
                "F078 F088 F087 F357 F359 F396 F402 F031"),
    "f650da8": ("rest: read paths never learn, crowd notes are not news, max_lag and note bounded",
                "F076 F081 F085 F075 F079 F077 F083"),
    "be66fb2": ("classifier 1.9.0: a reopening is not a closure; bounded regexes",
                "F039 F074"),
    "646746c": ("classifier: a re-read no longer duplicates closure observations", "F205"),
    "3d77f79": ("ingest: poller honours FloodWait resolving/downloading, fails with nothing resolved, atomic cursor",
                "F042 F224 F226 F218"),
    "f5fd58d": ("ingest: the v1 import cursor is its own and re-reads behind itself", "F007"),
    "6e47e60": ("databank: demolition ladder runs; indistinguishable copies kept; same-run conflicts; crashes isolated",
                "F028 F029 F135 F137"),
}
PARTIAL = {
    "F322": ("d952350", "Hebrew/Latin-only names dropped from `passes`; the settlement LABEL needs a data source (HANDS-NEEDED §5)"),
    "F068": ("f650da8", "read paths and resolve_for_state_kind no longer learn; resolve_place still defaults learn=True (08-gazetteer)"),
    "F031": ("a348ccf", "code now matches PARTNER-API (one revocation, 90-day refresh); the doc itself not re-read"),
}
done = {}
for c, (_, ids) in C.items():
    for f in ids.split():
        done.setdefault(f, c)

rows_by_area, totals = [], {"done": 0, "partial": 0, "open": 0}
for a in idx:
    text = (PLAN / a["file"]).read_text()
    tasks = re.findall(r"^### ([A-Z]+-\d+) · (F\d+) · (\w+) · [\w-]+\n\*\*(.+?)\*\*", text, re.M)
    vtasks = re.findall(r"^- \*\*([A-Z]+-V\d+) · (F\d+) · (\w+)\*\* — (.+?) — `", text, re.M)
    out = []
    for tid, fid, sev, title in tasks:
        if fid in PARTIAL:
            st, com, note = "partial", PARTIAL[fid][0], PARTIAL[fid][1]
        elif fid in done:
            st, com, note = "done", done[fid], ""
        else:
            st, com, note = "open", "", ""
        totals[st] += 1
        out.append((tid, fid, sev, st, com, title[:95], note))
    vdone = [(tid, fid, sev, done[fid], title[:95]) for tid, fid, sev, title in vtasks if fid in done]
    rows_by_area.append((a, out, vdone, len(vtasks)))

L = ["# Status of the audit fix plan — what is done, what is open",
     "",
     "Generated 2026-09-25 from the plan files and the fix commits on `claude/system-analysis-complete-mzpu2r`.",
     "Read this before starting an area: a task marked **done** is fixed and has a test that failed before the change;",
     "do not redo it. **partial** says what is left. Everything is proven only on the schema-only local database and",
     "offline fixtures — none of it is live until `HANDS-NEEDED.md` is worked through on main-server.",
     "",
     f"**Confirmed tasks: {totals['done']} done · {totals['partial']} partial · {totals['open']} open** "
     f"(of {sum(totals.values())}). Local suite: 927 passed / 99 failed; the 99 are the baseline's production-data "
     "and live-API tests (the baseline was 821 / 99).",
     "",
     "## Commits",
     "",
     "| commit | what | findings |", "|---|---|---|"]
for c, (subj, ids) in C.items():
    L.append(f"| `{c}` | {subj} | {ids} |")
L += ["", "Docs-only commits: `d273191` (the plan), `7188a2f`, `81d0b1f` (rollout runbook), and the commit that adds this file.", ""]
L += ["## Per area", ""]
for a, out, vdone, nv in rows_by_area:
    n_done = sum(1 for r in out if r[3] == "done")
    n_part = sum(1 for r in out if r[3] == "partial")
    L += [f"### {a['n']:02d} · {a['title']} — `{a['file']}`",
          "",
          f"{n_done} done · {n_part} partial · {len(out) - n_done - n_part} open of {len(out)} confirmed; "
          f"{len(vdone)} of {nv} verify-first done.", ""]
    if out:
        L += ["| task | finding | severity | status | commit | title |", "|---|---|---|---|---|---|"]
        for tid, fid, sev, st, com, title, note in out:
            t = title.replace("|", "\\|") + (f" — *{note}*" if note else "")
            L.append(f"| {tid} | {fid} | {sev} | **{st}** | {('`'+com+'`') if com else ''} | {t} |")
    for tid, fid, sev, com, title in vdone:
        L.append(f"| {tid} | {fid} | {sev} | **done** | `{com}` | {title.replace('|', '/')} |")
    L.append("")
L += ["## Refuted findings that were still worth a change",
      "",
      "- F042 (FloodWait during media download): refuted as a wire storm (Telethon's own flood guard), but the batch was",
      "  stored without media and the cursor moved past it; fixed in `3d77f79`.",
      ""]
(PLAN / "STATUS.md").write_text("\n".join(L) + "\n")
print(totals)
for a, out, vdone, nv in rows_by_area:
    print(a["file"], sum(1 for r in out if r[3] != "open"), "/", len(out))
