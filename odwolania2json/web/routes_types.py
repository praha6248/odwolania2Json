"""Routes of the document type wizard: rule suggestions, live preview and saving a new type."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from .state import AppState


def router(app: AppState) -> APIRouter:
    """Build the wizard routes bound to the application state."""
    api = APIRouter(prefix="/api")
    store = app.store

    def sample(doc_id: str) -> dict[str, Any]:
        """Return a processed document used as a sample in the type wizard."""
        result = store.get(doc_id).get("result")
        if not result or not result.get("text"):
            raise HTTPException(status_code=400, detail="Dokument nie ma tekstu.")
        return result

    @api.post("/wizard/suggest")
    def wizard_suggest(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Suggest a field rule for a value selected in the sample text."""
        from ..wizard import suggest_field

        try:
            return suggest_field(sample(body["doc_id"])["text"], int(body["start"]), int(body["end"]))
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.get("/wizard/keywords/{doc_id}")
    def wizard_keywords(doc_id: str) -> dict[str, Any]:
        """Suggest classification keywords from the sample text."""
        from ..wizard import suggest_keywords

        return suggest_keywords(sample(doc_id)["text"])

    @api.post("/wizard/preview")
    def wizard_preview(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Run a draft type on the sample and score it against the other uploaded documents."""
        from ..wizard import preview

        doc = sample(body["doc_id"])
        others = [r for r in store.processed() if r["id"] != doc["id"]]
        try:
            return preview(body.get("draft") or {}, doc["text"], doc["filename"], others, app.settings.min_classification_score)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Błąd w definicji typu: {exc}") from exc

    @api.post("/types")
    def save_type(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Save a draft type as YAML in the configuration directory and reload the configuration."""
        from ..config import DEFAULT_CONFIG_DIR
        from ..wizard import save

        target = app.settings.config_dir or DEFAULT_CONFIG_DIR
        try:
            path = save(body.get("draft") or {}, Path(target), bool(body.get("overwrite")))
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app.reload()
        return {"path": str(path), "name": path.stem, **app.info()}

    return api
