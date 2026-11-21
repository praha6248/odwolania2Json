"""Loading of application settings and document type definitions from YAML files."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@dataclass
class DocumentType:
    """Declarative description of one class of documents."""

    name: str
    label: str
    classify: dict[str, Any]
    sections: dict[str, dict[str, Any]]
    fields: dict[str, dict[str, Any]]
    template: Any
    llm: dict[str, Any] = field(default_factory=dict)
    source: Path | None = None


@dataclass
class Settings:
    """Global application settings."""

    min_classification_score: float = 3.0
    llm: dict[str, Any] = field(default_factory=dict)
    ocr: dict[str, Any] = field(default_factory=dict)
    plugins: list[str] = field(default_factory=lambda: ["odwolania2json.extractors"])
    document_types: list[DocumentType] = field(default_factory=list)

    def get_type(self, name: str) -> DocumentType | None:
        """Return the document type with the given name, if configured."""
        return next((t for t in self.document_types if t.name == name), None)


def load_document_type(path: Path) -> DocumentType:
    """Parse a single document type YAML file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = {"name", "classify", "fields", "template"} - data.keys()
    if missing:
        raise ValueError(f"{path}: missing keys {sorted(missing)}")
    return DocumentType(
        name=data["name"],
        label=data.get("label", data["name"]),
        classify=data["classify"],
        sections=data.get("sections", {}) or {},
        fields=data["fields"],
        template=data["template"],
        llm=data.get("llm", {}) or {},
        source=path,
    )


def load_settings(config_dir: str | Path | None = None) -> Settings:
    """Load settings.yaml, import extractor plugin modules and read every document type from the configuration directory."""
    config_dir = Path(config_dir or os.environ.get("O2J_CONFIG_DIR") or DEFAULT_CONFIG_DIR)
    settings_file = config_dir / "settings.yaml"
    raw = yaml.safe_load(settings_file.read_text(encoding="utf-8")) if settings_file.exists() else {}
    raw = raw or {}
    llm = dict(raw.get("llm", {}) or {})
    for key, env in (("base_url", "O2J_LLM_URL"), ("model", "O2J_LLM_MODEL"), ("api_key", "O2J_LLM_API_KEY")):
        if os.environ.get(env):
            llm[key] = os.environ[env]
    if os.environ.get("O2J_LLM_ENABLED"):
        llm["enabled"] = os.environ["O2J_LLM_ENABLED"].lower() in {"1", "true", "yes"}
    plugins = list(raw.get("plugins") or ["odwolania2json.extractors"])
    for module in plugins:
        importlib.import_module(module)
    types = [load_document_type(p) for p in sorted((config_dir / "document_types").glob("*.y*ml"))]
    return Settings(
        min_classification_score=float(raw.get("min_classification_score", 3.0)),
        llm=llm,
        ocr=dict(raw.get("ocr", {}) or {}),
        plugins=plugins,
        document_types=types,
    )
