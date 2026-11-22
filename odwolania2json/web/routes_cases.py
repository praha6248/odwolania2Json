"""Routes working across documents: cases with formal checks, export, search, summaries and the LLM assistant."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from ..cases import group_cases
from .state import AppState


def router(app: AppState) -> APIRouter:
    """Build the cross-document routes bound to the application state."""
    api = APIRouter(prefix="/api")
    store = app.store

    def llm_call(func: Any, *args: Any) -> Any:
        """Run an LLM-backed function and report model failures as 502."""
        try:
            return func(app.llm_client(), *args)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM: {exc}") from exc

    @api.get("/cases")
    def cases() -> list[dict[str, Any]]:
        """Group uploaded documents into cases by procurement reference, check party consistency and formal rules."""
        return group_cases(store.processed(), app.settings.formal_checks)

    @api.get("/export.xlsx")
    def export_xlsx() -> Response:
        """Excel workbook with a summary, one sheet per type and the formal checks."""
        from ..export import to_xlsx

        docs = store.processed()
        data = to_xlsx(docs, group_cases(docs, app.settings.formal_checks), app.labels())
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="odwolania2json.xlsx"'})

    @api.get("/export.csv")
    def export_csv() -> Response:
        """One CSV row per document with every output field."""
        from ..export import to_csv

        return Response(to_csv(store.processed()), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="odwolania2json.csv"'})

    @api.post("/search")
    def search_documents(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Find the best matching fragments of the uploaded documents without a language model (BM25)."""
        from ..assistant import search

        query = str(body.get("question") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Wpisz pytanie lub frazę.")
        return {"hits": search(query, store.processed())}

    @api.post("/answer")
    def answer_without_model(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Answer a typical question from the extracted JSON (config/assistant.yaml) and add matching fragments."""
        from pathlib import Path

        from ..assistant import search
        from ..config import DEFAULT_CONFIG_DIR
        from ..qa import answer, load_intents

        question = str(body.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="Wpisz pytanie lub frazę.")
        documents = store.processed()
        intents = load_intents(Path(app.settings.config_dir or DEFAULT_CONFIG_DIR))
        return {**answer(question, documents, intents), "hits": search(question, documents)}

    @api.post("/ask")
    def ask_documents(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Answer a question about the uploaded documents with retrieval over their text (RAG)."""
        from ..assistant import ask

        question = str(body.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="Wpisz pytanie.")
        ids = body.get("doc_ids") or list(store.items)
        documents = [store.items[i]["result"] for i in ids if i in store.items and "result" in store.items[i]]
        return llm_call(ask, question, documents)

    @api.post("/documents/{doc_id}/summary")
    def summary(doc_id: str) -> dict[str, Any]:
        """Summarize one document with the configured LLM (accurate mode feature)."""
        from ..assistant import summarize

        return llm_call(summarize, store.get(doc_id)["result"])

    return api
