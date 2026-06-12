# greenhouse-sandbox

Zero-stakes target repo for **Greenhouse** nightly autonomous code spikes (v0.2).

This repo exists so the first autonomous code-generation PRs land somewhere whose blast radius is
**zero**. Nothing here is load-bearing for any fleet system.

## What lands here
Nightly spike seeds: small, self-contained proof-of-concept tools in tools/, opened as **draft PRs**
on agent/greenhouse/<date>/<slug> branches. Ace reviews; anything useful graduates to a real repo.

## Review safety
Greenhouse PR branches are **web-only / --no-checkout review** — do not check out a greenhouse branch
locally without inspecting .git-internal files first (Greenhouse PRD B4 / RC-new).

## Guardrails (enforced upstream)
Draft-only PRs, never auto-merged. main is branch-protected (incl. admins). Diff-capped, secret-scanned
before PR-open. Generated code runs in a --network none container; it never touches your machine.
