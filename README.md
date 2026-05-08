# Crossref Auditor

Pre-submission audit and cleanup for Crossref deposit XML. Sibling tool to the per-journal scrapers under `Journal Reference Scrapers/`. Reads a `<doi_batch>` deposit, validates against the Crossref XSD, runs heuristic checks for the smelly-but-valid issues that come out of imperfect scraping, and provides a card-based cleanup UI to fix or delete flagged citations.

## Quick start

```bash
pip install -r requirements.txt
python fetch_xsds.py    # one-time: download Crossref XSDs
python app.py           # http://localhost:5001
```

## Where to read more

See [DOCUMENTATION.md](DOCUMENTATION.md) for the full reference: rule catalog, cleanup workflow, bulk auto-decide, HTTP API, database schema, pipeline integration, troubleshooting.
