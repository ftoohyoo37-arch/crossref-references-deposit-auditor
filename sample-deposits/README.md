# Sample deposits

Two small `<doi_batch>` XMLs you can upload to a fresh Auditor instance to see what the tool does. Both are toy data — fake DOIs (`10.99999/…`), made-up batch IDs, and a depositor email of `deposits@example.org`. Nothing here resolves; nothing here would actually deposit.

## What's in each file

**`clean-deposit.xml`** — Two articles, seven citations total, all in good shape. Uploading this to the Auditor produces 0 findings against the heuristic rules. Useful for confirming the install works and for showing what a tidy deposit looks like.

**`dirty-deposit.xml`** — One article, eight citations, seven of which have planted problems for the audit rules to catch. The eighth is clean so you can see the difference. Each citation has an inline XML comment naming the rule that should flag it:

| `key` | Planted issue | Rule that flags it |
|---|---|---|
| `ref1` | Two refs concatenated into one `<unstructured_citation>` | `glued_citations` |
| `ref2` | `<doi>` element carries `https://doi.org/` prefix | `doi_format` |
| `ref3` | Repeat-author `———.` marker not expanded | `repeat_author_marker` |
| `ref4` | Body-prose paragraph mistakenly captured as a citation | `paragraph_shaped` |
| `ref5` | Duplicate year (`1992 1992`) from OCR scrambling | `duplicate_year` |
| `ref6` | Future-dated year (`2099`) | `future_year` |
| `ref7` | Stuck internal whitespace from OCR | `stuck_whitespace` |
| `ref8` | None (clean control) | — |

## How to use them

Start the Auditor:

```bash
python app.py    # http://localhost:5001
```

Then upload either file at the index page. For the dirty deposit you should see roughly seven findings on the report page, each with a Keep / Delete / Split card you can act on.

The Auditor's bulk auto-decide pass (Cleanup → "Auto-decide all") will resolve most of these without manual review — for instance, stripping the `https://doi.org/` prefix on ref2 or splitting ref1 along the obvious break. The remaining cases that need human judgment (ref4's paragraph-shaped content, for instance) stay in the review queue.

## Making your own

The XML structure is straightforward — see `clean-deposit.xml` for a minimal valid example. If you have an actual `<doi_batch>` from your scraper pipeline, that's better test data than these toys; just upload it directly.

Note that the Auditor works against the *reference deposit* schema (`doi_resources_schema/4.3.6`), which is what you submit to attach a citation list to existing DOIs. It does not currently audit *content registration* deposits (the `journal_article` schema used to mint new DOIs), though that's a reasonable feature request if you have a use case.
