"""FastAPI web interface: upload PDFs, preview them side by side with extracted JSON and its provenance.

The routes live in routes_system (info, LLM, updates), routes_documents (per-document actions), routes_cases (cases,
export, search, assistant) and routes_types (type wizard); they share one AppState.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from . import routes_cases, routes_documents, routes_system, routes_types
from .state import AppState, Store, serialize

STATIC = Path(__file__).resolve().parent / "static"

__all__ = ["create_app", "AppState", "Store", "serialize"]


def create_app(config_dir: str | Path | None = None) -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(title="Odwołania2JSON", version=__version__)
    state = AppState(config_dir)
    app.state.o2j = state
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the single page application."""
        return (STATIC / "index.html").read_text(encoding="utf-8")

    for module in (routes_system, routes_cases, routes_types, routes_documents):
        app.include_router(module.router(state))
    return app
