"""
Custom Prometheus metrics for CricEdge.
"""
from prometheus_client import Counter, Gauge, Histogram

scraper_runs_total = Counter(
    "cricedge_scraper_runs_total",
    "Total scraper executions",
    ["scraper_name", "status"],  # status: success / failed
)

xi_confirmations_total = Counter(
    "cricedge_xi_confirmations_total",
    "Total playing XI confirmations detected",
)

active_subscribers = Gauge(
    "cricedge_active_subscribers",
    "Current active paid subscribers",
    ["tier"],  # pro / elite
)

ownership_prediction_duration = Histogram(
    "cricedge_ownership_prediction_seconds",
    "Time taken to compute ownership predictions",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

cricbuzz_api_calls_total = Counter(
    "cricedge_cricbuzz_api_calls_total",
    "Total Cricbuzz API calls made (cache misses only)",
    ["endpoint"],
)
