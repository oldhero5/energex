"""Connector contract — the boundary every source adapter implements (spec §5.2).

``Connector.fetch()`` returns a ``FetchResult`` whose ``frame`` carries
``instrument_id`` + tz-aware-UTC ``valid_time`` + value columns, plus provenance
(``source``, ``fetched_at``, ``source_url``) and ``complete_over_range`` — ``True``
iff the frame is the full as-known series for its ``valid_time`` span (the
merge-vs-replace signal for revised sources; always ``False`` for a continuous
degenerate stream).

Framework- AND storage-agnostic: this module MUST NOT import arcticdb.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

import pandas as pd


@dataclass(frozen=True)
class FetchResult:
    """One source pull. ``fetched_at`` is the tz-aware-UTC knowledge time."""

    frame: pd.DataFrame
    source: str
    fetched_at: datetime
    source_url: str
    complete_over_range: bool


@runtime_checkable
class Connector(Protocol):
    source: str

    def fetch(self, window_start: date, window_end: date) -> FetchResult: ...
