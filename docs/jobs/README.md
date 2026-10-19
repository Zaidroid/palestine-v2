# Jobs for the DeepSeek harness

A job is one file in this folder, `JOB-NN-slug.md`, written by Claude (Fable) and taken by the DeepSeek harness on Zaid's Mac over SSH to main-server. The split is by cost: DeepSeek does bulk reading, per-article judgment, long fetch windows and research scans; Claude does schema, migrations, extractors, QA and the decisions packaged for Zaid.

## The loop

1. **Open.** Claude writes the brief: goal, inputs (exact commands/paths), output contract, acceptance checks, what not to do. Header `status: open`.
2. **Take.** DeepSeek sets `status: taken · <date>` in the header and works on a git worktree branch `job-NN-slug` (never on the serving branch; never `serve/`; never a service restart).
3. **Return.** DeepSeek writes `JOB-NN-RETURN.md` next to the brief, one page at most: what was done, the counts, where the files are, what failed, open questions. Header `status: returned`.
4. **Review.** Claude checks the return (diff, the tests, a 20-row sample against the quoted sources) and either loads it (a migration and loader that Zaid runs) or sends it back with named fixes. Header `status: merged` or `status: returned · fixes named`.

## Output contract (every job)

- Files, not database rows. A job writes under `data/raw/jobs/NN/` as NDJSON, one record per figure, each with `doc_id`, `published_at`, `publisher`, `url`, a `quote` of at most 300 characters that contains the number, `measure`, `value`, `unit`, `place`, `period`, `authority_named` (the body that produced the number, or null) and `confidence` (`sure` / `likely` / `unsure`).
- No inferred numbers. If the text does not say it, the record does not exist. "About", "more than", "nearly" go into `attrs.qualifier`, never into `value`.
- Duplicates grouped: the same figure on the same day from several outlets is one figure with several `doc_id`s.
- A summary table in the return: records by measure and year, and which measures have enough points for a series (at least 12 points over 2 years, or 24 over any span).

## The rules that do not move

- Read `docs/HANDOFF.md` §1 first: v1 at `/opt/stacks/palestine` is never developed in place; no data loss; the Telegram account is never used; `claim` is immutable; `.env` is never printed or committed.
- The database is read-only for a job unless the brief says otherwise. Ask the archive with `.venv/bin/python -m ops.ask_archive` (under a second a question; raw `to_tsquery` on Arabic returns nothing). A `body ILIKE` over `document` costs about a minute; use the index.
- Web reads respect robots and crawl delays; Al Jazeera is headline-only by its robots file.
- Any job longer than ten minutes runs detached with a log and a `DONE` marker (`setsid nohup … ; echo DONE >> log`), and checks `df -h /` first: stop below 20 GB free.
- Arabic that will be rendered or published is audited by Zaid before it renders; a job never publishes.
- Figures about lives (killed, injured, detained children) are reported with the publisher's wording in the quote; never rounded.

## Queue

| Job | Status | What |
|---|---|---|
| [JOB-01](JOB-01-water-gaza-series.md) | open | Gaza water figures 2010→2026 from the archive: a reviewed series |
| [JOB-02](JOB-02-health-facilities-places.md) | open | Health facilities by place and status over time, from ministry/WHO/OCHA statements |
| [JOB-03](JOB-03-pcbs-energy-tables-fuel-2012-2023.md) | open | PCBS Energy Tables: monthly fuel prices 2012→2023 transcribed from the PDFs |
| JOB-05 (to write) | — | The 1948–2000 UN reports (10,468 texts): yearly figures for refugees, casualties, demolitions |
| JOB-04 (to write) | — | Settlement units approved and outposts established, by month, 2010→2026 (regex first pass by Claude, judgment pass by DeepSeek) |
