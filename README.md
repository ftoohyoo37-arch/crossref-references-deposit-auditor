# Crossref Auditor

Pre-submission audit and cleanup for Crossref deposit XML. Sibling tool to the per-journal scrapers under `Journal Reference Scrapers/`. Reads a `<doi_batch>` deposit, validates against the Crossref XSD, runs heuristic checks for the smelly-but-valid issues that come out of imperfect scraping (glued citations, paragraph-shaped body text, repeat-author markers, footnote bleed, duplicate years, Crossref business-rule violations that schema validation misses, etc.), and provides a card-based cleanup UI to fix or delete flagged citations.

Also supports **batch upload and merge** for multi-volume single-journal backfills: upload all N volume-level XMLs at once, clean each volume's queue individually, then merge into one deposit XML for submission.

## Quick start

Two ways to bring it up:

**Docker (recommended for first-time users):**

```bash
docker compose up
# then open http://localhost:5001
```

**Bare Python:**

```bash
pip install -r requirements.txt
python fetch_xsds.py    # one-time: download Crossref XSDs
python app.py           # http://localhost:5001
```

## Try it on sample data

The repo includes two small example deposits in [`sample-deposits/`](sample-deposits/) — a clean one to confirm the install works and a deliberately dirty one with seven planted issues so you can see what each audit rule catches and how the cleanup workflow handles them. Upload either at `http://localhost:5001` to get a feel for the tool before pointing it at your own deposits.

## What it audits

Sixteen rules covering schema validation, Crossref ingestion-layer business rules (the kind that pass XSD but get rejected at deposit time), GROBID extraction artifacts, and unstructured citation quality. Auto-cleanup handles most issues without manual review; what remains is a focused review queue of the cases that genuinely need eyes.

## Where to read more

See **[DOCUMENTATION.md](DOCUMENTATION.md)** for the full reference:
- Plain-language overview and core concepts
- Per-rule reference (all 16 rules with parameters and Crossref-side rationale)
- Cleanup workflow (manual actions, bulk auto-decide with all five passes, keyboard shortcuts, apply-to-similar, diff view)
- Batch workflow (upload, per-file dashboard, depositor/schema validation, merge)
- Pipeline integration (importable Python core for scraper-side gating)
- HTTP API reference
- Database schema
- Limitations and troubleshooting (including the Crossref test-sandbox-vs-production gotcha)

## Contributing

Bug reports, feature requests (especially new audit rules!), and PRs all welcome. See **[CONTRIBUTING.md](CONTRIBUTING.md)** for what to include in an issue and what kinds of changes land most easily. The Auditor's rule engine is the most actively evolved part of the codebase, so if your scraper produces a particular pattern of deposit garbage that the existing rules don't catch, that's exactly the kind of feature request that's quick to land.

## About

I'm Justin Lewis — faculty at Olympic College, design and web editor at *[Literacy in Composition Studies](https://licsjournal.org)*, and builder of *[Pinakes](https://pinakes.app)*, an open-access bibliometric platform for rhetoric and composition / technical and professional communication. I built the Auditor because I needed it for my own journal's Crossref deposits and the surrounding pipeline I've been developing for several other journals in the field; it's released open-source in case it's useful to others doing similar back-catalog and ongoing-deposit work.

The Auditor is the cleanup-side counterpart to a larger reference-extraction pipeline (currently used across seven humanities journals on WAC Clearinghouse and OJS platforms). If you have a humanities journal that mints DOIs but hasn't yet deposited reference lists with Crossref, I'm happy to talk about doing that work for you at no cost — jlewis2 [at] olympic.edu.
