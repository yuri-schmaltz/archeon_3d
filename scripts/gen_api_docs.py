"""Regenerate docs/API_DOCUMENTATION.md from the live OpenAPI schema.

Run with the server NOT required: the spec is built by importing the
FastAPI app in-process, so the docs can never drift from the code.

    python scripts/gen_api_docs.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DOC_PATH = REPO_ROOT / "docs" / "API_DOCUMENTATION.md"

# Endpoints that are part of the API contract but hidden from the schema.
UNSCHEMAED = [
    ("GET", "/metrics", "Prometheus metrics in text format (excluded from the schema)."),
]


def _fmt_default(prop: dict[str, Any]) -> str:
    if "default" in prop:
        return f"`{prop['default']!r}`"
    if prop.get("type") == "string" and "enum" in prop:
        return "required"
    return "—"


def _fmt_range(prop: dict[str, Any]) -> str:
    lo, hi = prop.get("minimum"), prop.get("maximum")
    if lo is not None and hi is not None:
        # ASCII hyphen: the table is read in terminals without the dash glyph.
        return f"{lo:g}-{hi:g}"
    if lo is not None:
        return f"≥ {lo:g}"
    if hi is not None:
        return f"≤ {hi:g}"
    if prop.get("type") == "integer":
        return "int"
    if prop.get("type") == "number":
        return "float"
    if prop.get("type") == "boolean":
        return "bool"
    if "enum" in prop:
        return " \\| ".join(f"`{v}`" for v in prop["enum"])
    return "str"


def _clean(text: str) -> str:
    """Flatten RST docstrings into readable Markdown.

    Docstrings in this codebase are written in RST (``literal``,
    ``\\n``-separated bullets), which renders as noise inside a Markdown
    table cell.
    """
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Drop RST bullet markers but keep the text.
        stripped = re.sub(r"^[-*]\s+", "", stripped)
        stripped = stripped.replace("``", "`")
        out.append(stripped)
    return " ".join(out) if out else ""


def _body_params(operation: dict[str, Any], schemas: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve a JSON body into a flat list of field descriptions."""
    body = operation.get("requestBody", {})
    ref = body.get("content", {}).get("application/json", {}).get("schema", {}).get("$ref", "")
    if not ref:
        return []
    name = ref.rsplit("/", 1)[-1]
    schema = schemas.get(name, {})
    if schema.get("type") == "array":  # e.g. list[JobResponse]
        return []
    required = set(schema.get("required", []))
    rows: list[dict[str, Any]] = []
    for field, prop in schema.get("properties", {}).items():
        rows.append(
            {
                "name": field,
                "type": _fmt_range(prop),
                "default": "required" if field in required else _fmt_default(prop),
                "desc": _clean(prop.get("description", "")),
            }
        )
    return rows


def _query_params(operation: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for param in operation.get("parameters", []):
        # The X-API-Key dependency shows up as a header parameter; auth is
        # documented once, above, not repeated on every endpoint.
        if param.get("in") != "query":
            continue
        prop = param.get("schema", {})
        rows.append(
            {
                "name": f"`{param['name']}`",
                "type": _fmt_range(prop),
                "default": "required" if param.get("required") else _fmt_default(prop),
                "desc": _clean(param.get("description", "")),
            }
        )
    return rows


def render(spec: dict[str, Any]) -> str:
    schemas = spec.get("components", {}).get("schemas", {})
    info = spec["info"]
    out: list[str] = []
    a = out.append

    a(f"# {info['title']} — API Reference")
    a("")
    a(f"Version `{info['version']}`. Generated from the OpenAPI schema by")
    a("`scripts/gen_api_docs.py`; do not edit by hand.")
    a("")
    a(info.get("description", ""))
    a("")
    a("## Contents")
    a("")
    a("- [Authentication](#authentication)")
    a("- [Probes and metrics](#probes-and-metrics)")
    a("- [Endpoints](#endpoints)")
    a("")

    total = sum(len(v) for v in spec["paths"].values())
    a(f"{total} operations across {len(spec['paths'])} paths.")
    a("")

    # -- auth ----------------------------------------------------------
    a("## Authentication")
    a("")
    a("When `POLYFORGE_API_KEY` is set, every `/v1/*` route requires an `X-API-Key`")
    a("header. A missing header returns `401` with `WWW-Authenticate: ApiKey`; a")
    a("wrong key returns `403`. With no key configured, auth is disabled (dev only).")
    a("")
    a("`/health`, `/ready`, `/metrics` and the frontend assets are always open.")
    a("")
    a("`/files/**` accepts either the API key or an HMAC-signed token from")
    a("`GET /v1/jobs/{uid}/download-url`.")
    a("")

    # -- probes --------------------------------------------------------
    a("## Probes and metrics")
    a("")
    a("| Method | Path | Purpose |")
    a("| --- | --- | --- |")
    for method, path in [("get", "/health"), ("get", "/ready")]:
        op = spec["paths"].get(path, {}).get(method)
        if op:
            a(f"| `{method.upper()}` | `{path}` | {op.get('summary', op.get('description', ''))} |")
    for method, path, desc in UNSCHEMAED:
        a(f"| `{method}` | `{path}` | {desc} |")
    a("")
    a("`/health` is a **liveness** probe: it answers `200` as soon as the process is")
    a("up and reports a `ready` boolean. `/ready` is the **readiness** gate: it")
    a("returns `503` until the job store has been rehydrated into memory, so a load")
    a("balancer can hold traffic until the in-memory job view matches the store.")
    a("")

    # -- endpoints -----------------------------------------------------
    a("## Endpoints")
    a("")
    for path in sorted(spec["paths"]):
        item = spec["paths"][path]
        methods = [m for m in item if m in ("get", "post", "delete", "put", "patch")]
        for method in methods:
            op = item[method]
            summary = op.get("summary") or ""
            a(f"### `{method.upper()} {path}`")
            a("")
            if summary:
                a(summary)
                a("")
            desc = _clean(op.get("description") or "")
            if desc:
                a(desc)
                a("")
            responses = op.get("responses", {})
            if responses:
                codes = ", ".join(f"`{c}`" for c in sorted(responses) if c != "default") or "—"
                a(f"Responses: {codes}")
                a("")
            body = _body_params(op, schemas)
            if body:
                a("**Body**")
                a("")
                a("| Field | Type | Default | Description |")
                a("| --- | --- | --- | --- |")
                for row in body:
                    a(f"| `{row['name']}` | {row['type']} | {row['default']} | {row['desc']} |")
                a("")
            query = _query_params(op)
            if query:
                a("**Query parameters**")
                a("")
                a("| Name | Type | Default | Description |")
                a("| --- | --- | --- | --- |")
                for row in query:
                    a(f"| {row['name']} | {row['type']} | {row['default']} | {row['desc']} |")
                a("")

    # -- notes ---------------------------------------------------------
    a("## Notes")
    a("")
    a("- Two endpoints stream Server-Sent Events: `/v1/jobs/events` for the whole")
    a("  list and `/v1/jobs/{uid}/events` for a single job. Both close on a")
    a("  terminal status (`completed`, `failed`, `cancelled`).")
    a("- `/v1/jobs` is paginated (`limit` caps at 200). Use `/v1/library` to page")
    a("  through the full history, which reads from SQLite and survives restarts.")
    a("- Only one uvicorn worker is supported: inference is serialised through a")
    a("  single in-process queue on one GPU. Run one process per GPU.")
    a("- SSE streams must be declared before `/v1/jobs/{uid}` in the route table or")
    a("  the literal path would be captured by the parameter.")
    a("")
    return "\n".join(out)


def main() -> int:
    from hy3dgen.api.server import app

    spec = app.openapi()
    DOC_PATH.write_text(render(spec), encoding="utf-8")
    # Also refresh the machine-readable spec if it is tracked.
    json_path = REPO_ROOT / "openapi.json"
    json_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    total = sum(len(v) for v in spec["paths"].values())
    print(f">>> wrote {DOC_PATH.relative_to(REPO_ROOT)} ({total} operations)")
    print(f">>> wrote {json_path.relative_to(REPO_ROOT)}")
    return 0


# NOTE: openapi.json is a generated artifact, regenerated by
# ``make openapi``. It is intentionally not tracked so the reference doc
# and the schema cannot disagree in review.


if __name__ == "__main__":
    raise SystemExit(main())
