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
