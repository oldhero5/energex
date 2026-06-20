"""Partition definitions (EIA weekly / ERCOT daily / NOAA monthly).

ERCOT partitions are populated in phase 7; the EIA weekly and NOAA monthly partitions
are live.
"""

import dagster as dg

# NOAA nClimDiv degree days are monthly. The partition key indexes the valid_time month;
# for the whole-file bitemporal_replace source it drives the as_of cadence and the
# live-vs-reconstructed split (spec §5.6). Default partition timezone is UTC.
NOAA_MONTHLY = dg.MonthlyPartitionsDefinition(start_date="2020-01-01")

# EIA weekly fundamentals (spec §5.6). day_offset aligns the partition to the release
# cadence (0=Sun..6=Sat): gas storage releases Thursday (day_offset=4), crude stocks
# Wednesday (day_offset=3). The partition key indexes the release week; the connector
# widens its pull >=5 weeks back to re-carry EIA's inline revisions (bitemporal_merge).
EIA_GAS_WEEKLY = dg.WeeklyPartitionsDefinition(start_date="2020-01-02", day_offset=4)
EIA_PETROLEUM_WEEKLY = dg.WeeklyPartitionsDefinition(start_date="2020-01-01", day_offset=3)

# FRED daily benchmark spot prices. The partition key indexes the valid_time day; for the
# degenerate stream it drives the as_of cadence. Each run pulls a short lookback window so
# the append-with-dedup write re-carries FRED's few-business-day publication lag.
FRED_DAILY = dg.DailyPartitionsDefinition(start_date="2020-01-01")

# EIA-930 hourly grid monitor. Daily partition over a ~3-year backfill window; each run
# pulls a short lookback so the degenerate append-with-dedup re-carries EIA's inline
# revisions. The hourly schedule re-materializes the latest (today's) partition.
EIA930_DAILY = dg.DailyPartitionsDefinition(start_date="2023-06-01")

# ERCOT nodal daily partition (forward-fill; no nodal backfill this slice).
ERCOT_DAILY = dg.DailyPartitionsDefinition(start_date="2026-06-01")
