"""Central registry of all Prometheus metrics named in PHASE1.md section 4.

Defining them all here (even before every producer exists) means later steps
only need to call `.labels(...).observe()/.inc()` without touching wiring.
"""
from prometheus_client import Counter, Gauge, Histogram

REQUEST_DURATION_SECONDS = Histogram(
    "filegrid_request_duration_seconds",
    "HTTP request duration in seconds",
    ["route", "method", "status_class"],
)

STORAGE_OPERATION_DURATION_SECONDS = Histogram(
    "filegrid_storage_operation_duration_seconds",
    "Storage adapter operation duration in seconds",
    ["category", "storage", "operation", "outcome"],
)

STORAGE_BYTES_TOTAL = Counter(
    "filegrid_storage_bytes_total",
    "Bytes written to / read from a storage backend",
    ["category", "storage", "operation"],
)

REQUESTS_REJECTED_TOTAL = Counter(
    "filegrid_requests_rejected_total",
    "Requests rejected by a bulkhead (503)",
    ["category", "reason"],
)

METER_INGEST_TOTAL = Counter(
    "filegrid_meter_ingest_total",
    "Meter reading ingest outcomes",
    ["result"],
)

INTEGRITY_FAILURES_TOTAL = Counter(
    "filegrid_integrity_failures_total",
    "SHA-256 mismatches detected on download/verify",
    ["category", "storage"],
)

CIRCUIT_STATE = Gauge(
    "filegrid_circuit_state",
    "Circuit breaker state per storage (0=closed, 1=half-open, 2=open)",
    ["storage"],
)

STORAGE_FALLBACK_TOTAL = Counter(
    "filegrid_storage_fallback_total",
    "Times a category fell back from its primary storage",
    ["category", "from", "to"],
)

FILE_TIME_TO_AVAILABLE_SECONDS = Histogram(
    "filegrid_file_time_to_available_seconds",
    "Time from upload start to the file becoming READY",
    ["category"],
)

UPLOAD_SESSIONS_ACTIVE = Gauge(
    "filegrid_upload_sessions_active",
    "Currently active resumable upload sessions",
)

UPLOAD_SESSIONS_STALLED = Gauge(
    "filegrid_upload_sessions_stalled",
    "Resumable upload sessions with no progress past their expected cadence",
)
