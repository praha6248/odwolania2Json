"""FastAPI web interface: upload PDFs, preview them side by side with extracted JSON and its provenance."""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import load_settings
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


def serialize(doc_id: str, result: DocumentResult, settings_labels: dict[str, str]) -> dict[str, Any]:
    """Build the API representation of a processed document."""
    return {
        "id": doc_id,
        "filename": result.path.name,
        "doc_type": result.doc_type,
        "doc_label": settings_labels.get(result.doc_type or "", "Nierozpoznany"),
        "data": result.data,
        "fields": result.fields,
        "classification": result.trace()["classification"],
        "seconds": round(result.seconds, 3),
        "error": result.error,
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
                {"name": t.name, "label": t.label, "fields": list(t.fields), "source": t.source.name if t.source else None}
                for t in settings.document_types
            ],
        }

    @app.get("/api/update")
    def update() -> dict[str, Any]:
        """Report whether a newer release is available on GitHub."""
        from ..update_check import check_for_update

        return check_for_update()

    @app.post("/api/reload")
    def reload() -> dict[str, Any]:
        """Reload YAML configuration without restarting the server."""
        state["settings"] = load_settings(config_dir)
        state["processor"] = Processor(state["settings"])
        return info()

    @app.post("/api/documents")
    async def upload(files: list[UploadFile] = File(...)) -> list[dict[str, Any]]:
        """Accept one or more PDFs, process them and return extraction results."""
        out = []
        for upload_file in files:
            if not (upload_file.filename or "").lower().endswith(".pdf"):
                continue
            doc_id, path = store.add(upload_file.filename or "document.pdf", await upload_file.read())
            result = state["processor"].process_pdf(path)
            store.items[doc_id]["result"] = serialize(doc_id, result, labels())
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
    def reprocess(doc_id: str, doc_type: str | None = None) -> dict[str, Any]:
        """Run extraction again, optionally forcing a document type."""
        item = store.get(doc_id)
        if doc_type and not state["settings"].get_type(doc_type):
            raise HTTPException(status_code=400, detail="Unknown document type")
        result = state["processor"].process_pdf(item["path"], doc_type)
        item["result"] = serialize(doc_id, result, labels())
        return item["result"]

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

    @app.get("/api/documents/{doc_id}/json")
    def download(doc_id: str) -> Response:
        """Download the output JSON named after the source PDF."""
        result = store.get(doc_id)["result"]
        if result["data"] is None:
            return JSONResponse({"detail": "Document was not recognized"}, status_code=422)
        name = Path(result["filename"]).with_suffix(".json").name
        return Response(
            json.dumps(result["data"], ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    return app
