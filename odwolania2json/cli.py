"""Command line interface."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .config import load_settings

ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(prog="odwolania2json", description="Convert KIO appeal PDFs into JSON.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, default=None, help="configuration directory (default: ./config)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="process ./input into ./output")
    run.add_argument("-i", "--input", type=Path, default=ROOT / "input")
    run.add_argument("-o", "--output", type=Path, default=ROOT / "output")
    run.add_argument("--trace", type=Path, default=None, help="write per-field extraction traces here")
    run.add_argument("--llm", action=argparse.BooleanOptionalAction, default=None, help="force LLM refinement on/off")

    one = sub.add_parser("extract", help="print JSON for a single PDF")
    one.add_argument("pdf", type=Path)
    one.add_argument("--type", default=None, help="skip classification and use this document type")
    one.add_argument("--trace", action="store_true", help="print the extraction trace instead")
    one.add_argument("--llm", action=argparse.BooleanOptionalAction, default=None)

    ev = sub.add_parser("eval", help="measure F1 on a labelled dataset")
    ev.add_argument("data", type=Path)
    ev.add_argument("--errors", type=int, default=0, help="show this many mismatches")
    ev.add_argument("--strict", action="store_true", help="require exact matches for long strings")
    ev.add_argument("--llm", action=argparse.BooleanOptionalAction, default=None)

    serve = sub.add_parser("serve", help="start the web interface")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("types", help="list configured document types, extractors and normalizers")
    sub.add_parser("llm-check", help="test the configured LLM endpoint (models, JSON answer, latency)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point; defaults to the 'run' command when no subcommand is given."""
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    if not any(a in {"run", "extract", "eval", "serve", "types", "llm-check"} for a in argv) and not any(a in {"-h", "--help", "--version"} for a in argv):
        argv = [*argv, "run"]
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    from .pipeline import Processor

    if args.command == "serve":
        import uvicorn

        from .web.app import create_app

        uvicorn.run(create_app(args.config), host=args.host, port=args.port)
        return 0

    settings = load_settings(args.config)

    if args.command == "types":
        from . import engine, normalizers

        for t in settings.document_types:
            print(f"{t.name:16} {t.label}  ({t.source})  fields: {', '.join(t.fields)}")
        print("extractors:", ", ".join(engine.available_extractors()))
        print("normalizers:", ", ".join(normalizers.available()))
        return 0

    if args.command == "llm-check":
        from .llm import LLMClient

        client = LLMClient(settings.llm)
        print(f"Endpoint: {client.base_url}  model: {client.model}  enabled: {settings.llm.get('enabled', False)}")
        try:
            print("Models:", ", ".join(client.models()) or "(none listed)")
            print(json.dumps(client.check(), ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f"LLM check failed: {exc}")
            return 1
        return 0

    processor = Processor(settings, use_llm=getattr(args, "llm", None))

    if args.command == "run":
        args.input.mkdir(parents=True, exist_ok=True)
        results = processor.process_tree(args.input, args.output, args.trace)
        done = sum(r.data is not None for r in results)
        unmatched = [r for r in results if r.data is None and r.error is None]
        empty = len(unmatched) if processor.settings.unmatched_output == "empty_json" else 0
        print(f"Processed {len(results)} PDF(s): {done} recognized, {len(unmatched)} outside the configured types"
              f"{f' (empty JSON {{}} written)' if empty else ''}; output in {args.output}")
        for result in results:
            if result.data is None:
                suffix = " Zapisano pusty JSON {}." if empty and result.error is None else ""
                print(f"  {result.path.name}: {result.message}{suffix}")
        return 0

    if args.command == "extract":
        result = processor.process_pdf(args.pdf, args.type)
        if args.trace:
            print(json.dumps(result.trace(), ensure_ascii=False, indent=2))
        elif result.data is not None:
            print(json.dumps(result.data, ensure_ascii=False, indent=2))
        if result.data is None:
            print(result.message, file=sys.stderr)
            return 2
        return 0

    if args.command == "eval":
        from .evaluate import evaluate_dataset, format_report

        print(format_report(evaluate_dataset(processor, args.data, fuzzy=not args.strict), args.errors))
        return 0

    parser.print_help()
    return 1
