"""DOI minting workflow — sibling to the pipeline/ module.

Used for journals that have whole-issue PDFs and no CrossRef DOIs.
Splits issue PDFs into per-article PDFs, captures table-of-contents
metadata for each article, and generates a CrossRef content-registration
deposit XML that mints DOIs for each article.

The downstream output (per-article PDFs + doi-map.json) feeds directly
into the existing pipeline's extract/enrich/audit stages, so a journal
that needs DOIs minted goes through the minting flow first and then
the reference-backfill flow exactly like any other journal.
"""
