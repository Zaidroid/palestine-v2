You are taking JOB-08 for the Palestine databank on main-server (SSH: zaid@main-server).

Read, in this order, before anything else:
1. /home/zaid/palestine-v2/docs/jobs/README.md — the protocol and "the rules that do not move"
2. /home/zaid/palestine-v2/docs/jobs/JOB-08-lake-second-pass.md — the brief
3. /home/zaid/palestine-v2/docs/jobs/JOB-06-RETURN.md, section "Claude's review" — why the pilot's 87 kept tree rows became 45, and the three stories that were wrong
4. /home/zaid/palestine-v2/db/reference/job06_review.yaml — the worked example: the exact shape of families A and B, and how drops are written

Setup:
- git -C /home/zaid/palestine-v2 worktree add /home/zaid/jobs/job-08-lake-second-pass -b job-08-lake-second-pass batch0-honest-serving
- On that branch set the brief's header to `status: taken · <date>`. The brief, the return and any scripts you write are committed there.
- The data is NOT in the worktree. Read inputs from and write outputs to /home/zaid/palestine-v2/data/raw/jobs/06/ and /home/zaid/palestine-v2/data/raw/jobs/08/ (absolute paths). Run Python as /home/zaid/palestine-v2/.venv/bin/python with /home/zaid/palestine-v2 as the working directory.

Run:
- `df -h /` first; stop below 20 GB free. Detached with a log and a DONE marker. At most 6 workers. `touch data/raw/jobs/08/STOP` ends the run at the next family boundary.
- Families in order A → K. Each finished family is a stop point: write its four files, update the table in docs/jobs/JOB-08-RETURN.md, commit.
- First return by 2026-10-21 08:00 UTC with whatever families are done. Continue the next night. Final by 2026-10-22 08:00 UTC. Delete the corpus dump when the job ends; keep the lake.

The bar is the brief's ten points. "Figure and subject match the family" is NOT a keep: a row is an event or a tally, one row per event across outlets, one row per tally dated at its period, and the dot decides by magnitude and sentence.

Do not: write to the database (reads only, one server-side cursor for the dump); touch serve/ or any service; publish anything; delete the lake or anything under data/raw/jobs/06.

When you hand back, give Zaid one paragraph: the families returned, kept rows and clusters per family, each family's self-check result, and what you could not do.
