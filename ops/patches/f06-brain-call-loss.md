F-06 — v1's calls to the brain: two of the three changes, and where the third lives

Written 2026-09-22, applied the same night except where noted. Measured before
touching anything: `/quality/checkpoints .llm` read 254 ok / 95 failed of 349
(72.8%) with 47 ReadTimeout, 26 HTTP 429, 12 ConnectTimeout, 8 ConnectError.

1. v1 read timeout — APPLIED, and to the live container

    /opt/stacks/palestine/services/westbank-alerts/.env
    +MINIMAX_TIMEOUT_S=60

    `MINIMAX_TIMEOUT_S` is a pydantic setting with a 20 s default and was absent
    from the env file, so 20 s is what every call got while one Honcho turn held
    the single resident model. The plan said `docker compose up -d --build
    alerts`; that is not needed and not safer for an env value — the image is
    prebuilt and `--build` would re-bake the live service for a variable it
    reads at start. Applied as:

    cd /opt/stacks/palestine && sudo -n docker compose up -d alerts

    Verified: `docker inspect params-alerts-api` carries MINIMAX_TIMEOUT_S=60,
    and `GET /quality/checkpoints` answers 200. The LLM counters reset with the
    container, so the ≥99 %-over-a-day proof starts from this restart.

2. llama-swap two slots — APPLIED on MainPC (100.114.104.95)

    C:\zlab\infer\llama-swap.yaml, backup kept beside it
    (llama-swap.yaml.bak-20260923-000827):

    -    cmd: '${srv} -m ${models}\gpt-oss-20b-MXFP4.gguf ${common} -c 16384 --jinja'
    +    cmd: '${srv} -m ${models}\gpt-oss-20b-MXFP4.gguf ${common} -c 32768 --parallel 2 --jinja'

    `-c` is the total context llama-server splits across `--parallel`, so 32768
    with two slots keeps 16384 per slot — which is what the plan asked for and
    what the old single-slot value could not give. Applied by restarting the
    scheduled task:

    Stop-ScheduledTask -TaskName zlab-llama-swap; Start-ScheduledTask -TaskName zlab-llama-swap

    Verified after the restart: the llama-server process carries `-c 32768
    --parallel`, `GET :8480/v1/models` lists the models, and a real
    `/v1/chat/completions` on the `engine` alias returned a 200 completion.

3. Gateway retries — NOT APPLIED, and this is the one thing F-06 could not finish

    zlab-brain (100.110.89.116) is a separate Tailscale node, not MainPC, and it
    refuses this box's key for every non-root account tried (`admin`, `zaid`,
    `root` → `Permission denied (publickey)`). The change is one line in its
    litellm config:

        engine: { num_retries: 2 }

    Until that lands, the 429s the gateway returns while its single resident
    model is busy still reach v1 as failures — the ReadTimeout half is fixed by
    (1) and the concurrency half by (2), but the retry-on-429 half needs that
    host. Either authorise this box's key there (add it to
    /root/.ssh/authorized_keys or the litellm user's) or make the edit directly.

Proof still outstanding, and it cannot be shortcut: the plan's DONE WHEN is
`/quality/checkpoints .llm` ≥ 99 % over a FULL day. Read it tomorrow after the
night's runs, not tonight.
