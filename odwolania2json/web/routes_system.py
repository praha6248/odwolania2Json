"""Routes for application info, configuration reload, LLM settings and patch updates."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from .state import AppState


def router(app: AppState) -> APIRouter:
    """Build the system routes bound to the application state."""
    api = APIRouter(prefix="/api")

    from ..updater import Updater

    updater = Updater()

    @api.get("/info")
    def info() -> dict[str, Any]:
        """Return version, configured document types and LLM status."""
        return app.info()

    @api.post("/reload")
    def reload() -> dict[str, Any]:
        """Reload YAML configuration without restarting the server."""
        app.reload()
        return app.info()

    @api.get("/update")
    def update() -> dict[str, Any]:
        """Report whether a newer release exists and how many changed files a patch update would download."""
        try:
            return updater.check()
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    @api.post("/update/start")
    def update_start() -> dict[str, Any]:
        """Start downloading only the changed files of the new release."""
        return updater.start()

    @api.get("/update/status")
    def update_status() -> dict[str, Any]:
        """Progress of the running update."""
        return {k: v for k, v in updater.status().items() if k in {"stage", "done", "total", "error"}}

    @api.post("/update/restart")
    def update_restart() -> dict[str, Any]:
        """Apply the downloaded patch and restart the application."""
        return {k: v for k, v in updater.restart().items() if k in {"stage", "error"}}

    def llm_view() -> dict[str, Any]:
        """Public view of the LLM settings without the API key."""
        cfg = app.settings.llm
        return {
            "enabled": bool(app.processor.llm),
            "mode": cfg.get("mode", "fast"),
            "base_url": cfg.get("base_url", ""),
            "model": cfg.get("model", ""),
            "has_key": bool(cfg.get("api_key")),
        }

    @api.get("/llm")
    def get_llm() -> dict[str, Any]:
        """Return the current LLM configuration."""
        return llm_view()

    @api.put("/llm")
    def set_llm(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Change LLM settings at runtime; with persist=true also store them in .env."""
        cfg = app.settings.llm
        for key in ("base_url", "model"):
            if isinstance(body.get(key), str) and body[key].strip():
                cfg[key] = body[key].strip()
        if isinstance(body.get("api_key"), str) and body["api_key"]:
            cfg["api_key"] = body["api_key"]
        cfg["enabled"] = bool(body.get("enabled", cfg.get("enabled", False)))
        if body.get("mode") in ("fast", "accurate"):
            cfg["mode"] = body["mode"]
        app.rebuild_processor()
        if body.get("persist"):
            from ..config import save_env

            updates = {"O2J_LLM_ENABLED": str(cfg["enabled"]).lower(), "O2J_LLM_URL": cfg.get("base_url", ""), "O2J_LLM_MODEL": cfg.get("model", ""), "O2J_LLM_MODE": cfg.get("mode", "fast")}
            if body.get("api_key"):
                updates["O2J_LLM_API_KEY"] = body["api_key"]
            save_env(updates)
        return llm_view()

    @api.post("/llm/check")
    def check_llm() -> dict[str, Any]:
        """Test the configured endpoint: list models and run a tiny extraction."""
        from ..llm import LLMClient

        client = LLMClient(app.settings.llm)
        try:
            return {"ok": True, "models": client.models(), **client.check()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return api
