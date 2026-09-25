# Plan 11 · Operability: watchdog, alerts, backups, shell steps, systemd units

Phase 4 — Silent failures: ingestion, feeds, operations. Read `00-README.md` first (setup, rules, the per-task loop).

## Scope

- **Files you may edit:** `ops/watchdog.py`, `ops/watchdog.sh`, `ops/heartbeat.py`, `ops/with-heartbeat.sh`, `ops/alert.py`, `ops/notify.py`, `ops/backup.py`, `ops/backup.sh`, `ops/restore_test.py`, `ops/restore-test.sh`, `ops/maintain.sh`, `ops/maintain_due.py`, `ops/mcp-audit.sh`, `ops/classify-news.sh`, `ops/crowd-refresh.sh`, `ops/databank-sync.sh`, `ops/ingest-external.sh`, `ops/ingest-gaza.sh`, `ops/ingest-palhub-roads.sh`, `ops/learn-checkpoints.sh`, `ops/measure-accuracy.sh`, `ops/rollup.sh`, `ops/sync-checkpoints.sh`, `ops/sync-valhalla-ip.sh`, `ops/repair_generations.py`, `ops/minimax_alarm.py`, `ops/systemd/*.service`, `ops/systemd/*.timer`, `ops/systemd/*.d/*.conf`, `tests/test_watchdog.py`, `tests/test_maintain_due.py`, `tests/test_ops_hardening.py`, `db/migrate.sh`, `ops/gap_radar.py`, `ops/asof_harness.py`, `ops/evidence.py`, `ops/fetchlib.py`, `ops/fetch_ooni.py`, `ops/fetch_ioda.py`, `ops/v1_liveness.py`, `ops/v1_field_health.py`, `ops/pipeline_report.py`, `ops/repair_identity.py`, `ops/repair_conflict_region.py`
- **Tests to run after every task:** `tests/test_watchdog.py tests/test_maintain_due.py tests/test_ops_hardening.py` (with the local DB sourced), then the full suite once at the end of the file.
- **Area rules:** Silence is failure: every shell step must be able to fail (set -euo pipefail; no `|| echo`), a crash and a found fault must have different exit codes, every unit that can fail has OnFailure=, TimeoutStartSec matches the real duration. Unit-file changes do not reach systemd until Zaid copies them — list each in your report as a HANDS item with the exact copy/daemon-reload commands. The unattended maintainer's privileges (maintain.sh) are Zaid's decision: narrow what code can narrow and put the rest in the report.

- Confirmed tasks: 16 · verify-first tasks: 21 · refuted (skip): 2

- Findings located in these files belong here too (fix them through the files you may edit, or with a NEW migration in your range — never edit an applied migration): `db/migrate.sh`, `db/tuning.sql`, `docker/compose.yml`, `ops/gap_radar.py`, `ops/asof_harness.py`, `ops/evidence.py`, `ops/fetchlib.py`, `ops/fetch_*.py`, `ops/v1_*.py`, `ops/pipeline_report.py`, `ops/replay_snapshots.py`, `ops/snapshot_inputs.py`, `ops/vault_snapshots.py`, `ops/source_scout.py`, `ops/route_coverage_measure.py`, `ops/reconcile_migrations.py`, `ops/repair_*.py`, `ops/backfill_stable_keys.py`

## A. Confirmed tasks (independently verified — do these first, in order)

### OPS-01 · F063 · high · security
**The unattended maintainer is an internet-reading agent with --dangerously-skip-permissions and a wildcard root sudo path on the production host**

- **Where:** `ops/maintain.sh:155`
- **What goes wrong:** A dataset description or licence page on a scouted catalog embeds instructions; the agent, told to read licences at the source with no permission prompts, follows them: `cat .env` into the digest Fawwaz reads aloud, exfiltrate the Telegram session, or `sudo -n systemd-run -- /bin/sh -c ...` for root. The playbook's 'hard rules' are prose, not enforcement.
- **Fix:** Run the maintainer as a dedicated user with a read-mostly DB role and no access to .env/session/.keys (pass only what it needs via a separate env file); replace --dangerously-skip-permissions with an explicit --allowedTools list; drop the sudo rule and implement retries as a static `palestine-v2-maintain-retry@.timer` template (or a root-owned timer that runs maintain_due) so no zaid->root path exists; sandbox the unit (ProtectSystem=strict, ReadWritePaths=repo, NoNewPrivileges=yes).
- **Evidence (audited code):**
```
ops/maintain.sh:153-156 runs `claude -p "$(cat ops/maintenance-prompt.md)" --model ... --dangerously-skip-permissions` as user zaid in the repo that holds `.env` (DB password, Telegram api_hash), `data/session/*.session` (the account's auth key) and `.keys/`. ops/maintenance-prompt.md step 1 instructs it to 'read its license AT THE SOURCE' for every scouted candidate and to read `data/source-scout.json` (a sweep of external catalogs). :126-130 `sudo -n /usr/bin/systemd-run --unit="$unit" --on-active=6h ... --description="... ($why)" /usr/bin/systemctl start ...` — the unit name and description vary per run, so the NOPASSWD rule that made this work live (DECISIONS F-03 'palestine-v2-maintain- …
```
- **Verifier's check:** Primary claim confirmed; the sudoers shape is inference. ops/maintain.sh:152-156 execs `claude -p "$(cat ops/maintenance-prompt.md)" --model ... --dangerously-skip-permissions` as User=zaid (ops/systemd/palestine-v2-maintain.service:8) with WorkingDirectory the repo (:9), which holds .env, data/session/ and .keys/ (.gitignore:1,20,60; ops/backup.py:30-33,238-247 confirm .env carries the DB password/api_hash and the session is 'account-takeover material'). ops/maintenance-prompt.md:53-55 tells the agent to read `data/source-scout.json` and 'read its license AT THE SOURCE' for every candidate sc …
- **Already in the release plan:** Accepted by design, not decided-against: ops/maintain.sh:13-17 ('--dangerously-skip-permissions is scoped by everything around it'); DECISIONS 2026-08-04 OPS (transcript treated as sensitive, flag kept); PLAN-09-21 F-03 + DECISIONS 2026-09-21 F-03 (the `sudo -n systemd-run --on-active=6h` retry was designed and proved live); PLAN-09-24 §7 P2-A.2 extends the same 'maintainer pattern' to a nightly headless run; docs/SECURITY-REVIEW.md does not mention the maintainer
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-02 · F064 · high · correctness
**mcp-audit.sh hands OK_EXIT_CODES to the audit process instead of the wrapper: every critical night is recorded as a failed job, and the unit lacks SuccessExitStatus so it fires a second alarm**

- **Where:** `ops/mcp-audit.sh:16`
- **What goes wrong:** The nightly audit finds one critical (its designed exit 1): ops.mcp_accuracy_audit raises its own alarm (:492), systemd fires OnFailure (a second push), the heartbeat row gets `consecutive_failures+1, last_error='exited 1'`; 27 h later (86400+10800) status flips to `failing` and the watchdog raises `watchdog:job:mcp-audit` (a third alarm) and /health shows a job failing and `jobs_ok` off by one until an audit night with zero criticals.
- **Fix:** `export OK_EXIT_CODES=1` before the exec (as watchdog.sh does) and add `SuccessExitStatus=0 1` to palestine-v2-mcp-audit.service; add a test that every script setting OK_EXIT_CODES has a unit with the matching SuccessExitStatus.
- **Evidence (audited code):**
```
ops/mcp-audit.sh:15-16 `exec with-heartbeat.sh mcp-audit 86400 10800 -- env OK_EXIT_CODES=1 .venv/bin/python -m ops.mcp_accuracy_audit` — `env` is the child command run by `"$@"` (with-heartbeat.sh:25); the wrapper's own `${OK_EXIT_CODES:-}` (:39) is unset. Compare ops/watchdog.sh:11 which `export`s it before exec. Reproduced with a stub: `with-heartbeat.sh mcp-audit 86400 10800 -- env OK_EXIT_CODES=1 sh -c 'exit 1'` recorded `--fail exited 1`. ops/systemd/palestine-v2-mcp-audit.service has no `SuccessExitStatus` (the watchdog unit has :16), so exit 1 also marks the unit failed. The script's own comment (:10-12) states the opposite intent.
```
- **Verifier's check:** Confirmed and reproduced. ops/mcp-audit.sh:15-16 execs `with-heartbeat.sh mcp-audit 86400 10800 -- env OK_EXIT_CODES=1 .venv/bin/python -m ops.mcp_accuracy_audit`; in ops/with-heartbeat.sh:25 `"$@"` runs `env ...` as the child, so OK_EXIT_CODES exists only in the child's environment and the wrapper's `${OK_EXIT_CODES:-}` at :39 is empty (the unit ops/systemd/palestine-v2-mcp-audit.service has no Environment=). Contrast ops/watchdog.sh:11 which exports it before exec. Scratchpad stub: `with-heartbeat.sh mcp-audit 86400 10800 -- env OK_EXIT_CODES=1 sh -c 'exit 1'` recorded `--fail exited 1`; the …
- **Already in the release plan:** PLAN-09-21 §11 2026-09-23 'F-86 done' (line 486) claims the OK_EXIT_CODES contract is in force — the code contradicts it; ops/watchdog.py:163-166 comment repeats the claim; PLAN-09-24 §7 P1-C.5 extends this audit (more exit-1 nights ahead)
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-03 · F065 · high · operability
**The Valhalla IP sync — the fixer for the routing outage that already happened — has no OnFailure and no heartbeat; a half-applied run leaves the API dead while the watchdog reads green**

- **Where:** `ops/systemd/palestine-v2-valhalla-ip.service:1`
- **What goes wrong:** wb-valhalla restarts and moves 172.22.0.4 -> .5. The 15-minute timer runs: .env is rewritten to .5, then `sudo -n` fails (sudoers edited, or systemctl returns non-zero) -> unit exits 1 -> journal only. The API process still holds .4 -> /v2/route and can_i_travel return 503/'routing unavailable' (the 2026-08-07 eleven-hour outage, DECISIONS 283) while the watchdog's valhalla row probes .5 from .env and reports `ok — valhalla 3.x`. Nothing alarms; /health is ok.
- **Fix:** Add `palestine-v2-valhalla-ip.service.d/onfailure.conf`; run the script through `with-heartbeat.sh valhalla-ip 900 1800` and add the entry to EXPECTED_JOBS (test_watchdog's script/registry test then covers it); restart first and rewrite .env only on success (or expose the URL the API process actually holds in /health and have routing_check compare the two).
- **Evidence (audited code):**
```
ops/systemd/palestine-v2-valhalla-ip.service is 9 lines with no `OnFailure=` and no drop-in directory (the only non-template unit without one; HANDOFF.md:62 claims 'on all twelve units'). ops/sync-valhalla-ip.sh is not wrapped in with-heartbeat.sh and `valhalla-ip` is absent from EXPECTED_JOBS (ops/watchdog.py:130-170). The script rewrites .env (:32-34) BEFORE `sudo -n systemctl restart palestine-v2-api.service` (:35) and its own comment (:12) says the restart is what makes the API read the new value. ops/watchdog.routing_check :598-665 judges `env_value('VALHALLA_URL')`, i.e. the .env file, not the URL the running API process holds.
```
- **Verifier's check:** Confirmed. ops/systemd/palestine-v2-valhalla-ip.service is 9 lines with no OnFailure= and there is no palestine-v2-valhalla-ip.service.d/ (ls ops/systemd); `grep -L OnFailure` plus the .d listing shows it is the only non-template unit with OnFailure nowhere, while docs/HANDOFF.md:62 claims 'on all twelve units'. ops/sync-valhalla-ip.sh:13-35 is not wrapped in with-heartbeat.sh (grep over ops/*.sh) and `valhalla-ip` is absent from EXPECTED_JOBS (ops/watchdog.py:148-181). The script rewrites .env at :32-34 BEFORE `sudo -n systemctl restart` at :35, and with `set -uo pipefail` (no -e) a failed su …
- **Already in the release plan:** DECISIONS 2026-08-07 ROUTING WAS DEAD ELEVEN HOURS (created the script and timer); PLAN-09-21 §11 2026-09-23 F-86 (watchdog judges the serving layer's URL); PLAN-09-24 §4 R5 + §7 P1-C.1 (/health omits the valhalla family) — adjacent; the unit's missing OnFailure/heartbeat and the rewrite-before-restart order are not filed
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-04 · F066 · high · operability
**A watchdog crash and a watchdog that found a fault are the same exit code, so the watchdog cannot be watched for crashing**

- **Where:** `ops/watchdog.py:817`
- **What goes wrong:** Postgres restarts at 03:00 and `job_checks()` raises psycopg.OperationalError before any check runs -> traceback, exit 1 -> systemd records success, the wrapper cannot beat (DB down) so nothing changes -> when the DB returns, the next run beats ok even if a later check (routing_check json shape, an import in minimax_alarm) keeps raising every 10 minutes: heartbeat `watchdog` reads ok, G3.8 stays green because measure_cadence ran before the crash, no alarm is raised or resolved, /health shows jobs ok, and every real fault for the duration is silent.
- **Fix:** Return a dedicated code for 'fault found' (e.g. 3) at :817; set `SuccessExitStatus=0 3` in the unit and `OK_EXIT_CODES=3` in watchdog.sh; wrap the body of main() in try/except that prints the traceback, best-effort `raise_alert('watchdog:self', repr(exc))` and returns 1 (so systemd OnFailure and the wrapper's --fail both fire). Add a test that monkeypatches job_checks to raise and asserts main() != 3 and != 0.
- **Evidence (audited code):**
```
ops/watchdog.py:816-817 `if faults: ... return 1` while any uncaught exception in main() (:776-820 has no try/except; e.g. `jobs = job_checks()` :782 raises when the DB is unreachable, `r.json().get("version")` :654 raises on a non-dict body) also exits 1. ops/watchdog.sh:11 `export OK_EXIT_CODES=1`; ops/with-heartbeat.sh:39-47 treats rc 1 as ok and writes a SUCCESS beat; ops/systemd/palestine-v2-watchdog.service:16 `SuccessExitStatus=0 1` so OnFailure never fires. Reproduced in this checkout with a stub heartbeat: `OK_EXIT_CODES=1 with-heartbeat.sh watchdog 600 900 -- python3 -c 'raise RuntimeError(...)'` printed the traceback and then `-m ops.heartbeat watchdog --interval 600 --grace 900` …
```
- **Verifier's check:** Confirmed. ops/watchdog.py:776-819 main() has no try/except; :782 `jobs = job_checks()` -> :370 `_q(JOB_SQL)` -> :315 psycopg.connect raises OperationalError uncaught; :654 `r.json().get("version")` is guarded only by `except ValueError` (:655), so a JSON array body raises AttributeError; :728 `from ops.minimax_alarm import safe_check` is an unguarded import. Any of these -> Python traceback, exit 1 — identical to :815-817 `if faults: return 1`. ops/watchdog.sh:11 `export OK_EXIT_CODES=1`; ops/with-heartbeat.sh:38-45 then writes a SUCCESS beat for rc 1; ops/systemd/palestine-v2-watchdog.servic …
- **Already in the release plan:** DECISIONS 2026-08-01 P3.1 (SuccessExitStatus=0 1 chosen deliberately); DECISIONS 2026-08-17 MAINTENANCE (the nine-day silent traceback) — symptom fixed, the exit-code aliasing is not filed in PLAN-09-24 §4/§7/§11 or HANDS; PLAN-09-24 §7 P1-C.1 (/health evaluates every family) is adjacent only
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-05 · F272 · medium · operability
**OnFailure alarms have no dedup or rate limit — a 2-minute timer that keeps failing pushes 30 notifications an hour**

- **Where:** `ops/alert.py:221`
- **What goes wrong:** v1's checkpoints.db becomes unreadable at 02:00 (permissions after a v1 redeploy): sync-checkpoints fails every 2 minutes -> 30 ntfy pushes/hour, 60 ledger lines/hour, until morning; the phone gets muted, and the next unrelated critical arrives into a muted channel — the failure every docstring in ops/ names.
- **Fix:** In alert.main for unit alarms: suppress delivery (still record) when the same unit raised within N minutes and mark the record `suppressed_after`; or make unit failures conditions keyed `unit:<name>` that the next successful heartbeat (or an OnSuccess= hook) resolves.
- **Evidence (audited code):**
```
ops/alert.py:207-222 — for a bare unit argument `raise_alert(a.unit, a.reason)` is unconditional (no `_already_open`, no window); raise_alert :57-58 appends a line, :67 `_notify(...)` pushes, :87-88 appends a receipt. Only the watchdog (:802) and the audit (:489) dedup. checkpoints.timer/crowd.timer fire every 2 min, news/palhub every 5; the 18:04 re-read loop (HANDS §8: 'the next tick starts over') is one such storm.
```
- **Verifier's check:** Confirmed. ops/alert.py:207-222: with a bare unit argument main() falls through to :221 `raise_alert(a.unit, a.reason)` unconditionally — no `_already_open`, no window; raise_alert :57-58 appends a record, :67 `_notify` pushes (ops/notify.py:212-260 has no dedup), :87-88 appends a receipt. Only ops/watchdog.py:802 and ops/mcp_accuracy_audit.py:489 dedup. ops/systemd/palestine-v2-alert@.service:1-8 has no rate limit, and each instance name is per failing unit, so the default StartLimitBurst never engages at a 2-min cadence. palestine-v2-checkpoints.timer:6 and crowd.timer:6 `OnUnitActiveSec=2mi …
- **Already in the release plan:** ops/alert.py:94-107 (resolve docstring) decides OnFailure alarms are events that wait for --clear; DECISIONS 2026-09-21 F-03 ('the unit still fails, so OnFailure= still alarms'); HANDS-09-24 §8 / PLAN-09-24 §11 18:05 (the 900 s re-read loop, one alert because the run was killed by hand); no dedup or rate limit is filed anywhere
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-06 · F273 · medium · data-integrity
**The 'monthly' full bronze set is cut every ~8 days because the last-full reference is read from local staging that prune_local trims to 7, and increments start from the gpg blob's mtime so objects written during tar+encrypt land in no set**

- **Where:** `ops/backup.py:212`
- **What goes wrong:** Full sets on days 1, 9, 17, 25 (~750 MB each per DECISIONS 08-11) instead of one — ~2.2 GB/month more on a 15 GiB shared quota that filled on 08-25. A restore from remote of day 1 + increments misses the handful of raw payloads written during each full's encryption window; the claims that reference them (claim.raw_ref) restore, their bronze does not.
- **Fix:** Record `bronze_from` = the timestamp taken before `tar` starts in the manifest and cut the next increment from it; find the last full from the remote listing (`rclone lsf` + manifest) or a small marker file outside STAGING/20*; test both with a fake staging directory.
- **Evidence (audited code):**
```
ops/backup.py:207-221 `_last_full_bronze()` scans `STAGING.glob("20*/manifest.json")` (local only) for `bronze_kind == "full"`; :73 `LOCAL_KEEP = 7`; :196 `full = ref is None or _now().day == BRONZE_FULL_DAY`. After day 8 the day-1 full is pruned locally -> ref None -> a full is cut again; the docstring's quota arithmetic (:75, :182-184 '30 × 2 GB does not fit') assumes one full per month. :220 `best = ... blob.stat().st_mtime` (the .gpg, written after tar and encryption) and :201 `--newer-mtime=@{int(ref)}`: bronze files whose mtime falls between the start of `tar` and the end of `gpg` are excluded from that full and from the next increment. Bronze receives ~2,000 files/day (:571-576 commen …
```
- **Verifier's check:** Confirmed by replaying the code. ops/backup.py:207-221 `_last_full_bronze()` scans only local `STAGING.glob('20*/manifest.json')`; :73 `LOCAL_KEEP = 7`; :313-319 `prune_local()` keeps the last 7 sets and is called at :443 after each set is built; :196 `full = ref is None or _now().day == BRONZE_FULL_DAY`. A 40-night simulation of those exact functions (scratchpad verify/sim_backup.py) produced FULL sets on 10-01, 10-09, 10-17, 10-25, 11-01, 11-09 — one every 8 days, 6 in 40 nights — against the docstring's one-per-month design (:176, :187-189) and the quota arithmetic at :74-75/:182-184. Bound …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-07 · F274 · medium · data-integrity
**Backup pruning runs after the upload it must make room for, and the first-of-month rule pins every set from the nine hand-runs of 08-01 — the off-host copy died on quota and the local staging grows toward the disk-fault line**

- **Where:** `ops/backup.py:411`
- **What goes wrong:** Quota full -> every night: dump + tar + gpg succeed, set renamed final, upload raises, run fails (OnFailure push nightly), no remote or local pruning -> staging grows ~50-230 MB/night on the single NVMe; DISK_WARN_GB=25 already crossed on 09-07, DISK_FAULT_GB=10 follows -> Postgres, the collectors and the backups fail together, with the only off-host copy a month old. Hard rule 2 (no data loss) is currently a belief.
- **Fix:** Run prune_remote BEFORE upload (keep the newest REMOTE_KEEP plus ONE set per calendar month, never below a minimum of verified sets); move prune_local into a finally; make the status file's `ok`/age a watchdog dependency row ('backup-remote' stale > 36 h = fault) separate from the heartbeat; record in the ledger when the remote copy was last verified.
- **Evidence (audited code):**
```
ops/backup.py:407-411 `upload(set_dir, remote); uploaded.append(...); prune_remote(remote)` inside the try — when `rclone copy` raises on a full quota, prune_remote is never reached. :330 `keep = set(sets[-REMOTE_KEEP:]) | {s for s in sets if s[8:10] == "01"}` keeps every set dated the 1st (nine from 2026-08-01). :443 `"pruned_local": prune_local()` sits inside the status.update that follows the upload block, so a failed upload skips local pruning too. DECISIONS 2026-08-31: 'keep == every set; the purge list is empty and provably always has been', 'every night since fails googleapi 403 storageQuotaExceeded' (since 08-25); 2026-09-07: '20 sets, 4.3 GB ... root filesystem at 97% (16 GB free)'. …
```
- **Verifier's check:** The CODE defect is confirmed as described; the live premise is stale. ops/backup.py:407-411: `upload(set_dir, remote)` then `prune_remote(remote)` inside the same try, so a raise in upload (:309 rclone copy) skips pruning; :417-420 then raises 'every destination failed'. :330 `keep = set(sets[-REMOTE_KEEP:]) | {s for s in sets if s[8:10] == "01"}` — set names are `%Y-%m-%dT%H-%M-%SZ` (:344) so chars 8:10 are the day, pinning every set dated a 1st (DECISIONS.md:380 confirms nine hand-run 08-01 sets and 'keep == every set'). :443 `"pruned_local": prune_local()` sits in the status.update after th …
- **Already in the release plan:** DECISIONS 2026-08-31 (prune_remote never deleted; ordering bug) and 2026-09-07 (prune_local downstream too) — 'filed, not fixed'; DECISIONS 2026-09-22 MAINTENANCE — 'Backups are green again ... Hetzner Storage Box since 09-19 ... local pruning works again ... Disk is 174 GB free ... The Drive-quota and prune-ordering items of 08-31 and 09-07 are overtaken by the move'; PLAN-09-21 §1 (backups: Hetzner nightly since 09-19) and ZAID-8 (2026-09-24: nightly set ok, 190 MB to hetzner:); PLAN-09-24 §7 P1-C.6 covers key custody only; HANDOFF §2:51 still says gdrive (stale)
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-08 · F275 · medium · operability
**databank-sync.sh keeps six `|| echo` steps whose only reader is the weekly maintainer that has missed four of the last six Mondays — the OONI fetch this line says it is fixing can die silently again**

- **Where:** `ops/databank-sync.sh:27`
- **What goes wrong:** OONI changes its API on a Wednesday: `fetch_ooni` fails nightly, the loader reads the frozen file, floors pass (nothing shrank), the radar marks connectivity stale at severity 4, the Monday session dies on a spend cap — the 60-day 06-09 outage repeats with every unit green and no push.
- **Fix:** Count fetch failures as ingest-external.sh does and pass them in the heartbeat detail; add a watchdog row over `ops/fetch-events.ndjson` (a fetcher failing 3 consecutive nights = fault) and make gap_radar exit non-zero on a newly-stalled dataset, which the plan's P1-B.3 already asks for.
- **Evidence (audited code):**
```
ops/databank-sync.sh:15 gho-wash, :21 t4p, :27 ooni, :28 ioda, :38 gaza_crosscheck, :44 snapshot_inputs, :51 vault_snapshots, :56 gap_radar all end `|| echo "... failed ..." >&2` and the script exits with only the loader's rc (:58). :24-26 'v1's copy of it died on 2026-06-09 and nobody noticed for sixty days, so a silent failure here is the exact thing being fixed'. ops/gap_radar.py:457 `return 0` unconditionally. The radar is read by ops/maintenance-prompt.md step 1; DECISIONS 08-17/08-31/09-21 record the maintainer not running on 08-10, 08-24, 09-14, 09-21. HANDOFF §4: 'A shell step that ends || echo cannot fail'.
```
- **Verifier's check:** Confirmed. ops/databank-sync.sh lines 15 (gho-wash), 21 (t4p), 27 (ooni), 28 (ioda), 38 (gaza_crosscheck), 44 (snapshot_inputs), 51 (vault_snapshots), 56 (gap_radar) each end `|| echo "... failed ..." >&2`; only the loader at :30-31 is wrapped by with-heartbeat, and :58 `exit $rc` returns the loader's status alone, so the unit and its OnFailure= (palestine-v2-databank.service) never see a fetch failure and the heartbeat detail carries none. :24-26 is the OONI 'nobody noticed for sixty days' comment as quoted. ops/gap_radar.py:457 `return 0` unconditionally; `measure_fetch_health` (:288) does m …
- **Already in the release plan:** PLAN §7 P1-B.3 (radar leg only)
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-09 · F276 · medium · data-integrity
**The as_of vault's index files and manifest, and the partner-key store, are not in the backup set although ops/evidence.py says the vault is**

- **Where:** `ops/evidence.py:9`
- **What goes wrong:** The NVMe dies. The DB and bronze objects come back from Drive; `data/evidence/manifest.json` and every stable-id index do not, so `ops/asof_harness.py`/`replay_snapshots.py` cannot address a single vaulted day (the objects are content-addressed, the map is gone) and G-level as_of proofs are unrebuildable; every partner API key and OAuth client is gone, including the published test key whose value is in PARTNER-API.md.
- **Fix:** Add `data/evidence` (indexes + manifest) to archive_bronze's tar (or a fourth archive) and `.keys` to archive_secrets; make restore_test assert the manifest is present and its entry count matches; correct the evidence.py docstring.
- **Evidence (audited code):**
```
ops/evidence.py:9 '1. the VAULT (data/evidence) — ours, verified by sha256, in the backup set'; :30-31 `VAULT = ROOT/data/evidence/v1-snapshots`, `MANIFEST = ROOT/data/evidence/manifest.json`. ops/backup.py archives only `ROOT/data/bronze` (:192-203) and `.env` + `data/session` (:238-247); grep for 'evidence' in backup.py/restore_test.py finds only a comment. vault_snapshots.py:18 copies the 836 `stable-id-index.json` files 'hot and verbatim to data/evidence/v1-snapshots/' (~0.85 GB per DECISIONS 09-21) and the manifest maps (day, category) -> bronze object. `.keys/` (partner-keys.json, oauth-state.json; PLAN §4 R6) is in .gitignore and in no archive.
```
- **Verifier's check:** Confirmed. ops/evidence.py:9 states the vault is 'in the backup set'; :30-31 place it at data/evidence/v1-snapshots + data/evidence/manifest.json. ops/backup.py archives only `ROOT/data/bronze` (:192-203, tar of 'bronze') and `.env` + `data/session/*.session|*.json` (:238-247); `grep evidence ops/backup.py ops/restore_test.py` hits only the docstring at :184. ops/vault_snapshots.py:18-19 copies the 836 stable-id-index.json files 'hot and verbatim to data/evidence/v1-snapshots/' and ops/snapshot_inputs.py:43-44 writes data/evidence/v2-inputs + v2-manifest.json — none under data/bronze. ops/asof …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-10 · F345 · medium · data-integrity
**repair_generations.py's demolitions rule deletes every current row ingested since 2026-08-07 — re-running --apply today wipes the repaired generation**

- **Where:** `ops/repair_generations.py:86`
- **What goes wrong:** The demolitions dataset was superseded by ops/repair_identity.py and reloaded on/after 2026-08-08 (docstring lines 5-18, DECISIONS 2026-08-08), so every CURRENT demolitions row now has ingested_at >= 2026-08-07. An operator re-runs `python -m ops.repair_generations --apply` (the docstring still presents it as the repair for generation doubling): the dry-run line prints `dupes=<all current rows>` and --apply DELETEs the whole current demolitions generation — a hard-rule-2 violation with no sys_period trail, and no gate detects a deletion (see G6.5 finding).
- **Fix:** Bound the generation rule to a closed window (`ingested_at::date BETWEEN '2026-08-07' AND '2026-08-07'`) and make the script refuse to run when any row in the dataset carries an identity_key (the post-052 state), or retire the script to ops/retired/ with a one-line README; add a unit test on the SQL builder asserting the date predicate has both ends.
- **Evidence (audited code):**
```
line 55: "v1_demolitions_ocha_demolitions": "GENERATION:2026-08-07"; lines 83-86: SELECT o.observation_id FROM observation o WHERE o.dataset_id = %s AND upper_inf(o.sys_period) AND o.ingested_at::date >= '{cutoff}'; line 109: cur.execute(f"DELETE FROM observation o WHERE o.observation_id IN ({dup_sql})"). The predicate is open-ended (>= with no upper bound) and there is no guard that the run is the original one.
```
- **Verifier's check:** Confirmed in code. ops/repair_generations.py:55 maps v1_demolitions_ocha_demolitions to 'GENERATION:2026-08-07'; lines 81-86 build `WHERE o.dataset_id=%s AND upper_inf(o.sys_period) AND o.ingested_at::date >= '2026-08-07'`, which has no upper bound. Line 109 runs a hard `DELETE FROM observation`. Nothing guards it: there is no FK or trigger on observation (007, and test_no_data_loss.sql T3 asserts there is no delete trigger), no check that the run is the original one, and no identity_key or post-052 refusal. The dataset key is still v1_demolitions_ocha_demolitions (db/mappings/demolitions.yaml …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-11 · F277 · medium · test-gap
**The weekly restore test never restores bronze or the full+increment chain — only the DB dump is exercised — and a checksum failure leaves the downloaded remote copy behind**

- **Where:** `ops/restore_test.py:120`
- **What goes wrong:** The 08-11 gzip-magic class of bug, or the increment-boundary gap above, corrupts the chain: every Sunday prints 'PASS — the backup restores, exactly, hypertables intact' because 30 tables of rows match, while the raw layer that makes them re-derivable cannot be rebuilt from the remote — discovered on the day the disk is gone.
- **Fix:** In restore_test, decrypt and extract the newest full plus every later increment into a temp dir and assert (a) object count >= the manifest's, (b) a random sample of 50 claim.raw_ref paths from the restored DB exist and hash correctly; move the `.remote-*` rmtree into a finally.
- **Evidence (audited code):**
```
ops/restore_test.py:118-147 `restore()` decrypts only `db.dump.gpg` (:120) and pg_restores it; bronze.tar.zst.gpg and secrets.tar.gpg are only sha256-compared (:107-115). The backup docstring (:40-46) says bronze 'makes silver/gold reproducible' and DECISIONS 285 built the incremental chain on it, yet no path ever extracts one full + N increments. :243-246 returns 1 on a checksum failure BEFORE the `.remote-*` cleanup at :252-256 (whose comment says a leftover copy 'accumulates one full set per weekly run on the same disk').
```
- **Verifier's check:** Confirmed. ops/restore_test.py:118-147 `restore()` decrypts only `set_dir / 'db.dump.gpg'` (:120) and pg_restores it; bronze.tar.zst.gpg and secrets.tar.gpg are touched only by `verify_checksums` (:107-115). `grep bronze_kind ops/restore_test.py` finds nothing although ops/backup.py:189-190 says 'ops/restore_test.py reads that rather than guessing', and backup.py:43 says bronze 'makes silver/gold reproducible'. No code path extracts a full plus increments. Ordering confirmed: `verify_checksums` failure returns 1 at :243-246 before the `.remote-*` rmtree at :252-256, and that rmtree sits inside …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-12 · F278 · medium · data-integrity
**sync-valhalla-ip.sh rewrites the single secrets file non-atomically every 15 minutes, and restarts the API forever if the VALHALLA_URL line is ever absent**

- **Where:** `ops/sync-valhalla-ip.sh:33`
- **What goes wrong:** Zaid removes VALHALLA_URL from .env to fall back to the code default (the watchdog's own comment says production once ran that way): from the next tick the public API restarts every 15 minutes (in-flight requests dropped, SSE subscribers reconnected, warm caches lost) with no alarm since the unit exits 0. Or: a truncation mid-write empties .env and every timer, the poller and the API lose the DB password and api_hash simultaneously.
- **Fix:** Write `.env.tmp` beside .env with `umask 077`, `mv -f .env.tmp .env`; append the line when `have` is empty; restart only when the file content actually changed (compare before/after); wrap in with-heartbeat (see the valhalla-ip finding).
- **Evidence (audited code):**
```
ops/sync-valhalla-ip.sh:32-34 `sed ... .env > "$tmp"; cat "$tmp" > .env; chmod 600 .env` — `>` truncates .env then copies; a kill or ENOSPC (the disk has been at 97 %, DECISIONS 09-07) between the two leaves an empty .env. :22 `have=$(grep -E '^VALHALLA_URL=' .env | cut -d= -f2-)` is empty when the line is missing, :24 then never matches, :32 sed substitutes nothing, :35 restarts the API — every 15 minutes, with `echo "valhalla moved: -> ..."` each time.
```
- **Verifier's check:** Confirmed by reading ops/sync-valhalla-ip.sh. :31-34 `tmp=$(mktemp)`, `sed ... .env > "$tmp"`, `cat "$tmp" > .env`, `chmod 600 .env` — the `>` redirection truncates .env before cat writes it; there is no write-to-temp-beside-and-rename, so a kill or ENOSPC between truncate and write leaves .env empty (DECISIONS.md:389 records the root FS at 97 % on 09-07). :22 `have=$(grep -E '^VALHALLA_URL=' .env | cut -d= -f2-)` is empty when the line is absent; :24 `[ "$want" = "$have" ]` then never matches; :32 `s|^VALHALLA_URL=.*|...|` substitutes nothing (no append path); :35 `sudo -n systemctl restart p …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-13 · F283 · medium · correctness
**Feed freshness ignores modality: palhub's quarantined checkpoint_flow rows keep the served checkpoint_flow feed 'ok' while the road-channel feed can be dead**

- **Where:** `ops/watchdog.py:281`
- **What goes wrong:** v1's road-channel monitor stops writing checkpoint_flow (a Telegram ban on v1's account, a parser regression) while palhub keeps posting. `checkpoint_flow` — the served open/closed field — reads age 3 m, status ok, in both the watchdog and /health for as long as the dependency check (1 h mtime on checkpoints.db) or the sibling kinds take to trip; if v1 still writes other kinds, the served feed stays dark and green indefinitely.
- **Fix:** Add `WHERE modality = 'assertion'` to CURRENT_SQL and CADENCE_SQL/CEILING_SQL (the (state_kind, observed_at DESC) index still serves them), or key feed rows by (state_kind, modality) and only judge the asserted one against FEED_COLLECTOR; pin with a test that a quarantined-only kind reads `silent`.
- **Evidence (audited code):**
```
ops/watchdog.py:281-286 CURRENT_SQL `SELECT state_kind, max(observed_at) ... FROM state_observation GROUP BY 1` and CADENCE_SQL :234-258 have no `modality` predicate. ingest/sources/palhub_roads.py:58 `STATE_KIND = "checkpoint_flow"`, :90 `MODALITY = "quarantined"`, written every 5 minutes (palhub-roads.timer) — 72,763 readings/week per PLAN §4 R3 that 'move nothing'. FEED_COLLECTOR maps checkpoint_flow to sync-checkpoints (:175).
```
- **Verifier's check:** Confirmed. ops/watchdog.py:281-287 CURRENT_SQL `SELECT state_kind, max(observed_at) ... FROM state_observation GROUP BY 1` and :234-257 CADENCE_SQL / :263-279 CEILING_SQL carry no modality predicate. ingest/sources/palhub_roads.py:58 `STATE_KIND = "checkpoint_flow"`, :90 `MODALITY = "quarantined"`, and :257-264 inserts into state_observation with that modality; palestine-v2-palhub-roads.timer:6 fires every 5 min; PLAN-2026-09-24-PUBLIC-RELEASE.md:60 confirms '72,763 readings in 7 days move nothing'. ingest/sources/checkpoints.py:22,257 and palhub_roads.py:84-86 confirm belief counts modality=' …
- **Already in the release plan:** PLAN-09-24 §4 R3 (72,763 palhub readings in 7 days move nothing) and §7 P1-A.3 'Silent-source flags: the watchdog's feed family gains per-source silence ... never again a source that dies unflagged' — would cover it if built per (source, modality); P1-A.1 (earn-out by value class) partially moots it; not filed as a modality bug
- **Fixable in a checkout without production:** no — write the change and a test, then list the main-server step in `HANDS-NEEDED.md`
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-14 · F284 · medium · operability
**A feed alarm is auto-resolved with a 'recovered' push when its collector degrades, although the feed is still silent**

- **Where:** `ops/watchdog.py:532`
- **What goes wrong:** checkpoint_status is silent for 3 h (alarm open). sync-checkpoints then fails twice on a locked SQLite -> status failing -> every checkpoint_* feed flips to collector_down -> six '🟢 recovered: watchdog:feed:checkpoint_*' pushes while nothing recovered. The collector heals, the feeds are still stale -> six fresh alarms. With an `unmonitored` collector the feed alarm is suppressed for good.
- **Fix:** In main(), exclude keys whose current row is `collector_down` from the resolve loop (keep the alarm open, no recovery push), and treat `unmonitored` as a fault for names in EXPECTED_JOBS.
- **Evidence (audited code):**
```
ops/watchdog.py:454 `healthy = {j["name"] for j in jobs if j["status"] == "ok"}`; :531-534 a stale feed whose collector is not in `healthy` becomes `status="collector_down", fault=False`; main() :806-811 resolves every open `watchdog:*` key not in `faulting` with 'check returned to within cadence' and alert.resolve :121 pushes '🟢 recovered'. A collector with status `failing`, `not_running`, `never_succeeded` or `unmonitored` (never a fault, :377) all drop out of `healthy`.
```
- **Verifier's check:** Core defect confirmed; the scenario's count is overstated. ops/watchdog.py:454 `healthy = {j["name"] for j in jobs if j["status"] == "ok"}`; :529-533 a stale feed whose collector is not in `healthy` becomes `status="collector_down", fault=False`; :800 `faulting` is built from faults only; :809-813 resolves EVERY open `watchdog:*` key not in `faulting` with 'check returned to within cadence', and ops/alert.py:121 pushes '🟢 recovered'. So an open `watchdog:feed:checkpoint_status` alarm is closed with a recovery push the moment sync-checkpoints degrades to failing/not_running/never_succeeded/unmo …
- **Already in the release plan:** no — new finding
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-15 · F285 · medium · operability
**A failed delivery is never retried and nothing ever proves the doorbell works — a dead ntfy token silences every alarm until someone runs --test by hand**

- **Where:** `ops/watchdog.py:772`
- **What goes wrong:** LifeOS rotates its ntfy token on a Tuesday. Wednesday 03:00 the poller dies: the ledger records `delivered:false, reason:'HTTP 403: ...'` once, the alarm stays open, no further push is attempted for the whole outage; the same for every later fault. Nobody learns the channel is dead until the next hand-run.
- **Fix:** Have the watchdog re-send open alarms whose latest receipt is undelivered (backoff, cap per day) and add a `dep:doorbell` row: fault when the last N receipts are undelivered or the weekly silent self-test (a scheduled `ops.alert --test`, silent priority) has no delivered receipt.
- **Evidence (audited code):**
```
ops/watchdog.py:772-773 `_already_open(key)` checks only that an alarm record exists; alert.open_alerts :163-178 ignores the receipt's `delivered` field, so an alarm whose push returned `HTTP 403` / `URLError` (notify.py:249-260) is 'open' and never re-sent. The token is read at call time from `/home/zaid/lifeos/state.json` (notify.py:99,195-199) owned by another project; ntfy is `deny-all` with per-user ACLs (README 'Alarm delivery'). No timer, watchdog row or test runs `ops.alert --test`; the only proof is manual (README, notify.py:6-7).
```
- **Verifier's check:** Confirmed. ops/watchdog.py:772-773 `_already_open` returns True whenever any open record with that unit exists; ops/alert.py:163-178 open_alerts() filters clear_marker/resolves/delivery_of and timestamps but never reads `delivered` (recorded only in the receipt line, :81-88), so an alarm whose push failed is 'open' and :802 skips re-raising it every run; nothing in ops/ re-sends. ops/notify.py:249-260 returns `HTTP 403`/`URLError` reasons rather than raising; :99 NTFY_TOKEN_FILE_DEFAULT `/home/zaid/lifeos/state.json` and :195-199 read it at call time; ops/systemd/README.md:60-80 ('Alarm delive …
- **Already in the release plan:** PLAN-09-21 F-04 (lines 169-173) and §11 2026-09-22 F-04 done (proof: one manual `ops.alert --test`, message id RdRXBQYOPdho); DECISIONS 2026-09-22 F-04 (token read at call time from lifeos/state.json); ops/systemd/README.md 'Alarm delivery' (proof is the manual --test); no retry or scheduled self-test filed
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

### OPS-16 · F286 · medium · operability
**The heartbeat records the attempt only after the job returns, so a job killed by TimeoutStartSec reads as 'not_running' (scheduler stopped) instead of 'failing' — the case that actually happens**

- **Where:** `ops/with-heartbeat.sh:25`
- **What goes wrong:** A classifier version bump: every news tick is killed at 900 s; 20 minutes later the watchdog raises `watchdog:job:classify-news not_running —` (empty detail, last_error NULL) and Fawwaz tells Zaid the scheduler stopped, while `systemctl list-timers` shows it firing every 5 minutes and journal shows 'result: timeout'.
- **Fix:** Add `ops.heartbeat <name> --attempt` (UPDATE last_attempt=now(), insert if absent, keep last_ok) and call it before `"$@"`; optionally trap TERM to write `--fail 'killed (timeout?)'`. Then a killed job reads `failing` with a reason.
- **Evidence (audited code):**
```
ops/with-heartbeat.sh:25 `"$@"` then :41-47 writes the beat or `--fail`; systemd's timeout SIGTERMs the whole cgroup so bash never reaches :41. ingest-external.sh writes its heartbeat only at :36/:42 (after all seven steps). The view (070:40-57) then reports `not_running` because last_attempt is stale, which migration 028 documents as 'the scheduler is not running it'. HANDS §8 / PLAN §11 18:05: the 1.8.0 re-read 'would have hit TimeoutStartSec=900 and rolled back in a loop'.
```
- **Verifier's check:** Confirmed and reproduced. ops/with-heartbeat.sh:25 runs `"$@"` and only afterwards (:43-48) calls ops.heartbeat; there is no trap (grep -c trap = 0) and ops/heartbeat.py has no `--attempt` mode (:108-123: only --interval/--grace/--detail/--fail), so last_attempt is written only after the job returns. systemd's start timeout SIGTERMs the whole cgroup (default KillMode=control-group); scratchpad simulation with a stub heartbeat: TERM to both the wrapper bash and its child -> wrapper rc=143, ZERO heartbeat calls (TERM to the child alone does reach :47 and records `--fail exited 143`, which is not …
- **Already in the release plan:** HANDS-09-24 §8 (TimeoutStartSec=3600 drop-in for news.service — a hand); PLAN-09-24 §11 2026-09-24 18:05/18:27 (the run killed at 18:04, 'would have hit TimeoutStartSec=900 and rolled back in a loop'); db/migrations/028:27-29,62-64 state the not_running/failing contract this breaks; the attempt-before-run gap itself is not filed
- **Fixable in a checkout without production:** yes
- **Done when:** a new test named after this task fails before the change and passes after; the area tests and the full suite show no new failures.

## B. Verify-first tasks (reported by one reader, not independently checked)

For each: reproduce it with a failing test first. If you cannot reproduce it, do NOT change code — add one line to `SKIPPED.md` with the id and why.

- **OPS-V01 · F329 · medium** — db/migrate.sh runs each file in one transaction, so 062 (ALTER TYPE ADD VALUE then use) cannot apply and a fresh database cannot be bootstrapped from db/migrations; version is recorded in a separate call and checksum drift only warns — `db/migrate.sh:75`
  - scenario: Restore-from-scratch (a new host, or the weekly restore test extended to schema): migrate.sh reaches 062 inside `psql -1`, Postgres raises `unsafe use of new value "district_mandate"`, the run aborts at 062 and 063-078 never apply. In the other direction, if the container blips between :75 and :76, the migration is applied but unrecorded; the next run re-executes a non-idempotent file (001-021 use …
  - suggested fix: Record the version inside the migration's transaction (wrap the file with BEGIN; ... INSERT INTO schema_migrations ...; COMMIT via a generated script), support a `-- migrate: no-transaction` header for files like 062 (run without -1, or split ADD VALUE into its own file), make checksum drift a hard refusal unless `--accept-drift <version> <reason>`, and add a `--fresh` CI job that applies 001-078 …
- **OPS-V02 · F240 · medium** — The as_of harness proves sys_period only on five fixed dates and silently skips a date the vault lacks, so it can exit 0 having claimed zero checks — `ops/asof_harness.py:86`
  - scenario: The vault loses (or never gains) the five sampled days — a vault_snapshots regression, a restore from an older backup — and the harness prints 'as_of: 0/0 claimed date-checks pass' and exits 0; every day after 2026-08-02, the days ops/snapshot_inputs.py adds nightly, is never proved at all.
  - suggested fix: Exit non-zero when `n_claimed == 0` or when any SAMPLE_DATE is absent from the vault; choose dates dynamically (the five newest vaulted days plus two fixed historical anchors) so the proof follows the evidence base; write the count of claimed checks into the report header the watchdog can read.
- **OPS-V03 · F139 · medium** — A dead v2-native upstream (T4P, OONI, IODA, GHO) never fails the nightly or pages: fetchers are `|| echo`, the loader loads yesterday's file, the gap radar writes JSON nobody alarms on — `ops/databank-sync.sh:21`
  - scenario: T4P's API returns 403 for a month: thirty green nights, `grew: {}`, the Gaza cumulative series' last day ages silently on the public API; the only reader of the radar is Monday's maintainer run, which DECISIONS 2026-09-21 records failing three weeks running.
  - suggested fix: Count fetch failures in databank-sync.sh and exit non-zero after two consecutive failed nights per feed (read ops/fetch-events.ndjson); let the watchdog treat gap-radar `stalled` datasets and fetch gaps of severity ≥ 4 as faults.
- **OPS-V04 · F241 · medium** — Dead supply lines never fail the nightly job or page; a missing v1 events file yields zero fetch-health rows; nothing watches the age of gap-radar.json or gaza-crosscheck.json — `ops/gap_radar.py:457`
  - scenario: gap_radar throws every night after a schema change: stderr gets one line, systemd records success (the heartbeat is on ingest.databank), /v2/databank/radar keeps serving a radar that ages a day at a time, the Monday maintainer reads a stale file, and 'zero dead supply lines' (G5) is asserted from silence. The 31-night v1 FAIL streaks in PLAN §4 R4 are the live instance.
  - suggested fix: gap_radar: exit 1 and raise_alert('gap-radar') when any fetch gap has fail_streak ≥ 3 or status stalled/missing, and report `v1_events: unreadable` as a severity-4 gap when the file is missing; in databank-sync.sh count the non-fatal failures and exit non-zero at the end (HANDOFF §4's 'count the failures and re-raise'); add data/gap-radar.json and data/gaza-crosscheck.json to the watchdog's raw-ar …
- **OPS-V05 · F186 · medium** — No per-step timeout: fuel_prices can consume the unit's 900 s and starve weather, connectivity, power and fires — `ops/ingest-external.sh:26`
  - scenario: Two outlets time out for an hour: fuel_prices alone takes ~10 minutes, power's 40 fetches push past 900 s, systemd kills the unit; weather, connectivity and fires never ran on that tick, the heartbeat is not written, an alert fires for the whole unit and the operator hunts in the wrong feed.
  - suggested fix: Wrap each step in `timeout -k 10 180 …` (per-step budget, named in the failure list), fetch feeds concurrently in fuel_prices, and in power.py skip body fetches for newsids whose window is already stored in attrs of the scheduled row.
- **OPS-V06 · F337 · medium** — reconcile_migrations.py marks a migration applied when its declared objects merely pre-exist from earlier migrations; 11 files (incl. 016, 033, 040, 041, 070) would be recorded on that alone, and CREATE FUNCTION can never verify — `ops/reconcile_migrations.py:216`
  - scenario: The 070 file is present on disk but was never run (or ran and rolled back at its UPDATE). `ops/reconcile_migrations.py` finds ops_heartbeat_status exists (from 028), prints `[ok] 070_retire_fuel_availability.sql 1 objects`, and inserts the ledger row; migrate.sh now believes fuel availability is retired, ops_heartbeat.retired_at does not exist, the watchdog's retired-kind check (watchdog.py:185) e …
  - suggested fix: Treat a name as proof only if this file is the FIRST in order to declare it (compute first_seen across the directory, as the probe does); for CREATE OR REPLACE VIEW / ALTER TABLE ADD COLUMN / DML-only files require a ledger-proofs.json entry (e.g. `SELECT count(*) FROM information_schema.columns WHERE table_name='ops_heartbeat' AND column_name='retired_at'` → 1; `SELECT pg_get_viewdef('state_kind_ …
- **OPS-V07 · F282 · medium** — The daemons have detection but no recovery: no WatchdogSec/sd_notify, so a hung poller or API event loop stays hung until a human reads the alarm — `ops/systemd/palestine-v2-poller.service:38`
  - scenario: A half-open TCP session after a router reboot: `_fetch_since` awaits forever, no beat, `telegram-poller not_running` after 15.5 min -> one push at 04:00; the news vertical is dark until someone wakes and runs `systemctl restart`, while a single automatic restart would have recovered it in the time the existing backoff policy already tolerates.
  - suggested fix: Add `WatchdogSec=900` (poller) / `WatchdogSec=300` (api) with `Type=notify` (or `NotifyAccess=all`) and call `sdnotify('WATCHDOG=1')` from beat()/_beat() when NOTIFY_SOCKET is set; wrap the per-channel fetch in `asyncio.wait_for(..., 120)`.
- **OPS-V08 · F290 · medium** — `/health` runs `max(observed_at) GROUP BY state_kind` over the whole state_observation hypertable on every call, and reads `state_current` for a retired feed — `ops/watchdog.py:281`
  - scenario: Postgres has no loose index scan for `max() GROUP BY`, so the (state_kind, observed_at DESC) index cannot answer this in O(kinds); every /health decompresses every daily chunk of state_observation. The endpoint is public, exempt from the limiter for local monitoring, and its cost grows without bound under the no-retention rule; the `feed_age_minutes` it reports is the retired fuel feed (PLAN §4 R5 …
  - suggested fix: Replace CURRENT_SQL with a per-kind ordered probe: `SELECT k.state_kind, (SELECT max(o.observed_at) FROM state_observation o WHERE o.state_kind = k.state_kind) AS latest FROM state_kind_config k` (each subquery becomes an index-ordered LIMIT 1 on the newest chunks), or maintain `state_kind_stats.last_observed_at` from the writers; drop the two fuel queries and `feed_age_minutes` (P1-C.1) so /healt …
- **OPS-V09 · F227 · medium** — The watchdog reads none of the heartbeat detail the poller writes (channels, channel_failures, flood_wait_seconds), so a permanently failing channel or a permanent throttle never alarms — `ops/watchdog.py:381`
  - scenario: One of 14 channels becomes private or is renamed: it fails every cycle, failures == 1 < len(entities), the beat is healthy, and the channel is dark indefinitely with the fact recorded in a column nothing consults. Likewise a FloodWait on every cycle (an account-level throttle) beats healthy every cycle.
  - suggested fix: In job_checks (or a new per-collector check), read detail for telegram-poller: fault when channel_failures > 0 for more than N consecutive beats, when channels < the configured count, or when flood_wait_seconds has been present on M consecutive beats; keep a per-channel last-claim timestamp in the detail and alarm on silence beyond that channel's measured p95 (P1-A.3).
- **OPS-V10 · F552 · low** — db/tuning.sql: max_worker_processes=8 is below TimescaleDB's requirement with a compression policy live; max_connections=20 against a connection-per-query API plus ~15 timers; slow-query log at 2000 ms hides 10× regressions of the 200 ms budget — `db/tuning.sql:13`
  - scenario: During the nightly window (databank + rollup + backup pg_dump + classifier tick) plus the dev API used for tests, connections exceed 20 and the production API's next `q()` fails with 'too many connections' → 500 on a checkpoint answer; the compression job cannot obtain a worker while parallel scans hold them and chunks stay uncompressed with only a log line. Effective values need `SHOW` on main-se …
  - suggested fix: Set max_worker_processes ≥ 21 (or lower timescaledb.max_background_workers to 4 and set max_worker_processes 12), raise max_connections to 40 with a small pool in resolve/db.py, set log_min_duration_statement to 300ms, and have ops/watchdog.py read pg_settings and compare against the file so the applied config is measured, not remembered.
- **OPS-V11 · F507 · low** — alerts.ndjson grows without bound and is read whole on every open_alerts() call; system_health tails 10,000 lines so an older clear marker is lost — `ops/alert.py:144`
  - scenario: After a month with a failing 2-minute timer (~45k lines) the watchdog re-parses several MB per fault per run, and Fawwaz's `system_health` lists as 'open' every OnFailure event older than the last 10,000 lines even after `--clear`, because the clear marker fell outside its tail.
  - suggested fix: Rotate at 5 MB into `alerts.ndjson.1` with a compaction that rewrites the open set + last clear marker into the new file; share one `_read_log` between alert.py and mcp_server (import when possible, else read the compact head).
- **OPS-V12 · F556 · low** — Backup manifest uploads 64 bits of SHA-256(backup passphrase file) in cleartext — `ops/backup.py:371`
  - scenario: Whoever can list the remote (a Drive/Hetzner credential leak, a shared-account operator) gets an offline oracle: guess passphrases, hash, compare 16 hex chars. If backup.key is a human-chosen passphrase rather than 32 random bytes, this turns the encrypted secrets.tar (which holds .env and the Telethon session) into a crackable target; the HANDOFF §2 note that the key must live in a password manag …
  - suggested fix: Replace with a random key-id generated once and stored beside the keyfile (or HMAC(random_salt, key) with the salt kept off the remote); confirm the keyfile is ≥ 32 random bytes.
- **OPS-V13 · F468 · low** — OONI year chunks may drop one day per boundary if `until` is exclusive — `ops/fetch_ooni.py:85`
  - scenario: Nine boundary days since 2017 are absent from ps_daily.json and read as 'no measurements that day' in the databank.
  - suggested fix: Verify against the API (request one day with since=until+1); if exclusive, use `until = b + 1 day` or overlap chunks and dedupe by date.
- **OPS-V14 · F469 · low** — fetchlib claims fetch_gho_wash and fetch_t4p read from it; neither imports it — `ops/fetchlib.py:5`
  - scenario: A session adds retry/backoff or a ledger change to fetchlib expecting all four fetchers to follow; gho_wash keeps failing silently to the ledger (it has no event line at all), and gap_radar never sees it.
  - suggested fix: Port both scripts to fetchlib (fetch_gho_wash gains event() and check_floor) or fix the docstring.
- **OPS-V15 · F508 · low** — The seat-probe failure path records the maintain heartbeat without a cadence, so on a fresh row the maintainer becomes 'unmonitored' — never a fault — `ops/maintain.sh:145`
  - scenario: After a restore (or on a rebuilt DB) the first maintain event is a capped seat: the row exists with NULL interval; every following Monday fails the same way; the watchdog and /health show `maintain unmonitored`, no fault, for as long as the seat stays capped — the exact 'skipped week nobody notices' F-03 was built to end.
  - suggested fix: Pass `--interval 604800 --grace 172800` at :145; in job_checks treat `unmonitored` as a fault when the name is in EXPECTED_JOBS.
- **OPS-V16 · F509 · low** — The gateway alarm still names MiniMax and says 'the subscription is still paid'; FAWWAZ.md still says alarms wait in a file until a Telegram pair is set — `ops/minimax_alarm.py:200`
  - scenario: Fawwaz relays 'the MiniMax subscription is still being paid for' to Zaid for a local-gateway budget cap; a new session reading FAWWAZ.md concludes real-time alarms are undelivered and re-plumbs Telegram.
  - suggested fix: Rename the row/key to `gateway`, reword the detail to the budget cap, update FAWWAZ.md's last section to describe ntfy (P1-C.3).
- **OPS-V17 · F557 · low** — Alarm delivery depends on another project's secret file and a bot-token search across unrelated .env files — `ops/notify.py:99`
  - scenario: LifeOS rotates its ntfy token or moves state.json: every alarm returns 403, `send()` swallows it by design (:263-280), and the watchdog keeps reporting a healthy exit — the 17-hour silence of 2026-08-02 recurs with the doorbell wired but ringing nowhere. The key search also means a bot token appearing in an unrelated .env silently becomes this project's alarm credential.
  - suggested fix: Store this project's own NTFY_TOKEN in .env (chmod 600); make ops/watchdog.py raise a fault when the last N sends failed (delivery health as a watched job); drop the multi-file token search.
- **OPS-V18 · F510 · low** — The high-priority ntfy path is dead: the '!!' mark it keys on is the watchdog's console mark and never appears in alert text — `ops/notify.py:218`
  - scenario: Every real alarm — poller dead, disk critical, backup failed — arrives at ntfy 'default' priority with no rotating_light tag; the sound/vibration distinction the comment promises ('the one that is allowed to make a sound') never happens, and a phone with default-priority notifications quietened sleeps through a poller death.
  - suggested fix: Give `send()` an explicit `priority` argument; alert.raise_alert passes 'high' for watchdog faults and OnFailure events, resolve passes 'min'; drop NTFY_HIGH_MARK.
- **OPS-V19 · F511 · low** — test_watchdog checks scripts against EXPECTED_JOBS but nothing checks timers against scripts, unit SuccessExitStatus against script OK_EXIT_CODES, or OnFailure presence per unit — the three properties the valhalla-ip and mcp-audit defects violate — `tests/test_watchdog.py:36`
  - scenario: The next timer added the way valhalla-ip was — a script, a unit, no wrapper — ships with a green suite and is unwatched until it fails on the day it matters.
  - suggested fix: Add three tests: every `*.timer` maps to a `.service` whose ExecStart script contains a `with-heartbeat.sh <name>` line with `<name>` in EXPECTED_JOBS (allow-list the daemons); every non-template `.service` has OnFailure in the file or its `.d/`; every script that mentions OK_EXIT_CODES exports it before exec and its unit carries the matching SuccessExitStatus.
- **OPS-V20 · F588 · low** — test_the_baseline_excludes_the_window_it_judges checks an f-string against the constants it was formatted from — `tests/test_watchdog.py:174`
  - scenario: The clause is kept but the percentile is later computed over a CTE that re-includes the judged hours; the string still contains both intervals; a slowly degrading feed drags its own threshold down and never trips.
  - suggested fix: Rolled-back DB test: insert arrivals for a synthetic kind with a 1-minute rhythm for 21 days and a 5-hour gap inside the last JUDGE_HOURS, run the cadence measurement, assert the p99 is unaffected by the recent gap.
- **OPS-V21 · F589 · low** — test_recovery_is_delivered_silently inspects source text for '_notify' and 'silent=True' instead of exercising resolve() — `tests/test_watchdog.py:622`
  - scenario: `resolve()` is refactored so the `_notify(..., silent=True)` call sits behind a condition that is never true (or in a comment); the test passes; recoveries stop being delivered and an operator cannot tell 'recovered' from 'still broken, gone quiet' (the file's own :615-618 rationale).
  - suggested fix: Monkeypatch `alert._notify` to record kwargs, raise then resolve an alarm against a tmp ledger, assert one call with `silent=True` and the recovery text.

## C. Refuted — do not fix

- F280 The databank sync at 03:40 reads v1's unified tree while v1's ~2-hour refresh is still rewriting it, and the vault hot-copy runs before v1's 04:05 snapshot every night (`ops/systemd/palestine-v2-databank.timer:5`) — The loader-mid-rewrite claim cannot be confirmed from this repo and is contradicted by its own records. ops/systemd/palestine-v2-databank.timer:5 is `OnCalendar=*-*-* 03:40:00` (+10 min RandomizedDelaySec) and ops/databank-sync.sh:4-5 says v1's unified tree refreshes at ~02:51; docs/DECISIONS.md:269 …
- F281 The classifier's full corpus re-read exceeds the 900 s timeout on BOTH units that run it; HANDS §8 fixes only the news unit and the fix lives outside ops/systemd (`ops/systemd/palestine-v2-external.service:10`) — Structural facts hold: ops/ingest-external.sh:33 runs `ingest.sources.news_incidents` with no --limit under palestine-v2-external.service:10 `TimeoutStartSec=900`; palestine-v2-news.service:10 is also 900; news_incidents.py:394-404 takes pg_try_advisory_lock and :436-445 re-reads every claim whose c …
