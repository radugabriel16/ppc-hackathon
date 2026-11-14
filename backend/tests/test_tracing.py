import json
import logging
import os
import subprocess
import sys

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from app.core.logging import JsonFormatter


def test_tracing_unset_is_noop():
    env = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    subprocess.run([sys.executable, "-c", """
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from app.core.tracing import configure_tracing
app = FastAPI()
before = trace.get_tracer_provider()
assert configure_tracing(app, "worker") is None
assert trace.get_tracer_provider() is before
assert not app.user_middleware
assert not HTTPXClientInstrumentor().is_instrumented_by_opentelemetry
assert not trace.get_tracer("test").start_span("disabled").get_span_context().is_valid
"""], env=env, check=True, timeout=30)


def test_json_logs_contain_active_trace_id():
    provider = TracerProvider()
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", (), None)
    formatter = JsonFormatter()
    assert json.loads(formatter.format(record))["trace_id"] is None
    with provider.get_tracer("test").start_as_current_span("run") as span:
        assert json.loads(formatter.format(record))["trace_id"] == format(
            span.get_span_context().trace_id, "032x"
        )
    provider.shutdown()


def test_otlp_export_and_instrumentors_enabled():
    env = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    subprocess.run([sys.executable, "-c", """
import os
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, HTTPServer
from fastapi import FastAPI
from fastapi.testclient import TestClient
import sqlalchemy
from sqlalchemy import text
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from app.core.tracing import configure_tracing
payloads = []
class Collector(BaseHTTPRequestHandler):
    def do_POST(self):
        assert self.path == "/v1/traces"
        payloads.append(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args):
        pass
server = HTTPServer(("127.0.0.1", 0), Collector)
thread = threading.Thread(target=server.serve_forever)
thread.start()
try:
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"http://127.0.0.1:{server.server_port}"
    os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
    os.environ["OTEL_SERVICE_NAME"] = "filegrid-test"
    os.environ["OTEL_RESOURCE_ATTRIBUTES"] = "service.namespace=grid-test,custom.attribute=present"
    app = FastAPI()
    @app.get("/probe")
    def probe():
        return {"ok": True}
    provider = configure_tracing(app, "files")
    with TestClient(app) as client:
        assert client.get("/probe").status_code == 200
    from app.core import db
    db.get_settings = lambda: SimpleNamespace(catalog_db_dsn="sqlite://")
    engine = db.get_catalog_engine()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    assert AsyncPGInstrumentor().is_instrumented_by_opentelemetry
    assert HTTPXClientInstrumentor().is_instrumented_by_opentelemetry
    assert provider.force_flush(timeout_millis=10000)
    requests = [ExportTraceServiceRequest.FromString(body) for body in payloads]
    spans = [span for request in requests for resource in request.resource_spans
             for scope in resource.scope_spans for span in scope.spans]
    assert any("probe" in span.name for span in spans)
    assert any(span.name == "SELECT" for span in spans), [span.name for span in spans]
    assert provider.resource.attributes["service.name"] == "filegrid-test"
    assert provider.resource.attributes["service.namespace"] == "grid-test"
    assert provider.resource.attributes["custom.attribute"] == "present"
    provider.shutdown()
finally:
    server.shutdown()
    server.server_close()
    thread.join()
"""], env=env, check=True, timeout=30)
