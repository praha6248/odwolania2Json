"""Routes for uploaded documents: processing, manual corrections, page previews, source boxes, redaction and JSON."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path
from threading import Lock, Timer
from typing import Any

from fastapi import APIRouter, Body, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from ..cases import case_values, key
from .state import AppState


def router(app: AppState) -> APIRouter:
    """Build the document routes bound to the application state."""
    api = APIRouter(prefix="/api/documents")
    store = app.store

    processing = Lock()

    @api.post("")
    def upload(files: list[UploadFile] = File(...), idempotency_key: str | None = Header(None)) -> list[dict[str, Any]]:
        """Run extraction in a worker and replay single-file retries within this session."""
        if idempotency_key and len(files) != 1:
            raise HTTPException(400, "Klucz ponowienia dotyczy jednego pliku.")
        out = []
        for upload_file in files:
            filename = upload_file.filename or ""
            if not filename.lower().endswith(".pdf"):
                continue
            content = upload_file.file.read()
            digest = hashlib.sha256(content).digest() if idempotency_key else None
            with processing:
                if idempotency_key:
                    previous = next((item for item in list(store.items.values())
                                     if item.get("upload_key") == idempotency_key), None)
                    if previous:
                        if previous["digest"] != digest or previous["filename"] != Path(filename).name:
                            raise HTTPException(409, "Klucz ponowienia został już użyty dla innego pliku.")
                        out.append(previous["result"])
                        continue
                doc_id, path = store.add(filename, content)
                processor = app.processor
                try:
                    app.remember(doc_id, processor.process_pdf(path), processor)
                except Exception:
                    store.remove(doc_id)
                    raise
                item = store.items[doc_id]
                item.update(upload_key=idempotency_key, digest=digest)
                out.append(item["result"])
        return out

    @api.get("")
    def list_documents() -> list[dict[str, Any]]:
        """List processed documents without their full text."""
        return [{k: v for k, v in result.items() if k != "text"} for result in store.processed()]

    @api.get("/{doc_id}")
    def get_document(doc_id: str) -> dict[str, Any]:
        """Return full result of one document."""
        return store.get(doc_id)["result"]

    @api.delete("/{doc_id}")
    def delete(doc_id: str) -> dict[str, str]:
        """Forget a document."""
        with processing:
            store.remove(doc_id)
        return {"status": "deleted"}

    # Keep recoverable deletions outside the active store so exports and case checks
    # immediately reflect them. A closed client cannot leave a deleted PDF behind.
    trash: dict[str, dict[str, Any]] = {}

    def expire(doc_id: str, item: dict[str, Any]) -> None:
        with processing:
            if trash.get(doc_id) is item:
                trash.pop(doc_id)
                shutil.rmtree(item["path"].parent, ignore_errors=True)

    @api.post("/{doc_id}/trash")
    def trash_document(doc_id: str) -> dict[str, int]:
        with processing:
            if doc_id not in trash:
                store.get(doc_id)
                item = dict(store.items.pop(doc_id))
                trash[doc_id] = item
                timer = Timer(30, expire, args=(doc_id, item))
                timer.daemon = True
                timer.start()
        return {"undo_seconds": 20}

    @api.post("/{doc_id}/restore")
    def restore_document(doc_id: str) -> dict[str, Any]:
        with processing:
            if doc_id in trash:
                store.items[doc_id] = trash.pop(doc_id)
            return store.get(doc_id)["result"]

    @api.post("/{doc_id}/reprocess")
    def reprocess(doc_id: str, doc_type: str | None = None, llm: bool | None = None) -> dict[str, Any]:
        """Run extraction again, optionally forcing a document type and LLM refinement on or off."""
        item = store.get(doc_id)
        if doc_type and not app.settings.get_type(doc_type):
            raise HTTPException(status_code=400, detail="Unknown document type")
        if not doc_type and item.get("result", {}).get("doc_type"):
            doc_type = item["result"]["doc_type"]
        try:
            with processing:
                processor = app.processor
                app.remember(doc_id, processor.process_pdf(item["path"], doc_type, llm), processor)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM: {exc}") from exc
        return item["result"]

    @api.put("/{doc_id}/fields/{name}")
    def set_field(doc_id: str, name: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Manually correct (or confirm as empty) one field and re-render the output JSON."""
        from ..engine import rerender

        item = store.get(doc_id)
        ctx = item.get("context")
        doc_type = app.settings.get_type(item["result"].get("doc_type") or "")
        if ctx is None or doc_type is None or name not in doc_type.fields:
            raise HTTPException(status_code=400, detail="To pole nie może być edytowane.")
        data = rerender(doc_type, ctx, {name: body.get("value")})
        fields = [r.to_dict() for r in ctx.results.values()]
        item["result"].update({"data": data, "fields": fields, "case_values": case_values(doc_type.case, {f["field"]: f["value"] for f in fields})})
        return item["result"]

    @api.get("/{doc_id}/pdf")
    def pdf(doc_id: str) -> FileResponse:
        """Stream the original PDF for in-browser preview."""
        return FileResponse(store.get(doc_id)["path"], media_type="application/pdf", headers={"Content-Disposition": "inline"})

    @api.get("/{doc_id}/pages")
    def page_count(doc_id: str) -> dict[str, Any]:
        """Number of pages of the stored PDF."""
        import pypdfium2 as pdfium

        from ..ocr import PDFIUM_LOCK

        item = store.get(doc_id)
        if "pages" not in item:
            with PDFIUM_LOCK:
                document = pdfium.PdfDocument(str(item["path"]))
                try:
                    item["page_sizes"] = [document.get_page_size(i) for i in range(len(document))]
                    item["pages"] = len(document)
                finally:
                    document.close()
        return {"pages": item["pages"], "sizes": item["page_sizes"]}

    @api.get("/{doc_id}/pages/{number}.png")
    def page_image(doc_id: str, number: int) -> Response:
        """Render one PDF page as PNG so the preview works in every browser and the desktop window."""
        import pypdfium2 as pdfium

        from ..ocr import PDFIUM_LOCK

        item = store.get(doc_id)
        cache = item.setdefault("page_png", {})
        if number not in cache:
            with PDFIUM_LOCK:
                document = pdfium.PdfDocument(str(item["path"]))
                count = len(document)
                image = document[number - 1].render(scale=1.6).to_pil() if 1 <= number <= count else None
                document.close()
            if image is None:
                raise HTTPException(status_code=404, detail="Brak strony")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            cache[number] = buffer.getvalue()
        return Response(cache[number], media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    @api.get("/{doc_id}/locate/{name}")
    def locate_field(doc_id: str, name: str) -> dict[str, Any]:
        """Boxes on the PDF pages where a field value was found, for highlighting in the preview."""
        from ..locate import locate

        item = store.get(doc_id)
        result = item.get("result") or {}
        field = next((f for f in result.get("fields") or [] if f["field"] == name), None)
        if field is None:
            raise HTTPException(status_code=404, detail="Nieznane pole")
        boxes = locate(item["path"], field, result.get("text") or "", app.processor.settings.ocr)
        if not boxes and result.get("ocr"):
            return {"field": name, "boxes": [], "reason": "Nie znaleźliśmy tej wartości na skanie: źródło zaznaczamy w zakładce Tekst."}
        return {"field": name, "boxes": boxes}

    @api.get("/{doc_id}/anonymized.pdf")
    def anonymized(doc_id: str) -> Response:
        """The PDF with personal data blacked out; names are also taken from the other documents of the same case."""
        from ..anonymize import redact

        item = store.get(doc_id)
        result = item.get("result") or {}
        reference = key((result.get("case_values") or {}).get("reference"))
        related = [
            f
            for other in store.processed()
            if other["id"] != doc_id and reference and key((other.get("case_values") or {}).get("reference")) == reference
            for f in other.get("fields") or []
        ]
        data, counts = redact(item["path"], result.get("fields") or [], result.get("text") or "", related, ocr=app.processor.settings.ocr)
        name = Path(result.get("filename") or "dokument.pdf").stem + "_anonimizacja.pdf"
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Redacted": json.dumps(counts), "Access-Control-Expose-Headers": "X-Redacted"})

    @api.get("/{doc_id}/json")
    def download(doc_id: str) -> Response:
        """Download the output JSON named after the source PDF."""
        result = store.get(doc_id)["result"]
        name = Path(result["filename"]).with_suffix(".json").name
        return Response(
            json.dumps(result["data"] if result["data"] is not None else {}, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    return api
