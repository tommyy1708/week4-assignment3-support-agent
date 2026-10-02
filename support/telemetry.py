"""Tracing: export every span to the separate Phoenix process (O-1), set as the global provider
before any agent is built, with OpenInference instrumentation on model calls (O-3).

Model calls go through LiteLLM to OpenRouter, so they are instrumented with the LiteLLM
instrumentor instead of SPEC's google-genai one; ADK still emits invoke_agent / call_llm /
execute_tool spans itself."""

import os

import httpx
from openinference.instrumentation.litellm import LiteLLMInstrumentor
from openinference.semconv.resource import ResourceAttributes
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

PHOENIX_URL = os.getenv("PHOENIX_URL", "http://127.0.0.1:6006")
PROJECT = "support-desk"

_provider: TracerProvider | None = None
_project_id: str | None = None


def setup_tracing() -> None:
    """Call once per process, before building agents. Fails loudly if Phoenix is down."""
    global _provider, _project_id
    if _provider is not None:
        return
    _project_id = _ensure_project()
    _provider = TracerProvider(resource=Resource.create({ResourceAttributes.PROJECT_NAME: PROJECT}))
    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{PHOENIX_URL}/v1/traces")))
    trace.set_tracer_provider(_provider)
    LiteLLMInstrumentor().instrument(tracer_provider=_provider)


def trace_url(trace_id: str) -> str:
    return f"{PHOENIX_URL}/projects/{_project_id}/traces/{trace_id}"


def flush() -> None:
    if _provider is not None:
        _provider.force_flush()


def _ensure_project() -> str:
    """Return the Phoenix project id, creating the project on first run."""
    try:
        projects = httpx.get(f"{PHOENIX_URL}/v1/projects", timeout=5).raise_for_status().json()["data"]
        for project in projects:
            if project["name"] == PROJECT:
                return project["id"]
        created = httpx.post(f"{PHOENIX_URL}/v1/projects", json={"name": PROJECT}, timeout=5)
        return created.raise_for_status().json()["data"]["id"]
    except httpx.HTTPError as e:
        raise RuntimeError(f"Phoenix is not reachable at {PHOENIX_URL} ({e}). Run ./run.sh start.") from e
