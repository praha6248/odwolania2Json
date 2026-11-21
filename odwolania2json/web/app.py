"""FastAPI web interface: upload PDFs, preview them side by side with extracted JSON and its provenance."""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import load_settings
from ..cases import case_values, group_cases
from ..pipeline import DocumentResult, Processor

STATIC = Path(__file__).resolve().parent / "static"


class Store:
    """In-memory registry of uploaded documents backed by a temporary directory."""

    def __init__(self) -> None:
        """Create an empty store with its own scratch directory."""
        self.root = Path(tempfile.mkdtemp(prefix="o2j-"))
        self.items: dict[str, dict[str, Any]] = {}

    def add(self, filename: str, content: bytes) -> tuple[str, Path]:
        """Persist an uploaded file and return its id and path."""
        doc_id = uuid.uuid4().hex[:12]
        folder = self.root / doc_id
        folder.mkdir(parents=True)
        path = folder / Path(filename).name
        path.write_bytes(content)
        self.items[doc_id] = {"id": doc_id, "filename": path.name, "path": path}
        return doc_id, path

    def get(self, doc_id: str) -> dict[str, Any]:
        """Return a stored item or raise 404."""
        if doc_id not in self.items:
            raise HTTPException(status_code=404, detail="Unknown document")
        return self.items[doc_id]

    def remove(self, doc_id: str) -> None:
        """Delete a stored item and its files."""
        item = self.items.pop(doc_id, None)
        if item:
            shutil.rmtree(item["path"].parent, ignore_errors=True)


def serialize(doc_id: str, result: DocumentResult, settings_labels: dict[str, str], case_spec: dict[str, str] | None = None) -> dict[str, Any]:
    """Build the API representation of a processed document."""
    values = {f["field"]: f["value"] for f in result.fields}
    return {
        "id": doc_id,
        "filename": result.path.name,
        "doc_type": result.doc_type,
        "doc_label": settings_labels.get(result.doc_type or "", "Spoza puli"),
        "data": result.data,
        "fields": result.fields,
        "case_values": case_values(case_spec or {}, values),
        "classification": result.trace()["classification"],
        "seconds": round(result.seconds, 3),
        "error": result.error,
        "message": result.message,
        "text": result.text,
        "ocr": result.ocr,
    }


def create_app(config_dir: str | Path | None = None) -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(title="Odwołania2JSON", version=__version__)
    state: dict[str, Any] = {"settings": load_settings(config_dir)}
    state["processor"] = Processor(state["settings"])
    store = Store()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def labels() -> dict[str, str]:
        """Map document type names to human readable labels."""
        return {t.name: t.label for t in state["settings"].document_types}

    def remember(doc_id: str, result: DocumentResult) -> None:
        """Store the serialized result and the extraction context needed for manual corrections."""
        doc_type = state["settings"].get_type(result.doc_type) if result.doc_type else None
        store.items[doc_id]["result"] = serialize(doc_id, result, labels(), doc_type.case if doc_type else None)
        store.items[doc_id]["context"] = getattr(state["processor"], "last_context", None) if doc_type else None

    def llm_client():
        """Return an LLM client for the current settings or fail with a clear message."""
        from ..llm import LLMClient

        if not state["settings"].llm.get("base_url"):
            raise HTTPException(status_code=400, detail="Skonfiguruj model językowy w Ustawieniach.")
        return LLMClient(state["settings"].llm)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the single page application."""
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/info")
    def info() -> dict[str, Any]:
        """Return version, configured document types and LLM status."""
        settings = state["settings"]
        return {
            "version": __version__,
            "llm": bool(state["processor"].llm),
            "llm_model": settings.llm.get("model") if state["processor"].llm else None,
            "types": [
                {"name": t.name, "label": t.label, "fields": list(t.fields), "optional": [n for n, spec in t.fields.items() if (spec or {}).get("optional")], "source": t.source.name if t.source else None}
                for t in settings.document_types
            ],
        }

    from ..updater import Updater

    updater = Updater()

    @app.get("/api/update")
    def update() -> dict[str, Any]:
        """Report whether a newer release exists and how many changed files a patch update would download."""
        try:
            return updater.check()
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    @app.post("/api/update/start")
    def update_start() -> dict[str, Any]:
        """Start downloading only the changed files of the new release."""
        return updater.start()

    @app.get("/api/update/status")
    def update_status() -> dict[str, Any]:
        """Progress of the running update."""
        return {k: v for k, v in updater.status().items() if k in {"stage", "done", "total", "error"}}

    @app.post("/api/update/restart")
    def update_restart() -> dict[str, Any]:
        """Apply the downloaded patch and restart the application."""
        return {k: v for k, v in updater.restart().items() if k in {"stage", "error"}}

    def llm_view() -> dict[str, Any]:
        """Public view of the LLM settings without the API key."""
        cfg = state["settings"].llm
        return {
            "enabled": bool(state["processor"].llm),
            "mode": cfg.get("mode", "fast"),
            "base_url": cfg.get("base_url", ""),
            "model": cfg.get("model", ""),
            "has_key": bool(cfg.get("api_key")),
        }

    @app.get("/api/llm")
    def get_llm() -> dict[str, Any]:
        """Return the current LLM configuration."""
        return llm_view()

    @app.put("/api/llm")
    def set_llm(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Change LLM settings at runtime; with persist=true also store them in .env."""
        cfg = state["settings"].llm
        for key in ("base_url", "model"):
            if isinstance(body.get(key), str) and body[key].strip():
                cfg[key] = body[key].strip()
        if isinstance(body.get("api_key"), str) and body["api_key"]:
            cfg["api_key"] = body["api_key"]
        cfg["enabled"] = bool(body.get("enabled", cfg.get("enabled", False)))
        if body.get("mode") in ("fast", "accurate"):
            cfg["mode"] = body["mode"]
        state["processor"] = Processor(state["settings"])
        if body.get("persist"):
            from ..config import save_env

            updates = {"O2J_LLM_ENABLED": str(cfg["enabled"]).lower(), "O2J_LLM_URL": cfg.get("base_url", ""), "O2J_LLM_MODEL": cfg.get("model", ""), "O2J_LLM_MODE": cfg.get("mode", "fast")}
            if body.get("api_key"):
                updates["O2J_LLM_API_KEY"] = body["api_key"]
            save_env(updates)
        return llm_view()

    @app.post("/api/llm/check")
    def check_llm() -> dict[str, Any]:
        """Test the configured endpoint: list models and run a tiny extraction."""
        from ..llm import LLMClient

        client = LLMClient(state["settings"].llm)
        try:
            return {"ok": True, "models": client.models(), **client.check()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/reload")
    def reload() -> dict[str, Any]:
        """Reload YAML configuration without restarting the server."""
        state["settings"] = load_settings(config_dir)
        state["processor"] = Processor(state["settings"])
        return info()

    def sample(doc_id: str) -> dict[str, Any]:
        """Return a processed document used as a sample in the type wizard."""
        result = store.get(doc_id).get("result")
        if not result or not result.get("text"):
            raise HTTPException(status_code=400, detail="Dokument nie ma tekstu.")
        return result

    @app.post("/api/wizard/suggest")
    def wizard_suggest(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Suggest a field rule for a value selected in the sample text."""
        from ..wizard import suggest_field

        try:
            return suggest_field(sample(body["doc_id"])["text"], int(body["start"]), int(body["end"]))
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/wizard/keywords/{doc_id}")
    def wizard_keywords(doc_id: str) -> dict[str, Any]:
        """Suggest classification keywords from the sample text."""
        from ..wizard import suggest_keywords

        return suggest_keywords(sample(doc_id)["text"])

    @app.post("/api/wizard/preview")
    def wizard_preview(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Run a draft type on the sample and score it against the other uploaded documents."""
        from ..wizard import preview

        doc = sample(body["doc_id"])
        others = [i["result"] for i in store.items.values() if "result" in i and i["id"] != doc["id"]]
        try:
            return preview(body.get("draft") or {}, doc["text"], doc["filename"], others, state["settings"].min_classification_score)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Błąd w definicji typu: {exc}") from exc

    @app.post("/api/types")
    def save_type(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Save a draft type as YAML in the configuration directory and reload the configuration."""
        from ..config import DEFAULT_CONFIG_DIR
        from ..wizard import save

        target = state["settings"].config_dir or DEFAULT_CONFIG_DIR
        try:
            path = save(body.get("draft") or {}, Path(target), bool(body.get("overwrite")))
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        reload()
        return {"path": str(path), "name": path.stem, **info()}

    @app.post("/api/documents")
    async def upload(files: list[UploadFile] = File(...)) -> list[dict[str, Any]]:
        """Accept one or more PDFs, process them and return extraction results."""
        out = []
        for upload_file in files:
            if not (upload_file.filename or "").lower().endswith(".pdf"):
                continue
            doc_id, path = store.add(upload_file.filename or "document.pdf", await upload_file.read())
            result = state["processor"].process_pdf(path)
            remember(doc_id, result)
            out.append(store.items[doc_id]["result"])
        return out

    @app.get("/api/documents")
    def list_documents() -> list[dict[str, Any]]:
        """List processed documents without their full text."""
        return [{k: v for k, v in i["result"].items() if k != "text"} for i in store.items.values() if "result" in i]

    @app.get("/api/documents/{doc_id}")
    def get_document(doc_id: str) -> dict[str, Any]:
        """Return full result of one document."""
        return store.get(doc_id)["result"]

    @app.post("/api/documents/{doc_id}/reprocess")
    def reprocess(doc_id: str, doc_type: str | None = None, llm: bool | None = None) -> dict[str, Any]:
        """Run extraction again, optionally forcing a document type and LLM refinement on or off."""
        item = store.get(doc_id)
        if doc_type and not state["settings"].get_type(doc_type):
            raise HTTPException(status_code=400, detail="Unknown document type")
        if not doc_type and item.get("result", {}).get("doc_type"):
            doc_type = item["result"]["doc_type"]
        try:
            result = state["processor"].process_pdf(item["path"], doc_type, llm)
            remember(doc_id, result)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM: {exc}") from exc
        return item["result"]

    @app.put("/api/documents/{doc_id}/fields/{name}")
    def set_field(doc_id: str, name: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Manually correct (or confirm as empty) one field and re-render the output JSON."""
        from ..engine import rerender

        item = store.get(doc_id)
        ctx = item.get("context")
        doc_type = state["settings"].get_type(item["result"].get("doc_type") or "")
        if ctx is None or doc_type is None or name not in doc_type.fields:
            raise HTTPException(status_code=400, detail="To pole nie może być edytowane.")
        data = rerender(doc_type, ctx, {name: body.get("value")})
        fields = [r.to_dict() for r in ctx.results.values()]
        item["result"].update({"data": data, "fields": fields, "case_values": case_values(doc_type.case, {f["field"]: f["value"] for f in fields})})
        return item["result"]

    @app.post("/api/documents/{doc_id}/summary")
    def summary(doc_id: str) -> dict[str, Any]:
        """Summarize one document with the configured LLM (accurate mode feature)."""
        from ..assistant import summarize

        result = store.get(doc_id)["result"]
        try:
            return summarize(llm_client(), result)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM: {exc}") from exc

    @app.post("/api/ask")
    def ask_documents(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Answer a question about the uploaded documents with retrieval over their text (RAG)."""
        from ..assistant import ask

        question = str(body.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="Wpisz pytanie.")
        ids = body.get("doc_ids") or list(store.items)
        documents = [store.items[i]["result"] for i in ids if i in store.items and "result" in store.items[i]]
        try:
            return ask(llm_client(), question, documents)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM: {exc}") from exc

    @app.get("/api/cases")
    def cases() -> list[dict[str, Any]]:
        """Group uploaded documents into cases by procurement reference and check party consistency."""
        return group_cases([i["result"] for i in store.items.values() if "result" in i], state["settings"].formal_checks)

    @app.delete("/api/documents/{doc_id}")
    def delete(doc_id: str) -> dict[str, str]:
        """Forget a document."""
        store.remove(doc_id)
        return {"status": "deleted"}

    @app.get("/api/documents/{doc_id}/pdf")
    def pdf(doc_id: str) -> FileResponse:
        """Stream the original PDF for in-browser preview."""
        item = store.get(doc_id)
        return FileResponse(item["path"], media_type="application/pdf", headers={"Content-Disposition": "inline"})

    @app.get("/api/documents/{doc_id}/pages")
    def page_count(doc_id: str) -> dict[str, int]:
        """Number of pages of the stored PDF."""
        import pypdfium2 as pdfium

        from ..ocr import PDFIUM_LOCK

        item = store.get(doc_id)
        if "pages" not in item:
            with PDFIUM_LOCK:
                pdf = pdfium.PdfDocument(str(item["path"]))
                item["pages"] = len(pdf)
                pdf.close()
        return {"pages": item["pages"]}

    @app.get("/api/documents/{doc_id}/pages/{number}.png")
    def page_image(doc_id: str, number: int) -> Response:
        """Render one PDF page as PNG so the preview works in every browser and the desktop window."""
        import io

        import pypdfium2 as pdfium

        from ..ocr import PDFIUM_LOCK

        item = store.get(doc_id)
        cache = item.setdefault("page_png", {})
        if number not in cache:
            with PDFIUM_LOCK:
                pdf = pdfium.PdfDocument(str(item["path"]))
                count = len(pdf)
                image = pdf[number - 1].render(scale=1.6).to_pil() if 1 <= number <= count else None
                pdf.close()
            if image is None:
                raise HTTPException(status_code=404, detail="Brak strony")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            cache[number] = buffer.getvalue()
        return Response(cache[number], media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/documents/{doc_id}/locate/{name}")
    def locate_field(doc_id: str, name: str) -> dict[str, Any]:
        """Boxes on the PDF pages where a field value was found, for highlighting in the preview."""
        from ..locate import locate

        item = store.get(doc_id)
        result = item.get("result") or {}
        field = next((f for f in result.get("fields") or [] if f["field"] == name), None)
        if field is None:
            raise HTTPException(status_code=404, detail="Nieznane pole")
        if result.get("ocr"):
            return {"field": name, "boxes": [], "reason": "Skan bez warstwy tekstowej: źródło zaznaczamy w zakładce Tekst."}
        return {"field": name, "boxes": locate(item["path"], field, result.get("text") or "")}

    @app.get("/api/documents/{doc_id}/json")
    def download(doc_id: str) -> Response:
        """Download the output JSON named after the source PDF."""
        result = store.get(doc_id)["result"]
        name = Path(result["filename"]).with_suffix(".json").name
        return Response(
            json.dumps(result["data"] if result["data"] is not None else {}, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    return app
