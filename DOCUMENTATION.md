# Crossref Auditor — Documentation

A pre-submission audit and cleanup tool for Crossref deposit XML, designed to sit between a journal-reference scraper and the Crossref deposit API. Local Flask web app; SQLite history; runs on http://localhost:5001.

---

## Table of contents

1. [Overview](#1-overview)
2. [Quick start](#2-quick-start)
3. [Core concepts](#3-core-concepts)
4. [The audit](#4-the-audit)
   - [Running an audit](#41-running-an-audit)
   - [Reading the report](#42-reading-the-report)
   - [Exporting findings](#43-exporting-findings)
   - [Audit rule reference](#44-audit-rule-reference)
5. [The cleanup workflow](#5-the-cleanup-workflow)
   - [Card review model](#51-card-review-model)
   - [Manual actions](#52-manual-actions-keep--delete--split)
   - [Crossref matching](#53-crossref-matching)
   - [Bulk auto-decide](#54-bulk-auto-decide)
   - [Filtering and sorting](#55-filtering-and-sorting-cards)
   - [Downloading the cleaned XML](#56-downloading-the-cleaned-xml)
6. [Batch workflow](#6-batch-workflow-multi-volume-single-journal-deposits)
   - [Batch upload](#61-batch-upload)
   - [Batch dashboard](#62-batch-dashboard)
   - [Merge](#63-merge)
   - [Recommended batch workflow](#64-recommended-batch-workflow-for-a-multi-volume-backfill)
7. [Configuration](#7-configuration)
8. [Pipeline integration](#8-pipeline-integration)
9. [HTTP API reference](#9-http-api-reference)
10. [Database schema](#10-database-schema)
11. [Architecture](#11-architecture)
12. [Limitations and known issues](#12-limitations-and-known-issues)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Overview

### What it does (plain language)

When you backfill a journal's references into Crossref, the deposit XML you submit has to be both **technically valid** (Crossref will reject malformed files outright) and **substantively clean** (a citation that's a paragraph of body text accidentally captured by your scraper isn't a "real" citation, even though Crossref's parser may accept it). Crossref Auditor reads the deposit XML you're about to submit and tells you exactly what's wrong with it before you send it.

It does this in two stages:

1. **Audit.** Validate the XML against Crossref's official XSD schema, then run a battery of heuristic checks designed around the kinds of mistakes scrapers actually make: a "citation" that's 200 words long (probably two refs glued together), a `<doi>` field that contains `https://doi.org/...` instead of the bare DOI, an author surname that has a semicolon in it, a year that's in the future. Each finding is tagged with a severity (error, warning, info) and pinned to a line number in the XML so you can find it.
2. **Clean up.** For each citation flagged by the audit, present a card with three options: **Keep** the citation as-is (the warning was a false positive), **Delete** it (it's body text or a footer that shouldn't be a citation at all), or **Split** it into multiple new citations (two real refs were glued together by the scraper). The tool can cross-check each proposed piece against the Crossref REST API to confirm it corresponds to a real published work, and a "bulk auto-decide" mode applies these decisions to thousands of citations in one click.

The end product is a corrected XML file you can upload to Crossref with confidence.

### Who this is for

This tool is built for journal editors, librarians, and developers running citation-backfilling pipelines. It assumes you already have a scraper producing Crossref deposit XML (specifically `<doi_batch>` envelopes using either the deposit schema `crossref.org/schema/X.Y.Z` or the citation-update schema `crossref.org/doi_resources_schema/X.Y.Z`). The auditor doesn't scrape; it audits.

### Why a separate tool

Crossref's own validator catches schema violations but says nothing about the substantive quality of your citations. Conversely, scraper-side QC tends to focus on extraction accuracy without checking against Crossref's deposit format. The auditor closes that gap, and importantly its core function is a pure Python function — your scraper can import `audit()` and gate deposits on the result without touching the Flask UI at all.

---

## 2. Quick start

### Requirements

- Python 3.10 or newer (uses `X | None` type hints and other 3.10 syntax)
- Windows, macOS, or Linux
- ~30 MB disk for the XSD bundle (downloaded on first run)
- Internet connection only for the optional Crossref REST matching during cleanup

### Install

```bash
cd "C:/Users/Justin/Desktop/Journal Reference Scrapers/Crossref Auditor"
pip install -r requirements.txt
python fetch_xsds.py
```

`pip install -r requirements.txt` installs Flask, lxml, openpyxl, xhtml2pdf, and requests — all pure Python on Windows, no system libraries needed.

`python fetch_xsds.py` downloads Crossref's official XSDs (top-level schemas plus their includes — JATS, MathML, common, fundref, etc.) into `config/crossref_xsd/`. Run it once after install. The auditor still works without the XSDs (schema validation gracefully degrades to a warning), but real validation requires them.

### Run

```bash
python app.py
```

Open http://localhost:5001 in a browser. Upload a deposit XML file, watch the audit complete, and either review the report or click "Clean up →" to start fixing flagged citations.

### Stop the dev server

Ctrl+C in the terminal running `app.py`.

---

## 3. Core concepts

| Term | Definition |
| --- | --- |
| **Deposit** | A single XML file submitted to Crossref. Wrapped in a `<doi_batch>` envelope. May contain a single article's metadata or a backfill of many articles. |
| **Citation** | One reference inside a `<citation_list>`. Crossref permits both **unstructured** form (the entire reference as a single text string inside `<unstructured_citation>`) and **structured** form (separate `<author>`, `<cYear>`, `<journal_title>`, `<doi>` etc. elements). Most scrapers produce mixed: structured `<doi>` plus unstructured fallback text. |
| **Schema namespace** | Either `crossref.org/schema/X.Y.Z` (full deposit, used when registering new DOIs) or `crossref.org/doi_resources_schema/X.Y.Z` (citation update, used to add/replace references for an existing DOI). The auditor detects which one your file uses and validates against the matching XSD. |
| **Audit** | A single pass over a deposit XML that produces a list of findings. Stored in SQLite for re-export and cleanup. |
| **Finding** | A single issue raised by a rule. Has a severity (error / warning / info), a rule ID, a message, and (usually) a source line number and citation key. |
| **Rule** | A check applied to either the whole document, each citation, or as a post-pass over accumulated state. Each rule has metadata (default severity, configurable parameters) and produces zero or more findings. |
| **Decision** | A per-citation cleanup choice (`keep`, `delete`, or `split`). Stored in SQLite, applied when the cleaned XML is downloaded. |
| **Cleanup card** | One row on the cleanup page representing one flagged citation, with manual action buttons and an editable proposed-split block. |

---

## 4. The audit

### 4.1 Running an audit

Three ways to trigger an audit:

1. **Web UI:** drop a file on the home page upload form, click **Run audit**.
2. **Pipeline:** import `audit(xml_bytes, config) -> list[Finding]` from the `auditor` package. See [Pipeline integration](#7-pipeline-integration).
3. **HTTP:** `POST /audit` with the file as `multipart/form-data` (`xmlfile` field). Redirects to the report page on success.

The audit is single-threaded and streams the citation list with `lxml.etree.iterparse` so memory stays bounded even on 7,000+ citation deposits. A 4 MB deposit with ~7,000 citations completes in under 5 seconds on commodity hardware (with schema validation enabled).

### 4.2 Reading the report

The report page shows:

- **Header card:** filename, file size, schema namespace, citation count, error/warning/info counts, run timestamp.
- **Export bar:** five export buttons (JSON, Markdown, CSV, Excel, PDF) and a **Clean up →** button to enter the cleanup workflow.
- **Findings table:** one row per finding, with Severity, Rule, Line, Citation key, Message, and a short snippet of the offending text.
- **Filters:** dropdown filters by severity and by rule. URL-driven so you can bookmark a filtered view.

### 4.3 Exporting findings

All five export formats are generated on demand from the SQLite store (the audit doesn't have to be re-run). They share a unified shape: file metadata at the top, then findings grouped or tabulated.

| Format | MIME type | Use case |
| --- | --- | --- |
| **JSON** | `application/json` | Machine-readable; full audit metadata and every finding field including XPath. |
| **Markdown** | `text/markdown` | Human-readable, paste-into-issue-tracker friendly. Findings grouped by rule, sorted by severity. |
| **CSV** | `text/csv` | Spreadsheet pivot tables, BOM-prefixed for Excel compatibility. |
| **Excel** | `.xlsx` | Two-sheet workbook: Summary + Findings (with severity color-coding, frozen header, auto-filter). |
| **PDF** | `application/pdf` | Print-ready report. Generated via `xhtml2pdf` (pure Python, no GTK or wkhtmltopdf required). |

Filenames embed the audit ID: `<original-stem>.audit-<id>.<ext>`.

### 4.4 Audit rule reference

Sixteen rules ship by default. Each is a Python module under [auditor/rules/](auditor/rules/) with a `META: RuleMeta` describing it and a registered check function.

**A note on severity and the cleanup queue.** Most rules default to `warning` and produce cards in the cleanup queue at `/cleanup/<id>`. Two rules — `embedded_doi` and `stuck_whitespace` — default to `info` and are *deliberately excluded* from the cleanup queue. They flag conditions the user should be aware of (a DOI buried in unstructured text; PDF-extraction word-spacing artifacts) but neither blocks deposit nor has a safe auto-fix, so surfacing them as review cards would only add noise. They still appear in the audit report, the JSON/CSV/Excel exports, and the severity counts on the home page.

#### Document-scoped rules

These rules see the parsed root element and the raw byte stream.

##### `schema_validate` — XSD schema validation
- **Default severity:** `error`
- **What it checks:** validates the deposit against the bundled Crossref XSD whose namespace matches the file. Recognizes `crossref4.3.6.xsd`, `crossref4.4.2.xsd`, `crossref5.3.0.xsd`, `crossref5.3.1.xsd`, `doi_resources4.3.6.xsd`, `doi_resources4.4.2.xsd`. If the namespace doesn't match a known XSD, emits a single `warning` finding.
- **Parameters:** `max_findings` (default 50) — caps the number of XSD errors reported per audit, since a single missing required element can produce dozens of cascading errors.
- **What Crossref rejects:** any XSD failure; treat these as blocking.

##### `encoding_mojibake` — UTF-8/Latin-1 round-trip detection
- **Default severity:** `warning`
- **What it checks:** scans the raw bytes for common mojibake artifacts (`Ã©`, `â€™`, `Â `, `â€"`, etc.) that indicate a page was decoded with the wrong codec before being written. Reports per-token counts.
- **Parameters:** `max_examples` (default 5) — number of distinct artifacts to list in the message.

#### Citation-scoped rules

These rules run once per `<citation>` element. They use namespace-agnostic local-name matching, so the same rule covers both deposit schema and citation-update schema.

##### `unstructured_length` — length and glued-references detection
- **Default severity:** `warning`
- **What it checks:** four sub-checks on `<unstructured_citation>` text:
  1. Empty.
  2. Fewer than `min_words` words (default 5) — likely a fragment.
  3. More than `max_words` words (default 60) — likely two or more refs glued together.
  4. More than `max_year_count` (default 1) **distinct** 4-digit year tokens. The "real year" filter excludes:
     - Years inside quoted titles (`"The 1984 election"`)
     - Years inside URLs (`/2018/...` or `from-1890-to-1965/`)
     - Parenthesized journal-founding years (`Atlantic Monthly (1993) 320(3)`)
     - Volume markers (`1991(2)`)
     - URL/handle fragments (`/2027/`, `=2027`, `2027.42`)
     - Year ranges (`1700-1964`, `1991-1995` — both endpoints skipped)
     - Same year repeated (deduplicated, so `2021. … press release, July 6, 2021` counts as 1)
  5. More than `max_semicolons` (default 2) semicolons.
- **Parameters:** `min_words`, `max_words`, `max_year_count`, `max_semicolons`.
- **Notes:** This is the rule that drives most cleanup work. Tuning the thresholds on the Settings page lets you reduce noise on journals with consistently long unstructured citations.
- **Type-aware suppression:** sub-checks 3, 4, and 5 are skipped when [`auditor.citation_types.detect_type()`](auditor/citation_types.py) recognizes the citation as a non-Crossref-indexed source (`conference`, `website`, or `software`). These types legitimately have multiple year tokens (publication date + access date), longer text (full URLs and access notes), and embedded punctuation. The empty-text and fragment checks still fire for all citations. Measured on the Reflections backfill, this suppression cut total findings from 1,244 to 929 with no false negatives observed.

##### `duplicate_year_tokens` — two adjacent publication years
- **Default severity:** `warning`
- **What it checks:** flags `<unstructured_citation>` values containing two 4-digit years separated by only a period or comma plus whitespace (`Ore, Ersula. 2019. 2015. "They Call Me Dr. Ore." …`). This is a common GROBID extraction artifact where the publication year is duplicated.
- **Cleanup behavior:** the cleanup tool's bulk auto-decide runs a Pass 1.3 dedicated to these cards. For each, it strips the duplicate-year sequence to build a clean Crossref query, sends the query, and — only when Crossref returns a high-confidence match (score ≥ threshold, default 50) AND the canonical year matches one of the two candidates — auto-saves a `split` decision with the corrected single-chunk text. If Crossref returns a third year (matching neither candidate) or low confidence, the card falls through to manual review. Both safety guards must pass; the auto-fix is conservative by design. Measured on the Reflections backfill, this audit rule caught 57 duplicate-year cases.

##### `notes_section_appended` — Notes/Footnotes section glued onto last citation
- **Default severity:** `warning`
- **What it checks:** flags `<unstructured_citation>` values whose tail matches the literal section header `Notes`, `Footnotes`, `Endnotes`, or `End Notes` immediately followed by a footnote back-reference glyph and a digit (e.g. `… Notes ↑1 We include "women" …`). This pattern appears when GROBID concatenates the article's notes section onto the very last entry of the works cited. The footnote-glyph + digit lookahead is what makes the signal strong: real citations don't end with that combination, so the rule has very low false-positive risk. Also requires the section header to start more than 30 characters into the citation, so footnotes that begin with the pattern (already caught by `footnote_artifact`) aren't double-flagged.
- **Cleanup behavior:** the cleanup tool's bulk auto-decide handles these in Pass 1.5 alongside `journal_footer_suffix` cards — both are trailing-artifact strips. The splitter has already removed everything from the section header onward, so this pass simply commits that change as a `split` decision with the cleaned single-chunk text.

##### `journal_footer_suffix` — journal page footer glued onto citation
- **Default severity:** `warning`
- **What it checks:** flags `<unstructured_citation>` values whose tail matches a journal page footer pattern: a proper-noun journal name, a pipe character, the literal word "Volume" + digits, ", Issue " + digits, optionally followed by ", Spring|Summer|Fall|Winter|Autumn|<Month> YYYY". The full pattern is anchored to end-of-string. Real bibliographic entries use compact forms like "5(2)" or "vol. 5, no. 2"; the spelled-out "Volume X, Issue Y" with a season is distinctly typesetting-footer language and almost never appears inside a citation.
- **Cleanup behavior:** the cleanup tool's bulk auto-decide runs a Pass 1.5 dedicated to these cards: it auto-saves a `split` decision with the splitter's pre-stripped chunks (which have the footer removed). No manual review needed — the tool fixes them automatically. Measured on the Reflections backfill, this caught 25 footer-bleed cases including running headers from Reflections, NYT, Wired, and several other sources.

##### `repeat_author_marker` — repeat-author placeholder detection
- **Default severity:** `warning`
- **What it checks:** flags `<unstructured_citation>` values containing a bibliography-style repeat-author marker — three or more underscores (`___`), three or more hyphens (`---`), or two or more em/en-dashes (`——`, `––`) standing alone as a token. These markers appear in glued multi-reference citations where later refs use the marker as a stand-in for the previous author. The cleanup tool's splitter detects these markers and substitutes them with the leading author block when the chunk that follows has no author of its own; if the following chunk *does* have its own author block (the marker was a bibliography-entry separator between *different* authors, not a same-author placeholder), the splitter splits but doesn't substitute.
- **Parameters:** `min_chars` (default 30) — skip very short citations.
- **Notes:** distinguishes "same author" vs. "entry separator" usage by inspecting the leading characters of the chunk after each marker — `^Surname,\s+Initial` patterns trigger split-only mode.

##### `footnote_artifact` — footnote captured as citation
- **Default severity:** `warning`
- **What it checks:** flags `<unstructured_citation>` values that begin with a footnote back-reference glyph — `↑` (U+2191), `↩` (U+21A9 leftward-with-hook), or `⁋` (U+204B reversed pilcrow). These are footnotes accidentally pulled into the reference list by GROBID, not bibliographic entries. Anchored to the start of the citation (after optional whitespace) so that real citations containing the arrow elsewhere in their text don't false-positive.
- **Cleanup behavior:** the cleanup tool's bulk auto-decide handles these in Pass 1 alongside `paragraph_shaped` cards — both are auto-marked **delete**, no Crossref query needed. Measured on the Reflections backfill, this rule caught 8 footnote artifacts.

##### `paragraph_shaped` — body text detection
- **Default severity:** `warning`
- **What it checks:** flags citations that look like body text or paragraphs accidentally captured by the scraper, rather than bibliographic entries. Triggers only when **all** of these hold: (1) the text has at least `min_long_sentences` (default 3) sentences of 8+ words, (2) it doesn't open with an author-block pattern, (3) it has no `(YYYY` marker anywhere. Conservative by design — if any of those three conditions fails, the rule stays silent.
- **Parameters:** `min_long_sentences`, `min_chars`.
- **Cleanup behavior:** in the cleanup tool, citations flagged by this rule are auto-deleted in Pass 1 of bulk auto-decide (no Crossref query needed).

##### `incomplete_structured_citation` — missing fields Crossref requires
- **Default severity:** `warning`
- **What it checks:** two Crossref business rules that XSD validation can't catch. Calibrated against two real test deposits.
  - **Venue sub-check:** when a citation contains ANY structured-content field (`article_title`, `volume`, `issue`, `cYear`, `first_page`, `last_page`, `doi`, `edition_number`, `component_number`, or `author`), it must also include at least one venue identifier (`journal_title`, `proceedings_title`, `volume_title`, `series_title`, `issn`, or `isbn`). Crossref error if missing: *"Either ISSN or Journal title or Proceedings title must be supplied."*
  - **Ident sub-check:** when a citation is journal-shape (has `journal_title`, `proceedings_title`, or `issn`) AND has any other structured trigger, it must also include `first_page` OR `author`. Book chapters identified only by `volume_title`/`series_title`/`isbn` are NOT subject to this rule. Crossref error if missing: *"Either first page or author must be supplied."*
- **Cleanup behavior:** the cleanup tool's bulk auto-decide handles these in Pass 1.4. It strips ALL structured fields from the citation, leaving only `<unstructured_citation>`. Crossref accepts unstructured-only citations unconditionally (no minimums apply). Verified end-to-end: on a 7,109-citation Reflections deposit, 93 citations were auto-fixed this way and the resulting file produced 0 individual citation errors at Crossref.

##### `embedded_doi` — DOI buried in unstructured citation text (informational)
- **Default severity:** `info`
- **What it checks:** flags `<unstructured_citation>` values that contain a DOI (either as a `doi.org` URL or a bare `10.xxxx/yyy` pattern) when the `<citation>` has no separate `<doi>` child element. The citation deposits successfully as-is; promoting the embedded DOI to a structured `<doi>` field improves Crossref matching value but isn't a fix.
- **Cleanup behavior:** **not in the cleanup queue.** These are informational only — the audit report shows the count for awareness.

##### `ligature_artifacts` — Unicode ligature normalization
- **Default severity:** `warning`
- **What it checks:** flags citations containing Unicode ligature codepoints (`ﬁ` U+FB01, `ﬀ` U+FB00, `ﬂ`, `ﬃ`, `ﬄ`, `ﬅ`, `ﬆ`). PDF text extractors sometimes preserve these typographic ligatures literally; Crossref expects decomposed forms.
- **Cleanup behavior:** the splitter automatically normalizes these as a pre-pass — `"scientiﬁc"` becomes `"scientific"`, `"coﬀee"` becomes `"coffee"` — so proposed cleanup chunks are always ligature-free. The audit rule fires for visibility but the fix is silent.

##### `stuck_whitespace` — mid-word PDF-extraction whitespace (informational)
- **Default severity:** `info`
- **What it checks:** flags `<unstructured_citation>` values with spurious spaces inserted mid-word, a common GROBID/PDF text-extraction artifact (`Riley-M u kavetz`, single lowercase letter embedded between longer fragments). Includes a safe-token guard for legitimate one-letter words (Spanish `y`, `e`; English `a`, `i`; accented variants).
- **Cleanup behavior:** **not in the cleanup queue.** Crossref doesn't validate word spacing, so these deposit successfully as-is, and mechanical merging would risk damaging legitimate hyphenated names or accents. Informational only.

##### `doi_format` — DOI pattern check
- **Default severity:** `error`
- **What it checks:** any `<doi>` element must:
  - Be non-empty.
  - Match `^10.\d{4,9}/\S+$`.
  - Not be wrapped in a `https://doi.org/...` or `dx.doi.org/...` URL.
  - Not have leading or trailing whitespace.

##### `author_parsing` — author field leak detection
- **Default severity:** `warning`
- **What it checks:** for `<author>`, `<surname>`, `<given_name>`, and `<suffix>` elements, flags content containing `;`, ` and `, ` & `, or sequences of initials — all signals that a scraper jammed multiple authors into a single field.

##### `title_quality` — title field issues
- **Default severity:** `warning`
- **What it checks:** for `<article_title>`, `<journal_title>`, `<volume_title>`, `<series_title>`, `<chapter_title>`:
  - Empty.
  - Contains leaked HTML/JATS tags (e.g. `<em>`, `<i>`, `&amp;`, `&lt;`).
  - Contains embedded newlines.
  - Is entirely ALL CAPS (only flagged if `min_caps_words` (default 5) or more words).
- **Parameters:** `min_caps_words`.

##### `date_validity` — year and date sanity
- **Default severity:** `warning`
- **What it checks:** `<cYear>` and `<year>` elements:
  - Are 4 digits.
  - Within `[min_year, today.year + future_year_buffer]`.
  - `<month>` in 1–12; `<day>` in 1–31.
- **Parameters:** `min_year` (default 1500), `future_year_buffer` (default 2).

##### `page_range` — page range integrity
- **Default severity:** `warning`
- **What it checks:** `<first_page>` and `<last_page>`:
  - Both non-empty when present.
  - Numeric (with optional letter prefix/suffix).
  - Same prefix on both (`A100`–`A150`, not `A100`–`B150`).
  - `last_page >= first_page`.

##### `orcid_format` — ORCID format and checksum
- **Default severity:** `error`
- **What it checks:** `<ORCID>` elements (direct children or inside `<person_name>`):
  - Match `XXXX-XXXX-XXXX-XXXX` form.
  - Pass the ISO/IEC 7064 MOD 11-2 checksum.

#### Post-pass rules

These rules run after the citation stream completes, with access to accumulated state in `AuditContext`.

##### `duplicate_keys` — duplicate citation keys
- **Default severity:** `error`
- **What it checks:** within each `<citation_list>`, no two `<citation>` elements may share a `key` attribute. Crossref deduplicates by key when ingesting, so a duplicate silently overwrites earlier references. Scope is **per citation_list**, not document-wide — a deposit with 13 articles may legitimately reuse `ref1` thirteen times (once per article's own list).

---

## 5. The cleanup workflow

The cleanup page (`/cleanup/<audit_id>`) is where flagged citations get fixed. It's reachable via the **Clean up →** button on any audit report.

### 5.1 Card review model

Each flagged citation appears as a **card** showing:

- The citation's `key` attribute and source line.
- All audit warnings that applied to this citation (deduplicated — one card per citation, even if it tripped multiple sub-checks).
- The full `<unstructured_citation>` text.
- A **paragraph-shaped** badge if the citation was flagged by that rule.
- Three action buttons: **Keep**, **Delete**, **Split**.
- An expandable splits editor pre-populated with the splitter's proposed chunks.

Cards persist their decisions to SQLite, so leaving and returning to the page preserves your work. A decided card shows a badge in its header: `manual: keep` or `auto: split` etc.

The cleanup page only shows citations flagged by the rules `unstructured_length`, `paragraph_shaped`, and `repeat_author_marker` — these are the rules that flag glued or garbage citations. Other rules' findings (DOI errors, schema violations, ORCID checksums) require fixing in your scraper, not in the deposit XML.

### 5.2 Manual actions: Keep / Delete / Split

| Action | What it does to the cleaned XML |
| --- | --- |
| **Keep** | Citation is left exactly as it appeared in the original. Use when the audit warning was a false positive. |
| **Delete** | Citation is removed entirely from the cleaned XML. The parent `<citation_list>` retains its remaining children. |
| **Split** | Citation is replaced by N new `<citation>` elements, one per non-empty chunk in the split editor. The first new citation reuses the original `key`; subsequent ones get derived keys (`refX`, `refXa`, `refXb`, …). Each new citation contains a single `<unstructured_citation>` with the chunk text. |

The Split editor is a stack of textareas, one per proposed chunk. The auto-proposed chunks come from a two-pass splitter:

1. **Repeat-author marker pass.** If the citation contains `___` / `---` / `——` markers, split at each marker. For each chunk after the first, look at its opening characters: if it starts with its own author block (`^Surname,\s+Initial`), keep it as-is; otherwise, prepend the first chunk's author block in place of the marker.
2. **Year-anchored pass.** Otherwise, find each `(YYYY)` token after the first and walk backward to the nearest sentence boundary; split there.

You can edit the text directly, click **+ Add chunk** to insert another, or **Remove this chunk** to drop one. Each chunk has its own **Match in Crossref** button to verify it corresponds to a real paper before saving.

### 5.3 Crossref matching

Powered by the public Crossref REST API at `https://api.crossref.org/works`. The auditor sends a `query.bibliographic=<text>` request with a polite User-Agent including a contact email. Returns are parsed into a structure containing the matched DOI, title, authors (formatted), publication year, journal/container, raw relevance score, and a coarse confidence label (`high` ≥ 100, `medium` ≥ 50, `low` otherwise).

**About the score:** Crossref's relevance score is not a percentage and not normalized across query types. A textbook query may top out at 50 even when the match is correct; a journal article query usually scores 100+ for the right paper. Treat scores as a relative ranking, not an absolute confidence.

**Known limitation:** Crossref's bibliographic search performs best on journal articles. For textbooks, dissertations, working papers, and grey literature, expect frequent low scores or no match — the underlying citation may still be valid. The cleanup workflow accommodates this with the **fallback** dropdown described below.

### 5.4 Bulk auto-decide

The **Bulk auto-decide via Crossref** card at the top of the cleanup page automates decisions across all flagged citations. Three passes run sequentially:

**Pass 1 (instant) — Garbage auto-delete.** Every card flagged by either `paragraph_shaped` (body text captured as a citation) or `footnote_artifact` (text starting with a footnote arrow `↑`/`↩`/`⁋`) is auto-marked **delete**, no Crossref query needed. The decision notes record which rule triggered the deletion.

**Pass 1.3 (instant for same-year, ~500 ms otherwise) — Duplicate-year auto-fix.** Every card flagged by `duplicate_year_tokens` is sent through `cleanup.fix_duplicate_year()`. Three resolution paths in order:
1. **Same-year duplicates** (e.g., `D'Angelo, Frank. 1974. 1974.`) are dedup'd unconditionally — no Crossref call needed.
2. **Different-year duplicates** are queried against Crossref. If Crossref returns a high-confidence match whose canonical year matches one of the two candidates, that year wins.
3. **Crossref disagreed or returned low confidence** — apply the configured fallback: `keep_second` (default; correct in ~7 of 9 verified Chicago author-date cases), `keep_first`, or `crossref_only` (refuse to fallback, leave for manual review).

The decision notes record which method resolved each card (`dedup_same_year`, `crossref_verified`, `fallback_keep_second`, `fallback_keep_first`). On the Reflections backfill (57 duplicate-year cases): 13 dedup'd, 14 Crossref-verified, 30 resolved via `keep_second` fallback — full coverage with no manual review needed.

**Pass 1.4 (instant) — Incomplete-structured auto-strip.** Every card flagged by `incomplete_structured_citation` is auto-marked **split** with a single chunk equal to the `<unstructured_citation>` text. The XML writer replaces the original `<citation>` with one containing only `<key>` and `<unstructured_citation>` — Crossref accepts unstructured-only citations unconditionally, so this turns a deposit-rejection into a clean acceptance.

**Pass 1.5 (instant) — Trailing-artifact auto-strip.** Every card flagged by either `journal_footer_suffix` (a journal page footer like `Reflections | Volume 24, Issue 2, Spring 2025`) or `notes_section_appended` (a Notes/Footnotes block glued onto the last works-cited entry) is auto-marked **split** with the splitter's pre-stripped chunks. The splitter has already removed the trailing artifact in either case; this pass simply commits that change as a decision. No Crossref query needed. The decision notes record which rule triggered the strip.

**Pass 1.7 (instant) — Recognized-type auto-keep.** Every card whose `<unstructured_citation>` text is identified by `detect_type()` as a conference presentation, news/website article, or software/code repo is auto-marked **keep**. Crossref doesn't index these, so a REST query would return no match and waste time. The card's notes record which type was detected (e.g., `auto-kept (website)`).

**Pass 2 (~500 ms per chunk) — Crossref-verified split or keep.** For each remaining card:
- Query Crossref for each proposed chunk.
- If **all** chunks score ≥ the threshold (default 50), auto-mark the card:
  - `split` if the splitter proposed multiple chunks.
  - `keep` if the splitter proposed only one (the audit warning was a confirmed false positive).
- If any chunk falls below threshold, apply the **fallback** action.

**Controls:**

| Control | Effect |
| --- | --- |
| **Min Crossref score** | Threshold for confident auto-acceptance. 50 is conservative; 100+ is strict. |
| **Below threshold** | Fallback for low-confidence cards: `leave pending` (default; manual review required), `auto-keep` (safe default — assumes the rule was a false positive), or `auto-delete` (aggressive — for files heavy in body-text capture). |
| **Re-check already-decided cards** | If unchecked (default), skip cards that already have a decision. If checked, re-run Crossref against them and overwrite. |
| **Run auto-decide / Cancel** | Start or stop the run. The Cancel button is enabled only while a run is active. |

**Progress reporting:** the line below the controls updates after each card processed, e.g. *"Pass 2: card 23/50 — querying Crossref for 2 chunk(s)…"*. On completion you get a summary like:

> *Done. Auto-deleted 1 paragraph-shaped, auto-accepted 12 split(s) and 27 keep(s); 8 low-confidence cards auto-marked keep; skipped 2.*

A 7,000-citation file with ~1,400 cleanup cards completes in roughly 12–15 minutes (rate-limited to 150 ms per Crossref call out of politeness). Cancellation is graceful — already-decided cards stay decided.

### 5.5 Filtering and sorting cards

The **Filter cards** section at the top of the page provides four orthogonal controls:

| Control | Options |
| --- | --- |
| **Status** | All / Pending only / Any decision / Auto-decided only / Manually decided only |
| **Action** | All actions / Keep / Delete / Split |
| **Sort** | **Pending first, decided at bottom** (default) / By line number / By action (delete → split → keep → pending) / By rule (paragraph-shaped first) |
| **Article (parent DOI)** | All articles / one specific `<doi>` from the deposit's `<doi_citations>` blocks (each block represents one article's references) |

A live "Showing N of M" count updates as you change filters. Cards also receive a subtle background tint based on their action — pink for delete, yellow for split, green for keep — so the page can be visually scanned at a glance.

The default `Pending first` sort floats reviewed cards to the bottom in line order while keeping pending cards at the top in line order. Designed for the common pattern where 90% of cards get auto-decided by bulk auto-decide and the remaining manual-review work stays clustered at the top of the page. Switch to `By line number` when you want strict source order regardless of decision state.

### 5.5.1 Keyboard shortcuts

Press `?` anywhere on the cleanup page (when not typing in a textarea or input) to toggle the shortcut help overlay. Available shortcuts:

| Key | Action |
| --- | --- |
| `j` | Focus next visible card (respects current filters) |
| `k` | Focus previous visible card |
| `K` (shift-k) | Mark focused card as **Keep** |
| `D` (shift-d) | Mark focused card as **Delete** (no confirmation) |
| `S` (shift-s) | Toggle the **Split** editor on the focused card |
| `?` | Show / hide this overlay |
| `Esc` | Hide the overlay |

The focused card gets an accent-colored outline so you can see where you are. Keyboard navigation respects the active filters.

### 5.5.2 Apply-to-similar batch action

After saving a manual `Keep` or `Delete` decision on a card, the cleanup page scans for other PENDING cards whose first ~50 characters match the decided card's text (whitespace-normalized, case-folded). If matches exist, a non-modal banner appears below the decided card offering one-click application of the same action to all matches. Useful for batches of identical garbage (e.g., 30 cards all starting with `Notes ↑1` from a per-article scrape) — turns N cards into one click.

The action is restricted to `keep` and `delete`; `split` decisions are not batch-applied because chunk text differs per citation.

### 5.5.3 Diff view per card

Inside the Split editor on each card, a `Show diff vs. original` toggle reveals a two-column token-level diff: the original `<unstructured_citation>` text on the left with removed tokens highlighted in red, the proposed cleaned text (joined chunks) on the right with added tokens highlighted in green. The diff re-renders on every keystroke as you edit chunk text, so the change is visible live.

### 5.6 Downloading the cleaned XML

Click **Download cleaned XML** at any time. The endpoint:
- Reads the original XML from `uploads/audit_<id>.xml`.
- Walks every `<citation>` element by source line.
- Applies decisions: `keep` is a no-op, `delete` removes the element, `split` replaces it with N new elements with derived keys.
- Writes to `uploads/audit_<id>.cleaned.xml` atomically, then streams the file as an attachment named `<original-stem>.cleaned.xml`.

Citations without a saved decision are left untouched. So you can download mid-review to spot-check progress.

---

## 6. Batch workflow (multi-volume single-journal deposits)

When a journal's reference backfill is split across many volume-level XML files — e.g., Across the Disciplines with 22 separate `atd-volume-N.xml` files, all belonging to one depositor — the batch workflow audits and merges them into a single submission deposit.

### 6.1 Batch upload

The home page has a second upload form labeled **"Batch audit + merge"**. Pick all the XML files you want in one batch (the file dialog supports multi-select with Shift-click or Ctrl-click), optionally name the batch (e.g., `"ATD vols 1-22"`), and submit. Each file is audited independently and tagged with a shared `batch_id`. The page redirects to `/batch/<id>`.

### 6.2 Batch dashboard

The dashboard at `/batch/<id>` shows:

- **Per-batch totals**: file count, total citations, total errors, total warnings, batch creation timestamp.
- **Schema/depositor compatibility check**: scans every file's `<head>/<depositor>/<email_address>` (the canonical Crossref depositor identifier) and every file's schema namespace. If all files share one depositor and one schema, a `"Single depositor across batch — merge is safe"` indicator appears. If files disagree, a red **"Merge blocked"** banner explains exactly which dimension fails, since Crossref can't accept a deposit spanning multiple depositors.
- **Per-file table**: one row per audit with citation count, error/warning/info counts, and links to that file's individual report or cleanup queue. Clicking a row drops you into that file's report or cleanup with a **"← Back to batch: \<name\>"** breadcrumb at the top for easy navigation back.
- **Merge form**: optional `merged_id` input (auto-generated if blank) and a **"Merge & download single deposit XML"** button.

### 6.3 Merge

Click the merge button to produce a single combined deposit XML. The merger:

1. Validates that every file in the batch shares the same schema namespace; halts with a clear error if not.
2. Validates that every file shares the same depositor (matched on `<email_address>`, falling back to `<depositor_name>`); halts if not.
3. Takes the first file's `<head>` envelope as the merged file's envelope. Updates `<doi_batch_id>` to either the user-provided `merged_id` or `merged-<timestamp>`. Only refreshes `<timestamp>` if the source already had one (the `doi_resources_schema` doesn't permit `<timestamp>` in `<head>`, only the full deposit schema does — unconditionally adding one would break XSD validation).
4. For each file in the batch, applies any saved cleanup decisions BEFORE extracting `<doi_citations>` blocks. So the merged file reflects each volume's individual cleanup state.
5. Concatenates every `<doi_citations>` block from every file under the merged `<body>`.
6. Writes atomically to `uploads/batch_<id>.merged.xml` and streams the file as a download with a sanitized filename based on the batch name.

The resulting file is a single Crossref deposit ready for submission via the production endpoint or the test endpoint.

### 6.4 Recommended batch workflow for a multi-volume backfill

1. Upload all N volume-level XMLs as one batch with a descriptive name.
2. On the dashboard, confirm the "single depositor" indicator appears.
3. Click into each file's cleanup queue and click **"Run auto-decide"** with your preferred fallback settings. Most files will resolve to small per-file manual-review piles (mostly long-but-legitimate citations).
4. Spot-check or fully review each file's remaining pending cards.
5. Return to the dashboard. Click **Merge & download**.
6. Submit the merged file to Crossref (production endpoint, or test endpoint first if you want the extra confidence — see the caveat in §11).

## 7. Configuration

### Settings page (`/settings`)

For every registered rule, the Settings page exposes:

- An **enabled** checkbox.
- A **severity** dropdown (`error` / `warning` / `info`) — overrides the rule's default.
- One input per configurable parameter, with the parameter's description as helper text.

Saved settings persist to `config/auditor_config.json` via atomic write (`.part` then rename). The file is JSON in this shape:

```json
{
  "rules": {
    "unstructured_length": {
      "enabled": true,
      "severity": "warning",
      "params": {"min_words": 5, "max_words": 60, "max_year_count": 1, "max_semicolons": 2}
    },
    "doi_format": {"enabled": true, "severity": "error", "params": {}}
  }
}
```

Loading is forgiving: missing rule entries are populated from defaults at audit time via `AuditorConfig.merged_with_defaults()`. So you can hand-edit the file to enable only specific rules and the rest will auto-fill.

### Per-audit config snapshot

Every audit stores the merged config it ran against in the `audits.config_json` column. So if you re-tune a threshold and re-audit, the new finding count is comparable to the prior one's snapshot. Export tools include this metadata.

---

## 8. Pipeline integration

The auditor is designed to be importable from your scraper without involving the Flask UI.

### Minimum viable gate

```python
from auditor import audit
from auditor.models import Severity

with open("deposit.xml", "rb") as f:
    findings = audit(f.read())

errors = [f for f in findings if f.severity == Severity.ERROR.value]
if errors:
    raise SystemExit(f"Audit failed: {len(errors)} error(s); not submitting.")
```

### Loading saved settings

```python
from pathlib import Path
from auditor import audit, AuditorConfig

cfg = AuditorConfig.load(Path("config/auditor_config.json"))
findings = audit(xml_bytes, cfg)
```

### Programmatic config

```python
from auditor import AuditorConfig
from auditor.models import RuleConfig

cfg = AuditorConfig(rules={
    "schema_validate":      RuleConfig(enabled=True,  severity="error",   params={"max_findings": 100}),
    "unstructured_length":  RuleConfig(enabled=True,  severity="warning", params={"max_words": 80}),
    "paragraph_shaped":     RuleConfig(enabled=True,  severity="warning", params={}),
    "duplicate_keys":       RuleConfig(enabled=True,  severity="error",   params={}),
    "doi_format":           RuleConfig(enabled=False, severity="error",   params={}),
})
findings = audit(xml_bytes, cfg)
```

### Reusing the cleanup primitives

The cleanup helpers are independently importable for headless workflows.

```python
from cleanup import propose_splits, match_citation, apply_decisions
from pathlib import Path

text = "Smith, J. (2020). Title... (2007). Other ref..."
chunks = propose_splits(text)            # → ["Smith, J. (2020). Title...", "(2007). Other ref..."]
match  = match_citation(chunks[0])       # → {"doi": "...", "score": 124, "confidence": "high", ...}

decisions = {1234: {"action": "split", "split_chunks": chunks, "crossref_data": [match, None]}}
counts = apply_decisions(Path("deposit.xml"), decisions, Path("deposit.cleaned.xml"))
# counts → {"kept": ..., "deleted": ..., "split_from": 1, "split_into": 2, "untouched": ...}
```

---

## 9. HTTP API reference

All routes are local-only by default (`127.0.0.1:5001`). Responses are HTML except where noted; AJAX endpoints accept and return JSON.

### Public pages

| Method | Path | Purpose |
| --- | --- | --- |
| `GET`  | `/` | Upload forms (single + batch) plus recent audits and batches. |
| `POST` | `/audit` | Multipart upload (`xmlfile`). Runs audit, stores XML and findings, redirects to `/report/<id>`. |
| `POST` | `/batch_audit` | Multipart upload (`xmlfiles`, repeated; optional `batch_name`). Creates a batch and runs an audit per file, tagging each with the new batch_id. Redirects to `/batch/<id>`. |
| `GET`  | `/report/<id>` | Full audit report with findings table and filter dropdowns. Query params: `severity`, `rule`. Shows breadcrumb back to the batch if the audit belongs to one. |
| `GET`  | `/cleanup/<id>` | Cleanup workspace for an audit. Shows breadcrumb back to the batch if the audit belongs to one. |
| `GET`  | `/batch/<id>` | Batch dashboard — per-file table, depositor/schema compatibility check, merge form. |
| `GET`  | `/settings` | Per-rule configuration form. |
| `POST` | `/settings` | Persist form to `config/auditor_config.json`. Redirects back to `/settings` with a flash message. |

### Export endpoints

| Method | Path | Returns |
| --- | --- | --- |
| `GET`  | `/export/<id>/json`  | `application/json`, full audit + every finding as a list of dicts. |
| `GET`  | `/export/<id>/md`    | `text/markdown`, findings grouped by rule. |
| `GET`  | `/export/<id>/csv`   | `text/csv` (UTF-8 BOM), one finding per row. |
| `GET`  | `/export/<id>/xlsx`  | OOXML spreadsheet, two sheets (Summary, Findings). |
| `GET`  | `/export/<id>/pdf`   | `application/pdf`, print-style report. |
| `POST` | `/history/<id>/delete` | Deletes the audit row (cascade-deletes findings and decisions). |

### Cleanup AJAX endpoints

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `POST` | `/cleanup/<id>/match` | `{"text": "<chunk text>", "min_score": 50}` | Citation match JSON. Queries Crossref first; on low confidence or no result, falls back to OpenAlex. Response includes `doi, title, authors, year, container, score, confidence, url, source` (`source` indicates which backend produced the match). Returns `{"empty": true}` if neither backend matched. |
| `POST` | `/cleanup/<id>/decision` | `{"line": 528, "citation_key": "ref52", "action": "split", "split_chunks": [...], "crossref_data": [...], "decided_by": "auto"\|"manual"}` | `{"ok": true}`. Idempotent upsert keyed by `(audit_id, citation_line)`. |
| `POST` | `/cleanup/<id>/fix_duplicate_year` | `{"text": "<full citation text>", "min_score": 50, "fallback": "keep_second"\|"keep_first"\|"crossref_only"}` | Either `{"fixed": "<corrected text>", "match": <result>, "kept_year": "<y>", "dropped_year": "<y>", "method": "..."}` or `{"fixed": null, "reason": "..."}`. |
| `GET`  | `/cleanup/<id>/download` | — | Generates the cleaned XML on demand and streams it as `<stem>.cleaned.xml`. |

### Workflow automation endpoints

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `POST` | `/iterate/<id>` | `{"max_iters": 5, "min_score": 50, "year_fallback": "keep_second"}` | Runs audit → auto-decide → download → re-audit until findings stop dropping. Returns `{"final_audit_id": <id>, "history": [{"iter": N, "audit_id": <id>, "findings": <n>}, …], "iterations": <count>}`. |
| `POST` | `/dryrun/<id>` | `{"username": "<crossref-test-login>", "password": "<password>"}` | POSTs the (cleaned, if decisions exist) XML to `https://test.crossref.org/servlet/deposit` and returns `{"status_code": <int>, "ok": <bool>, "response": "<text>"}`. Credentials are forwarded per request and never stored. Returns 400 if credentials are missing. **Important**: the test endpoint does not mirror production DOIs (see §12). |
| `POST` | `/filter_dois/<id>` | `{"doi_list": ["10.x/a", "10.x/b", ...]}` | Produces a copy of the deposit XML with the listed `<doi_citations>` blocks removed. Useful for dropping article DOIs that aren't yet registered with Crossref. Streams the result as `<stem>.filtered.xml`. |
| `POST` | `/batch/<id>/merge` | Form-encoded: `merged_id` (optional) | Validates depositor/schema compatibility, applies saved cleanup decisions per file, concatenates all `<doi_citations>` blocks under one envelope, streams the merged file as `<batch_name>.merged.xml`. Returns 302 with a flash message if validation fails. |

---

## 10. Database schema

SQLite database at `audits.db` (gitignored). Four tables.

### `batches`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | Auto-increment batch ID. |
| `name` | TEXT | User-supplied or auto-generated batch label. |
| `created_at` | TEXT | `datetime('now')` default. |

### `audits`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | Auto-increment audit ID. |
| `filename` | TEXT | As uploaded. |
| `file_size` | INTEGER | Bytes. |
| `namespace` | TEXT | Detected schema namespace, NULL on parse failure. |
| `citation_n` | INTEGER | Total citations counted via streaming. |
| `error_n` / `warning_n` / `info_n` | INTEGER | Pre-computed finding counts by severity. |
| `config_json` | TEXT | Snapshot of `AuditorConfig` at run time. |
| `xml_path` | TEXT | Local filesystem path to the saved upload. |
| `batch_id` | INTEGER FK → `batches(id)` | Optional. NULL for standalone single-file audits. Indexed for fast per-batch lookup. |
| `created_at` | TEXT | `datetime('now')` default. |

### `findings`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `audit_id` | INTEGER FK → `audits(id)` | Cascade delete. |
| `rule_id` | TEXT | Matches a registered rule's `META.id`. |
| `severity` | TEXT | `error` / `warning` / `info`. |
| `message` | TEXT | Rule-formatted, includes parameter values where relevant. |
| `line` / `xpath` / `citation_key` / `snippet` | various | Optional. Filled when the rule provides them. |

Indexed on `audit_id`, `rule_id`, `severity` for fast filter queries.

### `cleanup_decisions`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `audit_id` | INTEGER FK → `audits(id)` | Cascade delete. |
| `citation_line` | INTEGER | Source line of the `<citation>` in the original XML. Unique per audit. |
| `citation_key` | TEXT | The citation's `key` attribute (informational; not used for lookup). |
| `action` | TEXT | `keep` / `delete` / `split`. |
| `split_chunks` | TEXT | JSON list of strings; the chunks the cleaned XML should produce. |
| `crossref_data` | TEXT | JSON list of match dicts (one per chunk), parallel to `split_chunks`. |
| `notes` | TEXT | `auto` or `manual` — used to distinguish auto-decided cards in the UI. |
| `decided_at` | TEXT | `datetime('now')` default; updated on conflict. |

`UNIQUE(audit_id, citation_line)` — the `upsert_cleanup_decision` helper uses `ON CONFLICT(...) DO UPDATE`.

---

## 11. Architecture

### File layout

```
Crossref Auditor/
├── app.py                       # Flask entry point + all HTTP routes
├── db.py                        # SQLite layer (init, upserts, reads)
├── requirements.txt
├── fetch_xsds.py                # One-time XSD downloader
├── README.md / DOCUMENTATION.md
│
├── auditor/                     # Audit core (importable, no Flask)
│   ├── core.py                  # audit() orchestrator, iterparse streaming
│   ├── models.py                # Finding, Severity, RuleMeta, AuditorConfig
│   └── rules/
│       ├── __init__.py          # Rule registry, decorator-based
│       ├── _util.py             # Local-name lookup, snippet helpers
│       ├── schema.py            # XSD validation
│       ├── encoding.py          # mojibake sniff
│       ├── unstructured.py      # length + glued-refs
│       ├── paragraph_shaped.py  # body text detection
│       ├── doi_format.py
│       ├── authors.py
│       ├── titles.py
│       ├── dates.py
│       ├── pages.py
│       ├── orcid.py
│       └── duplicates.py        # post-pass, per-citation_list scoped
│
├── cleanup/                     # Cleanup core (importable, no Flask)
│   ├── splitter.py              # Year-anchored split heuristic
│   ├── crossref_match.py        # REST API client with polite headers
│   └── xml_writer.py            # Apply decisions, write cleaned XML
│
├── exporters/                   # Audit findings → file formats
│   ├── json_exp.py
│   ├── markdown_exp.py
│   ├── csv_exp.py
│   ├── xlsx_exp.py              # openpyxl
│   └── pdf_exp.py               # xhtml2pdf
│
├── templates/                   # Jinja2 templates
│   ├── base.html
│   ├── index.html               # Upload + history
│   ├── report.html              # Findings table + filters + exports
│   ├── settings.html            # Rule config form
│   └── cleanup.html             # Card review UI + auto-decide JS
│
├── static/style.css             # Single stylesheet
│
├── config/
│   ├── auditor_config.json      # Saved settings (created on first save)
│   └── crossref_xsd/            # Downloaded by fetch_xsds.py
│
├── samples/                     # Test inputs
│   └── smoke_test.xml
│
├── uploads/                     # Saved uploaded XMLs + cleaned outputs
│   ├── audit_<id>.xml
│   └── audit_<id>.cleaned.xml
│
└── audits.db                    # SQLite (gitignored)
```

### Component roles

- **`auditor/`** is the audit core. Pure Python, no Flask, no I/O outside what callers pass in. Importable from any pipeline.
- **`cleanup/`** is the cleanup core. Same constraints as `auditor/`.
- **`exporters/`** convert in-memory findings to file formats. Stateless; each module exports a single `to_<fmt>(meta_dict, findings) → bytes`.
- **`db.py`** is the only module that knows about SQLite. Uses a context-manager-based connection pattern with auto-commit on success and rollback on exception.
- **`app.py`** is the Flask layer. Imports `auditor`, `cleanup`, `exporters`, and `db` and wires them to HTTP routes. Owns the upload-saving and cleanup orchestration.

### Streaming model

The audit core uses **two-phase parsing** to handle large deposits without loading every citation into Python:

1. **Document phase.** `lxml.etree.fromstring(xml_bytes)` parses the entire tree once. Document-scoped rules see the root element and the raw bytes. After this phase, the root is freed.
2. **Citation phase.** `lxml.etree.iterparse(BytesIO(xml_bytes), events=("end",), tag=citation_tag)` streams one `<citation>` at a time. Each citation-scoped rule sees the element; after rules run, the element is `.clear()`ed and any preceding siblings are removed from the tree to keep memory bounded. Cross-citation state (duplicate-key tracker, citation count) accumulates in `AuditContext`.
3. **Post phase.** Post-scope rules read the accumulated state and emit final findings.

A 4 MB / 7,000-citation file holds peak memory under ~50 MB during audit.

### Rule registry

Rules register themselves at import time via decorators in `auditor/rules/__init__.py`:

```python
@register_citation_rule(META)
def my_rule(elem, ctx) -> list[Finding]:
    ...
```

The `_import_all_rules()` function at the bottom of that module imports every rule submodule, triggering registration. Adding a new rule means: write a module under `auditor/rules/`, define a `META: RuleMeta` and a registered check function, append the module name to `_import_all_rules`. The Settings page picks it up automatically.

---

## 12. Limitations and known issues

- **Schema validation gaps.** Four mathml/xml dependency XSDs that Crossref's schemas reference don't resolve at the URLs declared in the includes. lxml falls back to alternates so validation still works, but `fetch_xsds.py` reports "Fetched 29/33 XSD files" — this is expected.
- **Crossref scoring inconsistency.** Bibliographic relevance scores aren't normalized across query types. A textbook may legitimately score 49 even when matched correctly. Treat the threshold as journal-article-tuned.
- **Splitter heuristic is conservative.** Citations glued without a clean sentence boundary before the second `(YYYY)` aren't auto-split; the editor still proposes a single chunk and the user can manually break it.
- **Author-block detection.** The `paragraph_shaped` rule's author detector handles common patterns (`Smith, J.`, `Smith J,`, `MacDonald, K.`, `Abu-Hamour, B.`, `American Psychological Association.`) but won't recognize every institutional-author variant. False-positive rate measured at <2% on Reflections-scale data.
- **No undo for cleanup decisions.** Decisions are upserted; clicking a different action overwrites. To reset a card, manually reload the page after deleting the row from `cleanup_decisions` (or mark all "Keep").
- **Single-user, local only.** No authentication, no multi-tenancy, no remote access by default. Designed for single-developer workstations.
- **Crossref test sandbox does not mirror production DOIs.** The `/dryrun` endpoint posts to `https://test.crossref.org/servlet/deposit`, which uses a separate database. Record-level "Referenced DOI not found in Crossref" failures from the dryrun do not necessarily mean the DOI is unregistered — it may exist in production but not in the test sandbox. **Verify failed parent DOIs against the public Crossref REST API** (`https://api.crossref.org/works/<DOI>`) before assuming a real problem. Per-citation business-rule errors (the kind covered by `incomplete_structured_citation`) ARE the same in test and production, so those remain actionable.
- **Batch merge is single-depositor only.** A Crossref deposit can only target DOIs owned by one depositor account. The `/batch/<id>/merge` endpoint validates that all files in the batch share one depositor (matched on `<email_address>` in `<head>/<depositor>`) and one schema namespace; it refuses to merge across depositors. Multi-journal cross-depositor workflows require submitting each journal as a separate deposit.

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `python fetch_xsds.py` runs and exits with `0/30 fetched` | No internet or proxy blocking `www.crossref.org` | Check connectivity; rerun. |
| Audit reports `Schema file crossref4.3.6.xsd not found` | XSDs never downloaded | Run `python fetch_xsds.py`. |
| Audit reports `Could not determine Crossref schema for namespace None; schema validation skipped` | XML root element doesn't declare a Crossref namespace | Check that your scraper emits `xmlns="http://www.crossref.org/..."` on `<doi_batch>`. |
| Cleanup page redirects to report with "Original XML for this audit isn't available" | Audit was created before the upload-saving feature was added | Re-upload the file to create a fresh audit. |
| Crossref match returns "Crossref error: HTTPSConnectionPool…" | Rate-limited or transient API issue | Wait a moment and retry that chunk; reduce concurrency by raising the per-chunk delay in `cleanup.html` JS. |
| `pip install xhtml2pdf` fails on Windows | Old pip without wheel support | Upgrade pip: `python -m pip install --upgrade pip`, then reinstall. |
| 500 error on Flask UI | Template syntax error after manual edit, or stale cached templates | Restart `python app.py`. |
| Cleanup page renders but Run auto-decide does nothing | Browser console shows JS error | Open DevTools, check console; usually a stale browser cache — hard reload (Ctrl+F5). |
| Batch dashboard shows red "Merge blocked: different depositors" | Files in the batch identify different `<email_address>` values in their `<head>/<depositor>` blocks | Batch merge requires single-depositor inputs. If the files genuinely share a depositor but have inconsistent metadata, edit the source XMLs so `<email_address>` matches across them. Otherwise, submit each depositor's files as separate Crossref deposits. |
| Batch merge fails with "Cannot merge: inputs use different schema namespaces" | One file uses `crossref.org/schema/X.Y.Z` (full deposit) and another uses `crossref.org/doi_resources_schema/X.Y.Z` (citation update) | Crossref deposits must use a single schema. Re-run the per-volume scrapers so all files emit the same schema, then re-upload. |
| Dryrun reports "Referenced DOI not found in Crossref" but `doi.org` resolves the URL fine | The test endpoint sandbox doesn't mirror production DOIs | Not a real problem. Verify against `https://api.crossref.org/works/<DOI>` to confirm production registration. The full submission against the production endpoint will succeed for those records. |
| Sort order changed after upgrade — decided cards moved to bottom | Default sort changed to "Pending first, decided at bottom" | Use the Sort dropdown to switch back to "By line number" if you prefer strict source order. |
| Cleanup queue is shorter than expected after upgrade | `embedded_doi` and `stuck_whitespace` are now `info`-only and excluded from the queue | Both rules still fire and show in the audit report — only the cleanup queue excludes them. Set `severity` back to `warning` in `config/auditor_config.json` and add the rule_id to `cleanup_rule_ids` in `app.py` if you want them in the queue. |

---

*Last updated: 2026-05-06 against tool revision matching `audits.db` audit IDs through #18.*
