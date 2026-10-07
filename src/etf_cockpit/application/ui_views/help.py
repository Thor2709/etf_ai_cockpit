"""Read-only view model for Help & Glossary (FINAL_UI_SPEC 6.9, 8).

The glossary registry (``configs/glossary.yaml``) is checksummed and its model forbids extra fields, so the three
presentation fields (where used, source, related) are derived here from the registry and the page help text instead
of being stored in the data file. Nothing here grants authority.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

SEGMENTS = ("Glossary", "This page", "Boundaries")
GLOSS_LIMIT = 28


@dataclass(frozen=True)
class GlossaryTerm:
    term: str
    slug: str
    gloss: str
    definition: str
    authority_note: str
    where_used: tuple[str, ...]  # page titles; empty = not named in any page help
    related: tuple[str, ...]


# Reference terms of spec 6.9 that the registry does not carry yet: (term, short gloss, definition).
SUPPLEMENTARY_TERMS: tuple[tuple[str, str, str], ...] = (
    (
        "Score",
        "0–10 evidence",
        "A 0–10 summary of how strongly the local evidence supports an instrument today. It combines quality, risk "
        "and cost evidence from adjusted prices. Authority remains bounded by evidence and policy: a high score "
        "never creates an order.",
    ),
    ("Evidence quality", "data completeness",
     "How complete, fresh and consistent the data behind a score is. Low quality lowers authority; it never "
     "becomes zero."),
    ("Execution authority", "always none",
     "The right to place orders. This application never holds it: execution_allowed is always false."),
    ("Adjusted prices", "dividends & splits",
     "Prices adjusted for dividends and splits, used for every return so corporate actions do not distort results."),
    ("Walk-forward", "time-ordered testing",
     "Testing on rolling, time-ordered windows so each test only uses information available at that time."),
    ("Shadow only", "no promotion",
     "A model or rule that is observed alongside the baseline but is not allowed to change a score or a gate."),
    ("Point-in-time", "no look-ahead",
     "Using only data that was known at the decision date, including later revisions only when they were published."),
)


def slugify(term: str) -> str:
    return term.casefold().replace(" ", "-").replace("/", "-")


# Order of the reference list (spec 6.9); every other term follows in registry order.
REFERENCE_ORDER = (
    "score", "evidence quality", "execution authority", "adjusted prices", "drawdown", "walk-forward",
    "shadow only", "point-in-time",
)


def short_gloss(text: str) -> str:
    """The first clause of the authority note (before ';' or '.'), at most GLOSS_LIMIT characters."""
    text = re.split(r"[;.]", (text or "").strip(), maxsplit=1)[0].strip()
    return text if len(text) <= GLOSS_LIMIT else text[: GLOSS_LIMIT - 1].rstrip() + "…"


def _mentions(text: str, term: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(term.casefold())}(?![\w-])", text.casefold()) is not None


def build_terms(
    entries: Iterable[object],
    page_help: Mapping[str, str],
    page_titles: Mapping[str, str],
) -> tuple[GlossaryTerm, ...]:
    """Registry entries (+ the spec reference terms not in the registry) with derived presentation fields."""
    base = [(e.term, short_gloss(e.authority_note), e.definition, e.authority_note) for e in entries]
    known = {term.casefold() for term, *_ in base}
    base += [(t, g, d, "") for t, g, d in SUPPLEMENTARY_TERMS if t.casefold() not in known]
    rank = {name: index for index, name in enumerate(REFERENCE_ORDER)}
    base.sort(key=lambda item: rank.get(item[0].casefold(), len(rank)))  # stable: registry order after the reference
    out: list[GlossaryTerm] = []
    for term, gloss, definition, note in base:
        used = tuple(
            page_titles.get(route, route) for route, text in page_help.items() if _mentions(text, term)
        )[:3]
        related = tuple(
            other for other, *_ in base
            if other.casefold() != term.casefold() and (_mentions(definition, other) or _mentions(note, other))
        )[:3]
        out.append(GlossaryTerm(term, slugify(term), gloss, definition, note, used, related))
    return tuple(out)


def filter_terms(terms: Sequence[GlossaryTerm], query: str) -> list[GlossaryTerm]:
    needle = (query or "").strip().casefold()
    return [t for t in terms if not needle or needle in t.term.casefold() or needle in t.gloss.casefold()]


def find_term(terms: Sequence[GlossaryTerm], slug: str) -> GlossaryTerm | None:
    wanted = (slug or "").casefold()
    return next((t for t in terms if t.slug == wanted), None)


def sentences(text: str) -> list[str]:
    """Split page help into sentences (used for the "How to read it" rows)."""
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def related_terms_for(text: str, terms: Sequence[GlossaryTerm], limit: int = 6) -> tuple[str, ...]:
    return tuple(t.term for t in terms if _mentions(text, t.term))[:limit]
