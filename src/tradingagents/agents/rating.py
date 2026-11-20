"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

The same five-tier scale (Buy, Overweight, Hold, Underweight, Sell) is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision; its free-text fallback is read here)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.

``extract_rating`` returns ``None`` when no rating can be found, and every
caller turns that into ``REVIEW`` rather than a tradeable position: a decision
nobody can read is not a Hold, and a Hold recorded in its place is quoted back to
the next run as a call that was never made (#1170).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

# Signal emitted when the model's decision has no recognizable rating. It is not
# a tradeable position: it flags output that needs a human/re-run rather than
# silently degrading to Hold. Callers that map the signal onto the 5-tier enum
# (e.g. ``PortfolioRating(signal)``) should guard with ``is_review`` first.
RATING_REVIEW = "REVIEW"

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}

# Matches "Rating: X" / "rating - X" / "Rating — **X**" — tolerates markdown
# bold wrappers and any dash or colon a model writes as the separator. "rating"
# must start a word, so "Operating margin: Sell-side" is not a label.
_RATING_LABEL_RE = re.compile(r"(?<![a-z])rating\b[^:\-\u2010-\u2015]*[:\-\u2010-\u2015][\s*]*(\w+)",
                              re.IGNORECASE)

# The decision's own rating line, in the shape the Portfolio Manager is asked to
# open with ("- **Rating**: X", "**Final Rating**: X", "## Our rating - X"): an
# optional list marker, emphasis and heading marks, and only words naming the
# decision itself before "rating". "Consensus rating: Buy" or "Trader's rating:
# Buy" is someone else's rating.
_OWN_QUALIFIER = r"(?:(?:final|our|overall|my|recommended|updated|revised|new|current)\s+)*"
_RATING_LINE_RE = re.compile(
    r"\s*(?P<item>(?:[-+*\u2022]|\d+[.)])\s+)?[\s*_#]*" + _OWN_QUALIFIER
    + r"rating[^\w:\-\u2010-\u2015]*[:\-\u2010-\u2015][\s*]*(?P<value>\w+)",
    re.IGNORECASE,
)

# A line presenting the scale rather than a decision ("Rating Scale: Buy, ...").
_RATING_SCALE_RE = re.compile(r"rating\s*(scale|options|legend)", re.IGNORECASE)

def extract_rating(text: str) -> str | None:
    """Extract a 5-tier rating from its label, or ``None`` if there is none.

    Reads an explicit "Rating: X" label (tolerant of markdown bold) in the
    NFKC-normalized text, so fullwidth punctuation like ``Rating：Overweight``
    matches as ASCII does: the decision's opening rating line, else its own
    rating lines or, failing those, every label, when they agree.
    """
    if not text:
        return None
    norm = unicodedata.normalize("NFKC", text)

    # The decision is asked to open with its rating, so a first line (after any
    # headings) in that shape is the call. A list item there may also be a quote
    # heading a list of other parties' ratings, so it counts with the decision's
    # other rating lines, which leave out list items; failing those, every label
    # counts. Either way they must agree: ratings that differ, with nothing
    # marking which one is the call, are no call (#1170). Lines presenting the
    # scale itself are a legend the model echoed, not a call.
    lines = [line for line in norm.splitlines() if line.strip() and not _RATING_SCALE_RE.search(line)]
    first = next((line for line in lines if not line.lstrip().startswith("#")
                  or _RATING_LINE_RE.match(line)), "")
    m = _RATING_LINE_RE.match(first)
    opening = m if m and m.group("value").lower() in _RATING_SET else None
    if opening and not opening.group("item"):
        return opening.group("value").capitalize()

    own = [opening.group("value").capitalize()] if opening else []
    labels = []
    for line in lines:
        m = _RATING_LINE_RE.match(line)
        if m and not m.group("item") and m.group("value").lower() in _RATING_SET:
            own.append(m.group("value").capitalize())
        labels += [v.capitalize() for v in _RATING_LABEL_RE.findall(line) if v.lower() in _RATING_SET]
    # Without a label there is no call to read: a rating word in the prose may be
    # one the text argues against ("not a Sell"), and reading it reports a
    # direction nobody decided.
    found = own or labels
    return found[0] if found and len(set(found)) == 1 else None


def parse_rating(text: str, default: str = RATING_REVIEW) -> str:
    """Extract a 5-tier rating, or ``REVIEW`` when the decision has none.

    For callers that need a string for every decision, such as the memory log's
    entry tag. The default is the review sentinel, never a tradeable rating.
    """
    rating = extract_rating(text)
    return rating if rating is not None else default


def run_rating(final_state: dict) -> str:
    """A finished run's rating: the Portfolio Manager's own, else read from its decision.

    The fallback serves a state without ``final_rating``, such as a run an older
    version completed and a checkpoint hands back unchanged.
    """
    return final_state.get("final_rating") or parse_rating(final_state.get("final_trade_decision", ""))


def is_review(signal: str) -> bool:
    """Whether a signal is the non-tradeable REVIEW sentinel (#1170)."""
    return signal == RATING_REVIEW


# ---------------------------------------------------------------------------
# Final-decision price validation (Implements: REQ-TA-FR-004; REQ-TA-INV-001).
#
# The Portfolio Manager's final answer carries two price levels. They are
# validated *before* the decision is adopted, and the validator reads the raw
# values the model wrote rather than a coerced Pydantic view, so ``"15%"`` is
# classified as *invalid* (a number the model supplied that is not a price)
# rather than *missing* (a field it never gave). Issue #32 fixes the contract.
# ---------------------------------------------------------------------------

# The two price levels, in the order the reasons are accumulated.
PRICE_FIELDS: tuple[str, ...] = ("entry_price", "stop_loss")

# Ratings that must state both levels (enter or add to a position).
PRICE_REQUIRED_RATINGS: frozenset[str] = frozenset({"Buy", "Overweight"})

# Machine-readable review reasons (Issue #32). Stable strings, one per field.
REASON_UNRESOLVED_RATING = "unresolved_rating"
REASON_MISSING_ENTRY_PRICE = "missing_entry_price"
REASON_MISSING_STOP_LOSS = "missing_stop_loss"
REASON_INVALID_ENTRY_PRICE = "invalid_entry_price"
REASON_INVALID_STOP_LOSS = "invalid_stop_loss"

REVIEW_REASONS: tuple[str, ...] = (
    REASON_UNRESOLVED_RATING,
    REASON_MISSING_ENTRY_PRICE,
    REASON_MISSING_STOP_LOSS,
    REASON_INVALID_ENTRY_PRICE,
    REASON_INVALID_STOP_LOSS,
)

_REASON_MISSING = {
    "entry_price": REASON_MISSING_ENTRY_PRICE,
    "stop_loss": REASON_MISSING_STOP_LOSS,
}
_REASON_INVALID = {
    "entry_price": REASON_INVALID_ENTRY_PRICE,
    "stop_loss": REASON_INVALID_STOP_LOSS,
}

# A price the model may write: an integer or decimal number as JSON or as text,
# with an optional sign, but only in ASCII with an integer part (approved
# contract; Issue #32). Grouping separators, currency symbols, percentages and
# ranges are not prices here. A leading dot (``".5"``) is not a price, and only
# ASCII ``0-9`` digits count — a fullwidth/Unicode digit is not a digit here. A
# bare ``NaN``/``Infinity`` token is a *decoding* failure, handled before this,
# not a value that reaches the syntax check. ``[0-9]`` (not ``\d``) keeps the
# grammar ASCII-only, since ``\d`` matches Unicode digits like ``５``.
_PRICE_RE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


class PriceValueError(ValueError):
    """A supplied price that is not usable (Implements: REQ-TA-FR-004)."""


def _is_absent(value: Any) -> bool:
    """Whether a price field was never supplied.

    ``None`` and a missing key both mean "not given". A blank string is a value
    the model wrote, so it is *invalid* rather than absent (Issue #32).
    """
    return value is None


def normalise_price(value: Any) -> float:
    """Normalise one supplied price to a finite, strictly positive ``float``.

    Accepts a JSON number (int/float, but not a bool) or a trimmed ASCII numeric
    string; rejects everything else with :class:`PriceValueError`. Binary64
    rounding applies, as the approved contract states; there is no exact-decimal
    or tick-size guarantee (REQ-TA-FR-004). An integer too large for a finite
    ``float`` overflows to infinity and is rejected as an invalid price rather
    than raising ``OverflowError`` (Issue #32 FR004-03).
    """
    if isinstance(value, bool):
        raise PriceValueError("a boolean is not a price")
    if isinstance(value, int):
        try:
            number = float(value)
        except OverflowError:
            raise PriceValueError("a price must be finite") from None
    elif isinstance(value, float):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.isascii() or not _PRICE_RE.match(text):
            raise PriceValueError(f"not a numeric price: {value!r}")
        number = float(text)
    else:
        raise PriceValueError(f"not a numeric price: {value!r}")
    if not math.isfinite(number):
        raise PriceValueError(f"a price must be finite: {value!r}")
    if number <= 0.0:
        raise PriceValueError(f"a price must be greater than zero: {value!r}")
    return number


def validate_final_decision(
    rating: str | None,
    prices: Mapping[str, Any],
    *,
    price_required: bool | None = None,
) -> tuple[str, list[str], dict[str, float]]:
    """Validate a decoded decision's rating and price levels (REQ-TA-FR-004).

    ``rating`` is the resolved five-tier rating, or ``None`` when the response
    could not be resolved. ``prices`` is the *raw* mapping the model wrote (the
    values as received, before any coercion), so ``"15%"`` can be told apart
    from an omitted field.

    Returns ``(final_rating, reasons, normalised_prices)``:

    - an unresolved rating short-circuits to ``("REVIEW", ["unresolved_rating"], {})``
      and no price policy is chosen (REQ-TA-INV-001);
    - a valid rating accumulates one reason per price field, entry first, and
      any valid supplied price is returned normalised to a ``float``;
    - any reason makes ``final_rating`` ``REVIEW`` (a non-actionable result).

    ``price_required`` overrides the per-rating policy for the ``prices``
    mapping only; the caller normally lets it follow ``rating`` (both levels for
    Buy/Overweight, optional for the rest).
    """
    if rating is None or rating == RATING_REVIEW or rating not in RATINGS_5_TIER:
        return RATING_REVIEW, [REASON_UNRESOLVED_RATING], {}

    required = PRICE_REQUIRED_RATINGS.__contains__(rating) if price_required is None else price_required
    reasons: list[str] = []
    normalised: dict[str, float] = {}
    for field in PRICE_FIELDS:
        value = prices.get(field)
        if _is_absent(value):
            if required:
                reasons.append(_REASON_MISSING[field])
            continue
        try:
            normalised[field] = normalise_price(value)
        except PriceValueError:
            reasons.append(_REASON_INVALID[field])
    return (RATING_REVIEW if reasons else rating), reasons, normalised
