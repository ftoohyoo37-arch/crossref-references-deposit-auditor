# Contributing

This is a hobby project I maintain in evenings and weekends. Contributions are welcome — issues, PRs, and questions all land in the same inbox, which is GitHub itself.

## Reporting a bug

Open an issue. The bug-report template will prompt for what you'd expect: what you did, what happened, what you expected to happen, the Auditor version (just paste `git rev-parse HEAD` if you cloned the repo), and a minimal example XML if the bug is data-specific.

If you can include the actual `<doi_batch>` snippet that misbehaves — or a redacted version of it — I can usually reproduce and fix within a day or two. Without a sample, debugging from a description alone takes longer.

## Suggesting a new audit rule

The Auditor's rule engine is the most actively evolved part of the codebase. If you have a recurring problem in your deposits that the existing sixteen rules don't catch, that's exactly the kind of feature request that's easy to land. Open an issue describing:

- What the bad pattern looks like (a couple of citation examples)
- Why Crossref or your downstream consumers care (ingestion rejection? bad display? indexing miss?)
- Whether you already have a regex or heuristic in mind, or whether you want to leave the detection to me

New rules live in `auditor/rules/<rule_name>.py` and follow the pattern of the existing ones. The interface is small — `meta()` returning rule metadata and `apply(doi_citations, config)` returning findings. PRs adding a new rule + a couple of fixture-based tests are the easiest kind to review.

## Pull requests

Smaller PRs land faster. If you're considering a substantial change — restructuring the cleanup workflow, adding a new schema version, integrating a third-party API — please open an issue first so we can align on the approach before you sink time into code.

For typo fixes, missing tests, documentation cleanup, etc., just open the PR directly.

A few practical asks:

- Keep PRs focused. One change per branch makes review tractable.
- Run the existing tests before pushing (`pytest`). I'll add CI for this eventually.
- If you're touching a rule, include a fixture XML in `tests/fixtures/` that demonstrates the rule firing.
- Don't introduce new dependencies casually. The current requirements list is short on purpose.

## Response time

In a typical week I check GitHub once or twice. Issues get triaged within a few days; bugs that block you from depositing get prioritized.

If something is genuinely urgent — you're sitting on a CrossRef deposit deadline and the auditor is broken — drop a note in the issue's title (`[blocking]`) and I'll try to look at it within 24 hours.

## What I'd love help with

A few areas where outside contributions would land especially well:

- **Schema coverage.** The Auditor currently audits the reference-deposit schema (`doi_resources_schema/4.3.6`). Extending it to also audit content-registration deposits (the `journal_article` schema used for new DOI minting) would be a meaningful expansion.
- **New rules.** Most of what people deposit follows the same patterns; once a rule's encoded it helps every downstream user.
- **Test fixtures.** Real-world XML snippets from your own deposits — sanitized — are the best test data for the rule engine.
- **Documentation.** The README and `DOCUMENTATION.md` could always be clearer for first-time users.

## Code of conduct

Be decent. This is a small project in a small field; the people who'll be using it are mostly colleagues. The usual standards apply: no harassment, no demeaning language, no personal attacks. If something goes wrong, email me directly rather than escalating publicly.

— Justin Lewis
