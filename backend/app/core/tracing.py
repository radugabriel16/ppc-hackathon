"""Opt-in OTLP tracing; standard OTEL_* variables are read by the SDK/exporter."""
import os
from threading import Lock

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_lock = Lock()
_provider: TracerProvider | None = None


def configure_tracing(app: FastAPI, role: str) -> TracerProvider | None:
    global _provider
    if (
        not (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"))
        or os.getenv("OTEL_SDK_DISABLED", "").lower() == "true"
        or os.getenv("OTEL_TRACES_EXPORTER", "").lower() == "none"
    ):
        return None
    with _lock:
        if _provider is None:
            protocol = os.getenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL") or os.getenv(
                "OTEL_EXPORTER_OTLP_PROTOCOL", "grpc"
            )
            if protocol == "http/protobuf":
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            elif protocol == "grpc":
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            else:
                raise ValueError(f"Unsupported OTLP trace protocol: {protocol}")
            resource = Resource.create({
                "service.name": f"filegrid-{role}",
                "service.namespace": "filegrid",
            }).merge(OTELResourceDetector().detect())
            provider = TracerProvider(resource=resource)
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(provider)
            SQLAlchemyInstrumentor().instrument(tracer_provider=provider)
            AsyncPGInstrumentor().instrument(tracer_provider=provider)
            HTTPXClientInstrumentor().instrument(tracer_provider=provider)
            _provider = provider
        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=_provider,
            excluded_urls="health/live,health/ready,metrics,customers/lookup",
        )
        return _provider
