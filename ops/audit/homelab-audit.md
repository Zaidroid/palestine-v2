# Homelab reclamation audit — P0.3

**Measured:** 2026-07-30 · **Host:** i7-11800H, 15.32 GiB RAM, RTX 3060 6 GiB, 259 GB free disk
**24h sampler:** running (`ops/audit/sample-stats.sh`, 5-min interval → `stats.ndjson`) — this
document uses the point-in-time snapshot; re-check against the sampler before acting.

## Headline

| | |
|:--|--:|
| Host RAM used | **9.8 GiB / 15.3 GiB** |
| Host RAM available | **5.5 GiB** |
| Swap in use | **2.6 GiB** |
| All 26 containers (docker accounting) | 2,607 MiB |
| VRAM used | 1,940 / 6,144 MiB |

**Docker's 2.6 GiB does not explain 9.8 GiB used.** The gap is host-side processes:
Claude sessions (~1.5 GiB, transient), the hermes agent stack (~1.05 GiB, runs as
`admin` outside docker), frigate's subprocess tree (docker reports 1.04 GiB; the
real tree is **3.07 GiB**), and stale dev servers (~0.6 GiB).

**Target for Phase 0:** free ≥2.5 GiB RAM so the Postgres/Timescale container can
take a 2 GiB limit instead of the 1.5 GiB default, with real headroom left over.

## GPU

| Process | Container | VRAM |
|:--|:--|--:|
| `wyoming_faster_whisper` large-v3-turbo, CUDA float16 | `voice-whisper` | 1,804 MiB |
| `frigate.detector:onnx` | `frigate` | 128 MiB |
| **Free** | | **~4,204 MiB** |

`voice-whisper` is the 1.8 GiB holder flagged as unknown in ARCHITECTURE §8.2 trap 2 —
**identified, and it is part of the voice stack (presumed keep).** The T2 encoder
(~0.5 GiB) fits comfortably in the remaining 4.2 GiB. A quantized 7B local LLM
fallback does **not** fit alongside; local fallback stays CPU-only as planned —
*unless* frigate is stopped, which returns 128 MiB and, more importantly, its CPU.

## Kill / keep / shrink

### Reclaim candidates (ranked by RAM returned)

| # | Target | RAM | What it is | Recommendation |
|--:|:--|--:|:--|:--|
| 1 | **frigate** | **~3.07 GB** | NVR: camera recording + ONNX detector + embeddings manager. Started 6 h ago. | **[ZAID]** Biggest single win by far. Stop only if you are not actively relying on camera recording. Also frees 128 MiB VRAM and meaningful CPU. |
| 2 | **hermes stack** | **~1.45 GB** | `hermes-crawl4ai` (331 MiB) + `hermes-searxng` (69 MiB) containers, plus 4 host processes as user `admin`: gateway (307 MB), chat (293 MB), taqwa gateway (288 MB), dashboard (163 MB) — up 17 h. | **[ZAID]** Stop if not in active use. The two gateways + chat + dashboard look like leftover sessions rather than a service. |
| 3 | **variant-studio dev servers** | **~606 MB** | `tsx` watcher (293 MB, up 1 d 10 h), vite on :8400 (157 MB, up 1 d 10 h), worktree node (156 MB, up 1 d 6 h). | **Recommend stop.** Left running over a day; trivially restarted with `pnpm dev`. Lowest-risk reclaim on the list. |
| 4 | **wire-pod / chipper** | **~559 MB swap** | Vector robot voice backend. Entirely in swap — it is paying swap cost while idle. | **[ZAID]** Stop if the Vector isn't in use. Reclaims swap pressure more than RAM. |
| 5 | tooling leftovers | ~450 MB | `shadcn mcp` (155 MB, 50 min), `chrome-headless` (296 MB, 1 min — likely an active session). | **Leave alone.** Transient; they exit on their own. Listed for completeness only. |

**Realistic reclaim:** 606 MB (no approval needed, #3) → **~5.7 GB** (with #1 + #2 + #4).

### Presumed keep (per IMPLEMENTATION_PLAN P0.3)

`voice-*` (7 containers, ~103 MiB total + 1.8 GiB VRAM), `honcho-*` (4, ~307 MiB),
`vector-brain` / `vector-embody` (~12 MiB), `homelab-mcp`, `ntfy`, `autoheal`,
`node-exporter`, `cloudflared-palestine`.

### Palestine v1 — keep, do not touch

`palestine-data-api` (249 MiB / 2 GiB cap), `params-alerts-api` (192 MiB / **256 MiB
cap — 74.9% utilised**, tight), `wb-valhalla` (146 MiB container; 612 MB host RSS),
`cloudflared-palestine`. These are live production per the standing rules.

> Note for later: `params-alerts-api` at 74.9% of a 256 MiB cap is a latent OOM risk
> in v1 independent of this project. Not in Phase 0 scope; flagging it.

### Not running (no reclaim available)

Steam / Zomboid / `pzserver` were listed as candidates in the plan — **verified not
running.** No processes, no containers. Disk only.

## Recommendation to Zaid

1. **Approve now, no risk:** stop the three stale variant-studio dev servers (#3) → **~606 MB**.
2. **Decide:** frigate (#1, ~3.07 GB) — are you relying on camera recording right now?
3. **Decide:** hermes stack (#2, ~1.45 GB) — active, or leftover sessions?
4. **Decide:** wire-pod/chipper (#4, ~559 MB swap) — Vector in use?

If #1 and #2 are both approved, the Postgres container gets a comfortable 2 GiB limit
and the box stops swapping. If only #3 is approved, we proceed with the planned
1.5 GiB default and revisit at the Gate 0 check.

**Nothing has been stopped. No container was modified. This is a proposal only.**

---

## P0.4 outcome — applied 2026-07-30

**Zaid approved: frigate only.** variant-studio, hermes, and wire-pod were NOT
approved and are untouched and still running.

`docker stop frigate` (restart policy `unless-stopped`, so it stays down across
daemon restarts; `docker start frigate` reverses it).

| Metric | Before | After | Reclaimed |
|:--|--:|--:|--:|
| RAM available | 6,217 MB | 7,268 MB | **+1,051 MB** |
| Swap used | 3,722 MB | 3,360 MB | **−362 MB** |
| VRAM used | 1,940 MiB | 1,810 MiB | **−130 MiB** |

**Effective reclaim ≈ 1.4 GB RAM+swap, plus 130 MiB VRAM.**

### Correction to this document's own estimate

The table above predicted **~3.07 GB** for frigate. The real figure is ~1.4 GB.
The estimate was produced by summing `ps` RSS across frigate's subprocess tree
(main + detector + embeddings + forkserver), which **double-counts shared
memory** — the pages are mapped into several processes but resident once. The
docker-reported 1.04 GiB was closer to the truth than the RSS sum.

Method note for the remaining candidates: treat `docker stats` as the lower
bound and the RSS sum as a loose upper bound. Do not quote RSS sums as
reclaimable RAM. The VRAM estimate (128 MiB) was accurate — `nvidia-smi`
per-process accounting does not have this problem.

### Budget outcome
Postgres container limit raised **1.5 GiB → 2 GiB** (`PG_MEM_LIMIT` in `.env`).
Remaining candidates stay on the table if more headroom is needed later.
