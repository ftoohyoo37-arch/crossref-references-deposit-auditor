from __future__ import annotations

from typing import Any, Callable

from ..models import Finding, RuleMeta

DocumentRuleFn = Callable[[Any, bytes, "AuditContext"], list[Finding]]
CitationRuleFn = Callable[[Any, "AuditContext"], list[Finding]]
PostRuleFn = Callable[["AuditContext"], list[Finding]]

_DOCUMENT_RULES: dict[str, tuple[RuleMeta, DocumentRuleFn]] = {}
_CITATION_RULES: dict[str, tuple[RuleMeta, CitationRuleFn]] = {}
_POST_RULES: dict[str, tuple[RuleMeta, PostRuleFn]] = {}


def register_document_rule(meta: RuleMeta):
    def decorator(fn: DocumentRuleFn) -> DocumentRuleFn:
        _DOCUMENT_RULES[meta.id] = (meta, fn)
        return fn
    return decorator


def register_citation_rule(meta: RuleMeta):
    def decorator(fn: CitationRuleFn) -> CitationRuleFn:
        _CITATION_RULES[meta.id] = (meta, fn)
        return fn
    return decorator


def register_post_rule(meta: RuleMeta):
    def decorator(fn: PostRuleFn) -> PostRuleFn:
        _POST_RULES[meta.id] = (meta, fn)
        return fn
    return decorator


def all_rule_metas() -> list[RuleMeta]:
    metas: list[RuleMeta] = []
    for d in (_DOCUMENT_RULES, _CITATION_RULES, _POST_RULES):
        for meta, _ in d.values():
            metas.append(meta)
    return metas


def document_rules() -> list[tuple[RuleMeta, DocumentRuleFn]]:
    return list(_DOCUMENT_RULES.values())


def citation_rules() -> list[tuple[RuleMeta, CitationRuleFn]]:
    return list(_CITATION_RULES.values())


def post_rules() -> list[tuple[RuleMeta, PostRuleFn]]:
    return list(_POST_RULES.values())


def _import_all_rules() -> None:
    """Trigger registration of every rule module."""
    from . import (  # noqa: F401
        schema,
        unstructured,
        doi_format,
        authors,
        titles,
        dates,
        pages,
        orcid,
        duplicates,
        encoding,
        paragraph_shaped,
        repeat_author_marker,
        journal_footer,
        duplicate_year,
        footnote_artifact,
        notes_section,
    )


_import_all_rules()
