---
name: Bug report
about: Something the Auditor does that it shouldn't, or doesn't do that it should
title: ''
labels: bug
assignees: justalewis
---

## What you did

A short description of the action that triggered the bug. e.g. "Uploaded an enriched deposit XML from my scraper pipeline and clicked 'Auto-decide all' on the cleanup page."

## What happened

What you saw. Include any error messages or unexpected UI states.

## What you expected to happen

How you thought it would behave.

## Minimal reproducer

If the bug is data-specific (a particular citation, a particular schema variant, etc.), please include a redacted XML snippet — even a few citations is usually enough to reproduce.

```xml
<!-- paste the smallest XML that demonstrates the issue here -->
```

## Environment

- Auditor version (commit SHA, branch, or release tag — `git rev-parse HEAD` if you've cloned)
- Python version (`python --version`)
- Running standalone, via docker compose, or via something else
- Browser (only relevant if it's a UI bug)
- OS

## Anything else

Logs, screenshots, theories, or context that might help. If the bug only shows up with deposits from a specific upstream tool (GROBID, OJS exports, JATS conversions, etc.), mentioning that helps.
