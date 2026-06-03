# gatekeeper

Reliable AI gatekeeper on top of Home Assistant. Phase 1: pure-logic validation
of the allow / confirm / reject safety gate. See
`docs/superpowers/specs/2026-06-03-ha-gatekeeper-design.md`.

## Setup

    python -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"

## Test

    pytest

## Run validation (needs ANTHROPIC_API_KEY)

    python -m harness.run_validation

## Phase 1a result (cloud Claude)

Validated 2026-06-03 with `claude-sonnet-4-6`, τ = 0.7 (unchanged from default):

| split   | pass  | safety violations |
|---------|-------|-------------------|
| tune    | 24/24 | 0                 |
| holdout | 6/6   | 0                 |

By category: normal 10/10, dangerous 9/9, invalid 11/11 — all on the first run, no
prompt/τ tuning required. Confidence on correct parses ranged 0.85–0.99, so the τ gate
never fired (expected for a strong model; its real test is Phase 1b with a local model).
