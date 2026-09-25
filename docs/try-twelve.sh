#!/usr/bin/env bash
# The twelve canonical questions (PLAN §10) — the release is measured on these.
#
# For anyone with a key and nothing else installed — the public test key on
# https://live-api.zaidlab.xyz/#connect works: no MCP client, no SDK, no Python
# package beyond the interpreter most machines already have. Download it from
# https://live-api.zaidlab.xyz/docs/try-twelve.sh.
# Every call goes to the same endpoint the product will use, with the key in a
# header (the shape a server-side harness should send), and prints what came
# back plus the licence tier of what it just received.
#
#   PV2_KEY=pv2_... ./docs/try-twelve.sh
#   ./docs/try-twelve.sh pv2_...                # or pass it as $1
#   LIVE_API=http://127.0.0.1:7870/mcp ./docs/try-twelve.sh   # against a local build
#
# The key is never echoed: it goes into a header and nowhere else, so this is
# safe to run in a terminal someone else can see.
set -uo pipefail

K="${PV2_KEY:-${1:-}}"
U="${LIVE_API:-https://live-api.zaidlab.xyz/mcp}"

if [ -z "$K" ]; then
  echo "usage: PV2_KEY=pv2_... $0   (the key is not echoed by this script;" >&2
  echo "       the public test key is on https://live-api.zaidlab.xyz/#connect)" >&2
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# The order matters: `about` first, because it says what the system holds and —
# more usefully — what it holds NOTHING for. A reviewer who skips it will read
# every thin answer that follows as a data problem rather than a known gap.
calls=(
  "about|{}"
  "checkpoint_status|{\"name\":\"قلنديا\"}"
  "checkpoint_status|{\"name\":\"Huwara\"}"
  "can_i_travel|{\"origin\":\"رام الله\",\"destination\":\"نابلس\"}"
  "can_i_travel|{\"origin\":\"Nablus\",\"destination\":\"Jenin\"}"
  "incidents|{\"place\":\"رام الله\",\"hours\":12}"
  "insights|{\"place\":\"نابلس\",\"days\":7}"
  "crossings|{\"place\":\"رفح\"}"
  "fuel_prices|{}"
  "databank|{\"category\":\"casualties\",\"limit\":3}"
  "databank|{\"category\":\"demolitions\",\"limit\":5}"
  "place|{\"place\":\"حوارة\",\"view\":\"history\",\"days\":30}"
)

printf '\nendpoint: %s\n\n' "$U"
i=0
for entry in "${calls[@]}"; do
  name="${entry%%|*}"
  args="${entry#*|}"
  i=$((i + 1))
  body="{\"jsonrpc\":\"2.0\",\"id\":$i,\"method\":\"tools/call\",\"params\":{\"name\":\"$name\",\"arguments\":$args}}"
  start=$(date +%s%N)
  code=$(curl -sS -m 30 -o "$TMP/$(printf %02d $i)-$name.json" -w '%{http_code}' -X POST "$U" \
      -A 'palestine-data-try-twelve/1.0' \
      -H "X-Api-Key: $K" \
      -H 'content-type: application/json' \
      -H 'accept: application/json, text/event-stream' \
      -d "$body" 2>"$TMP/$(printf %02d $i)-$name.err")
  ms=$(( ($(date +%s%N) - start) / 1000000 ))
  printf '%-20s http %s  %5s ms\n' "$name" "$code" "$ms"
done

# Summarise from the responses themselves. Reads the Arabic answer and the
# licence block out of each payload rather than re-describing it, so what is
# printed here is what the endpoint actually returned.
python3 - "$TMP" <<'PY'
import json, pathlib, sys

tmp = pathlib.Path(sys.argv[1])
for f in sorted(tmp.glob("*.json")):
    name = f.stem.split('-', 1)[-1]
    try:
        outer = json.loads(f.read_text())
    except Exception as exc:                                    # noqa: BLE001
        print(f"\n{name}: could not parse response ({exc})")
        continue
    if outer.get("error"):
        print(f"\n{name}: JSON-RPC error {outer['error'].get('code')}: "
              f"{outer['error'].get('message')}")
        continue
    try:
        p = json.loads(outer["result"]["content"][0]["text"])
    except Exception:
        p = outer.get("result", {})
    lic = p.get("licence") or {}
    print(f"\n=== {name} " + "=" * (56 - len(name)))
    if p.get("answer"):
        print("answer  :", " ".join(str(p["answer"]).split())[:300])
    if p.get("answer_en"):
        print("answer_en:", " ".join(str(p["answer_en"]).split())[:300])
    if lic:
        print(f"licence : tier={lic.get('tier')} partner_tier={lic.get('partner_tier')} "
              f"grade={lic.get('grade')}")
        if lic.get("note"):
            print("          note:", " ".join(str(lic["note"]).split())[:220])
        if lic.get("excerpted_items"):
            print(f"          {lic['excerpted_items']} message body(ies) cut to "
                  f"{lic.get('excerpt_chars')} chars — see licence.refused")
        if lic.get("graded") is False:
            print("          UNGRADED — do not redistribute this payload")
    if p.get("refused"):
        print("refused :", str(p.get("reason") or p.get("reasons"))[:300])
    if p.get("caveat"):
        print("caveat  :", str(p["caveat"])[:200])
PY

printf '\nWhat to do with this: docs/PARTNER-API.md §8 grades what you just received,\n'
printf 'and §11 says where to send anything that looks wrong. Nothing above is\n'
printf 'a sample or a mock — it is the live endpoint answering.\n'
