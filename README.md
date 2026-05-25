# Crossref Auditor

Pre-submission audit and cleanup for Crossref deposit XML. Sibling tool to the per-journal scrapers under `Journal Reference Scrapers/`. Reads a `<doi_batch>` deposit, validates against the Crossref XSD, runs heuristic checks for the smelly-but-valid issues that come out of imperfect scraping (glued citations, paragraph-shaped body text, repeat-author markers, footnote bleed, duplicate years, Crossref business-rule violations that schema validation misses, etc.), and provides a card-based cleanup UI to fix or delete flagged citations.

Also supports **batch upload and merge** for multi-volume single-journal backfills: upload all N volume-level XMLs at once, clean each volume's queue individually, then merge into one deposit XML for submission.

## Quick start

```bash
pip install -r requirements.txt
python fetch_xsds.py    # one-time: download Crossref XSDs
python app.py           # http://localhost:5001
```

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
