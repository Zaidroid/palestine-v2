#!/usr/bin/env bash
# P0.1 — sample container + host resource usage for the reclamation audit.
# Detached logger: writes one NDJSON line per container per sample.
# Usage: nohup ops/audit/sample-stats.sh <hours> <interval_sec> &
set -uo pipefail

HOURS="${1:-24}"
INTERVAL="${2:-300}"
OUT="$(dirname "$0")/stats.ndjson"
END=$(( $(date +%s) + HOURS * 3600 ))

while [ "$(date +%s)" -lt "$END" ]; do
  TS=$(date -Is)

  # Per-container: name, mem bytes, mem %, cpu %
  docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}' 2>/dev/null |
  while IFS=$'\t' read -r name mem memp cpup; do
    used="${mem%% /*}"
    printf '{"ts":"%s","kind":"container","name":"%s","mem":"%s","mem_pct":"%s","cpu_pct":"%s"}\n' \
      "$TS" "$name" "$used" "$memp" "$cpup" >> "$OUT"
  done

  # Host memory + swap
  read -r _ mt mu mf _ _ ma < <(free -b | awk '/^Mem:/')
  read -r _ st su _        < <(free -b | awk '/^Swap:/')
  printf '{"ts":"%s","kind":"host","mem_total":%s,"mem_used":%s,"mem_free":%s,"mem_avail":%s,"swap_total":%s,"swap_used":%s}\n' \
    "$TS" "$mt" "$mu" "$mf" "$ma" "$st" "$su" >> "$OUT"

  # GPU
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null |
  while IFS=', ' read -r gu gt; do
    printf '{"ts":"%s","kind":"gpu","vram_used_mib":%s,"vram_total_mib":%s}\n' "$TS" "$gu" "$gt" >> "$OUT"
  done

  sleep "$INTERVAL"
done
