"""The page column, and the blocks that have to line up inside it.

There is no browser here, so these are not visual checks — they are checks on
the few stylesheet facts that a block's width actually depends on, because
each of them has gone wrong once. A `<figure>` carries a browser default
`margin: 1em 40px`, so a full-width card built on one reads 80px narrower
than the `section` and `ul` blocks beside it unless the margin is reset; and
the page column is stated twice, once for the page and once for the alert
banner above it, which have to agree.
"""

from __future__ import annotations

import re
from pathlib import Path

CSS = Path("app/static/css/app.css").read_text()
TEMPLATES = Path("app/templates")

#: Comments first: one sitting above a rule would otherwise be read as part
#: of that rule's selector.
BARE_CSS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)

#: Good enough for a flat stylesheet with no nesting. A rule inside @media
#: still matches on its own, because a selector cannot contain a brace.
_RULE = re.compile(r"(?P<sel>[^{}]+)\{(?P<body>[^{}]*)\}", re.S)


def _block(selector: str) -> str:
    """The declarations of the first rule whose selector list matches."""
    for found in _RULE.finditer(BARE_CSS):
        selectors = [one.strip() for one in found.group("sel").split(",")]
        if selector in selectors:
            return found.group("body")
    raise AssertionError(f"no rule for {selector!r}")


# --- Browser defaults that change a block's width -----------------------


def test_figures_have_their_default_margin_reset():
    """`figure { margin: 1em 40px }` is the browser default. Left in, the
    ribbon card renders 80px narrower than the jar grid under it."""
    assert "margin: 0" in _block("figure")


def test_every_figure_in_the_templates_is_covered_by_that_reset():
    """A bare `figure` selector covers all of them, which is the point of
    resetting it rather than patching each card."""
    figures = [
        path
        for path in TEMPLATES.rglob("*.html")
        if "<figure" in path.read_text()
    ]
    assert figures, "expected some figures to exist"
    # The reset is on the element, so no class can escape it.
    assert re.search(r"(^|\n)figure\s*\{", BARE_CSS)


def test_the_cards_that_span_the_column_set_their_own_vertical_rhythm():
    """Resetting the margin takes the figure's vertical spacing with it, so
    each full-width figure card has to say what it wants instead."""
    for selector in (".ribbon-card", ".chart-card"):
        body = _block(selector)
        assert "margin" in body, f"{selector} has no margin of its own"


# --- One column width ---------------------------------------------------


def test_the_page_column_is_stated_once_as_a_token():
    assert "--page-max:" in _block(":root")


def test_the_page_and_the_alert_banner_share_that_token():
    """The banner sits above the page and has to line up with it."""
    for selector in (".wrap", ".alert-banner-inner"):
        assert "max-width: var(--page-max)" in _block(selector), selector


def test_no_block_pins_its_own_column_width_in_pixels():
    """A second hard-coded width is how the two drifted apart before."""
    pinned = re.findall(r"max-width:\s*(\d{4})px", BARE_CSS)
    assert pinned == [], f"hard-coded column widths left behind: {pinned}"
