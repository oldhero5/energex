"""Symbology guardrail: every entry's revision_mode must match its library class."""

from __future__ import annotations

import pytest

from energex.core import symbology
from energex.core.exceptions import SymbologyError


def test_every_entry_mode_matches_library_class():
    for instrument_id, (library, _symbol, mode) in symbology._TABLE.items():
        assert mode == symbology.LIBRARY_MODE[library], (
            f"{instrument_id}: mode {mode!r} != library {library!r} class "
            f"{symbology.LIBRARY_MODE[library]!r}"
        )


def test_resolve_revision_mode_and_symbol_lookups():
    assert symbology.resolve("CME.CL.CLF26") == ("prices.futures", "CL_CLF26")
    assert symbology.revision_mode("CME.CL.CLF26") == "bitemporal_merge"
    assert symbology.mode_for_symbol("CL_FRONT") == "degenerate"
    assert symbology.library_for_symbol("hdd_texas") == "weather"
    assert symbology.contracts_for("crude") == ["CL_CLF26", "CL_CLG26"]


def test_unknown_identifiers_raise():
    with pytest.raises(SymbologyError):
        symbology.resolve("NOPE.X.Y")
    with pytest.raises(SymbologyError):
        symbology.mode_for_symbol("not_a_symbol")
    with pytest.raises(SymbologyError):
        symbology.contracts_for("unobtanium")
