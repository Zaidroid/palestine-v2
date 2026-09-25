# DESIGN.md — palestine-v2 public page ("see it" — gate T1.8)

Contract for every UI surface in this repo. Derived from the zaid-design DNA
(pole 1 signature, adapted: this is a PUBLIC, Arabic-first family tool, not a
private desk). The engine's honesty laws are design laws here.

## Who this is for, and the ten-second test

Someone in Ramallah, on a phone, in Arabic, deciding **which road to take** —
answered in under ten seconds. Not an operator dashboard: the watchdog and MCP
already serve the operator. Every screen must survive: one hand, bright sun,
2G, and a person who has never seen it before.

## The laws (violations are bugs, not taste)

1. **Age changes the answer.** A reading past its staleness band renders as
   `unknown` with "last known X, N minutes ago" — never as the stale value in
   confident clothes. This is the entire differentiator; the competitor shows
   age in small grey text under a bold pill. We let it change the pill.
2. **The three-state vocabulary is sacred**: a value, `unknown` (decayed or
   never reported), and `no source` (nothing feeds this) are three different
   facts and get three different renderings. Zeroes are zeroes.
3. **Arabic-first**: `dir="rtl"`, `lang="ar"` default; EN toggle mirrors chrome
   only — data keeps its language. Arabic line-height ≥ 1.6. Bidi isolation
   wraps NUMERALS ONLY, never Arabic prose.
4. **Numbers are mono + `tabular-nums`**, everywhere, both languages.
5. **No external requests.** No tile servers, no font CDNs, no analytics.
   System Arabic type stack; everything self-contained. A page for people on
   throttled connections does not phone third parties.
6. **No skeletons, no progress theater.** Render last-known data instantly;
   SSE liveness = one pulsing dot + rows arriving. `prefers-reduced-motion`
   honored; motion 120–450ms, one easing, arrival/state-change only.
7. **Attribution + blind spots stated**: source names visible; `no source`
   kinds listed, not hidden; quarantined feeds never appear as data.
8. **Presence is a sighting, not a state**: army/police chips carry their age
   and never overwrite the flow answer.

## Tokens (single source: `serve/webapp/tokens.css`)

Warm-dark signature (variants may define a light alternative in their own
scope, same structure): ground `#141110` ladder ×4, ink `#EDE6DD`/muted
`#A79A8C`, accent gold `#E8A33D`, status triad olive `#7C8A4D` / amber
`#D9A03F` / terracotta `#C25E4C`, unknown slate `#6E675F`, hairline
`rgba(237,230,221,.08)`. Radius 4/8/14. Type: system Arabic stack
(`"SF Arabic", "Segoe UI", "Noto Naskh Arabic UI", system-ui`), mono for
numerals (`"SF Mono", "Cascadia Mono", monospace`). Uppercase tracked
micro-labels 10–11px/.14em for eyebrows (EN); Arabic eyebrows use weight+muted
instead of uppercase (Arabic has no case).

## Status encoding (colour never decorates)

flow `open` olive · `slow`/`congested` amber · `closed` terracotta ·
`unknown` slate outline (no fill — absence of knowledge is not a state
colour). Fuel `available` olive / `unavailable` terracotta / `unknown` slate.
Every status chip carries its age beside it, mono.

## Process state

2026-08-03: three concept variants built on live data for the options loop —
`road` (answer-first), `pulse` (feed-first), `board` (corridor diagram,
light). NOT LOCKED. No further aesthetic work until Zaid points or mixes;
then the locked concept gets the full PWA pass (manifest, SW, install copy,
thumb-zone audit) per mobile-first-pwa.

2026-09-25: **the front door** (Z-1) — `/` for a browser serves `webapp/front.html`
(content-negotiated; API clients keep the JSON), `/docs/partner` the rendered partner guide.
Both follow the reader's colour scheme through `:root.follows-scheme` in `tokens.css`
(the concept pages do not carry the class and stay warm-dark), and both send a CSP that
allows this origin only — law 5 enforced by the browser, not just by review.
