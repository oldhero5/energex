"""Partition definitions (EIA weekly / ERCOT daily / NOAA monthly).

EIA/ERCOT partitions are populated in phases 5-7; the NOAA monthly partition is live.
"""

import dagster as dg

# NOAA nClimDiv degree days are monthly. The partition key indexes the valid_time month;
# for the whole-file bitemporal_replace source it drives the as_of cadence and the
# live-vs-reconstructed split (spec §5.6). Default partition timezone is UTC.
NOAA_MONTHLY = dg.MonthlyPartitionsDefinition(start_date="2020-01-01")
