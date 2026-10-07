"""Command-line client for the PolyForge backend.

Do prompt ao polígono — from prompt to polygon.

The CLI talks to a running ``polyforge-api`` server over HTTP, so the same
``XDG_CACHE_HOME`` is shared between the CLI and the API (the API does the
heavy lifting; the CLI just submits jobs and downloads the result).

Examples::

    # Submit a text-to-3D job and wait for the GLB:
    polyforge-cli text "a red chair" --output chair.glb

    # Image-to-3D:
    polyforge-cli image input.png --output model.glb --texture

    # Multi-view from 4 images:
    polyforge-cli multiview front.png back.png left.png right.png \\
        --output model.glb

    # Re-texture an existing mesh (GLB) with an image:
    polyforge-cli texture-mesh mesh.glb --image ref.png --output textured.glb
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

DEFAULT_API_URL = os.environ.get("POLYFORGE_API_URL", "http://127.0.0.1:8081")
DEFAULT_API_KEY = os.environ.get("POLYFORGE_API_KEY") or None
DEFAULT_TIMEOUT = 30
POLL_INTERVAL = 2.0
POLL_TIMEOUT = 900.0  # 15 minutes


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _request(
    method: str,
    url: str,
    *,
    data: dict | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **({"X-API-Key": api_key} if api_key else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8") or "{}"
            return cast(dict, json.loads(payload))
    except urllib.error.HTTPError as e:
        # Try to surface a helpful error body.
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = str(e)
        raise SystemExit(f"HTTP {e.code} {e.reason}: {detail}") from None
    except urllib.error.URLError as e:
        raise SystemExit(
            f"Could not reach the backend at {url}: {e.reason}. Is `polyforge-api` running?"
        ) from None


def _encode_image(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"Image not found: {path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _encode_mesh(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"Mesh not found: {path}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _wait_for_completion(
    api_url: str, uid: str, *, api_key: str | None, timeout: float = POLL_TIMEOUT
) -> dict:
    deadline = time.monotonic() + timeout
    last_status: str | None = None
    while time.monotonic() < deadline:
        job = _request("GET", f"{api_url}/v1/jobs/{uid}", api_key=api_key)
        status = job.get("status")
        if status != last_status:
            print(f"  job {uid[:8]} status: {status}")
            last_status = status
        if status == "completed":
            return job
        if status in ("failed", "cancelled"):
            err = job.get("error", "unknown")
            raise SystemExit(f"Job {uid} {status}: {err}")
        time.sleep(POLL_INTERVAL)
    raise SystemExit(f"Job {uid} did not complete within {timeout:.0f}s.")


def _wait_via_sse(
    api_url: str, uid: str, *, api_key: str | None, timeout: float = POLL_TIMEOUT
) -> dict:
    """Stream job status updates over SSE.

    Reads the stream line by line, parses the ``data:`` lines as JSON,
    and stops at the first terminal status. Falls back gracefully if
    the server doesn't support SSE.
    """
    url = f"{api_url}/v1/jobs/{uid}/events"
    headers = {"Accept": "text/event-stream", **({"X-API-Key": api_key} if api_key else {})}
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SystemExit(f"Job {uid} not found.") from None
        raise SystemExit(f"SSE failed: HTTP {e.code} {e.reason}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"Could not reach the backend at {url}: {e.reason}") from None

    deadline = time.monotonic() + timeout
    last_status: str | None = None
    try:
        for raw in resp:
            if time.monotonic() > deadline:
                raise SystemExit(f"Job {uid} did not complete within {timeout:.0f}s.")
            line = raw.decode("utf-8", errors="ignore").rstrip("\r\n")
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if not payload or payload == "{}":
                continue  # keep-alive ping
            try:
                event = cast(dict, json.loads(payload))
            except json.JSONDecodeError:
                continue
            status = event.get("status")
            if status != last_status:
                print(f"  job {uid[:8]} status: {status}")
                last_status = status
            if status == "completed":
                return event
            if status in ("failed", "cancelled"):
                err = event.get("error", "unknown")
                raise SystemExit(f"Job {uid} {status}: {err}")
    finally:
        resp.close()
    raise SystemExit(f"Job {uid} stream ended without a terminal status.")


def _download(file_path: str, output: Path, api_url: str) -> None:
    basename = os.path.basename(file_path)
    url = f"{api_url}/files/{urllib.parse.quote(basename)}"
    print(f"Downloading {basename} → {output}…")
    try:
        with urllib.request.urlopen(url, timeout=300) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Download failed: HTTP {e.code} {e.reason}") from None
    output.write_bytes(data)
    print(f"Wrote {len(data)} bytes to {output}.")


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _cmd_generate(args: argparse.Namespace) -> int:
    """Unified generation: dispatch to /v1/generate with whatever inputs
    were provided. The backend infers the mode from the fields that are
    set.
    """
    payload: dict[str, Any] = {
        "steps": args.steps,
        "guidance": args.guidance,
        "octree_resolution": args.octree_resolution,
        "seed": args.seed,
        "format": args.format,
        "texture": args.texture,
        "face_count": args.face_count,
        "remove_background": not getattr(args, "no_rembg", False),
    }
    if args.text is not None:
        payload["text"] = args.text
    if args.image is not None:
        payload["image"] = _encode_image(Path(args.image))
    if args.views is not None:
        payload["views"] = {
            "front": _encode_image(Path(args.views[0])),
            "back": _encode_image(Path(args.views[1])),
            "left": _encode_image(Path(args.views[2])),
            "right": _encode_image(Path(args.views[3])),
        }
    if args.mesh is not None:
        payload["mesh"] = _encode_image(Path(args.mesh))

    if not any(
        [
            payload.get("text"),
            payload.get("image"),
            payload.get("views"),
            payload.get("mesh"),
        ]
    ):
        raise SystemExit("generate: provide at least one of --text, --image, --views, --mesh")

    job = _request("POST", f"{args.api_url}/v1/generate", data=payload, api_key=args.api_key)
    uid = job["uid"]
    print(f"Submitted {uid}.")
    final = _maybe_stream_wait(args, uid)
    if final.get("file_path") and args.output:
        _download(final["file_path"], Path(args.output), args.api_url)
    elif not args.output:
        print(f"  uid: {uid}")
    return 0


def _cmd_text(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {
        "type": "text_to_3d",
        "prompt": args.prompt,
        "steps": args.steps,
        "guidance": args.guidance,
        "octree_resolution": args.octree_resolution,
        "seed": args.seed,
        "format": args.format,
        "texture": args.texture,
    }
    job = _request("POST", f"{args.api_url}/v1/jobs", data=payload, api_key=args.api_key)
    uid = job["uid"]
    print(f"Submitted {uid}.")
    final = _maybe_stream_wait(args, uid)
    if final.get("file_path") and args.output:
        _download(final["file_path"], Path(args.output), args.api_url)
    return 0


def _cmd_image(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {
        "type": "image_to_3d",
        "image": _encode_image(Path(args.input)),
        "remove_background": not args.no_rembg,
        "steps": args.steps,
        "guidance": args.guidance,
        "octree_resolution": args.octree_resolution,
        "seed": args.seed,
        "format": args.format,
        "texture": args.texture,
    }
    job = _request("POST", f"{args.api_url}/v1/jobs", data=payload, api_key=args.api_key)
    uid = job["uid"]
    print(f"Submitted {uid}.")
    final = _maybe_stream_wait(args, uid)
    if final.get("file_path") and args.output:
        _download(final["file_path"], Path(args.output), args.api_url)
    return 0


def _cmd_multiview(args: argparse.Namespace) -> int:
    if len(args.views) != 4:
        raise SystemExit("multiview requires exactly 4 image paths (front, back, left, right).")
    payload: dict[str, Any] = {
        "type": "multiview",
        "front": _encode_image(Path(args.views[0])),
        "back": _encode_image(Path(args.views[1])),
        "left": _encode_image(Path(args.views[2])),
        "right": _encode_image(Path(args.views[3])),
        "steps": args.steps,
        "guidance": args.guidance,
        "octree_resolution": args.octree_resolution,
        "seed": args.seed,
        "format": args.format,
        "texture": args.texture,
    }
    job = _request("POST", f"{args.api_url}/v1/jobs", data=payload, api_key=args.api_key)
    uid = job["uid"]
    print(f"Submitted {uid}.")
    final = _maybe_stream_wait(args, uid)
    if final.get("file_path") and args.output:
        _download(final["file_path"], Path(args.output), args.api_url)
    return 0


def _cmd_texture_mesh(args: argparse.Namespace) -> int:
    if not args.image and not args.prompt:
        raise SystemExit("texture-mesh requires --image or --prompt as the reference.")
    payload: dict[str, Any] = {
        "type": "texture_mesh",
        "mesh": _encode_mesh(Path(args.mesh)),
        "steps": args.steps,
        "guidance": args.guidance,
        "octree_resolution": args.octree_resolution,
        "seed": args.seed,
        "format": args.format,
        "texture": True,
    }
    if args.image:
        payload["image"] = _encode_image(Path(args.image))
    if args.prompt:
        payload["prompt"] = args.prompt
    job = _request("POST", f"{args.api_url}/v1/jobs", data=payload, api_key=args.api_key)
    uid = job["uid"]
    print(f"Submitted {uid}.")
    final = _maybe_stream_wait(args, uid)
    if final.get("file_path") and args.output:
        _download(final["file_path"], Path(args.output), args.api_url)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    job = _request("GET", f"{args.api_url}/v1/jobs/{args.uid}", api_key=args.api_key)
    print(json.dumps(job, indent=2))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    jobs = _request("GET", f"{args.api_url}/v1/jobs", api_key=args.api_key)
    if args.json:
        print(json.dumps(jobs, indent=2))
    else:
        for j in jobs:
            print(f"{j['uid'][:8]}  {j['status']:>10}  {j['created_at']}")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _maybe_stream_wait(args: argparse.Namespace, uid: str) -> dict:
    """Pick the SSE-backed waiter when ``--stream`` is set, else poll."""
    if args.stream:
        try:
            return _wait_via_sse(
                args.api_url,
                uid,
                api_key=args.api_key,
                timeout=args.timeout,
            )
        except SystemExit as e:
            # SSE endpoint missing or server pre-SSE; fall back to polling.
            print(f"  SSE not available ({e}); falling back to polling.")
            return _wait_for_completion(
                args.api_url,
                uid,
                api_key=args.api_key,
                timeout=args.timeout,
            )
    return _wait_for_completion(
        args.api_url,
        uid,
        api_key=args.api_key,
        timeout=args.timeout,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="polyforge-cli",
        description=__doc__.split("\n\n", 1)[0] if __doc__ else "PolyForge CLI",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help="Backend base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        help="X-API-Key header value (default: POLYFORGE_API_KEY env)",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--steps", type=int, default=50, help="Inference steps (default: 50)")
    common.add_argument("--guidance", type=float, default=5.0, help="Guidance scale (default: 5.0)")
    common.add_argument(
        "--octree-resolution",
        type=int,
        default=256,
        help="Octree resolution (default: 256)",
    )
    common.add_argument("--seed", type=int, default=1234, help="Random seed (default: 1234)")
    common.add_argument(
        "--format",
        choices=["glb", "obj", "ply", "stl"],
        default="glb",
        help="Output format (default: glb)",
    )
    common.add_argument("--texture", action="store_true", help="Generate a texture map")
    common.add_argument(
        "-o",
        "--output",
        help="Download path for the resulting mesh (default: just print uid)",
    )
    common.add_argument(
        "--timeout",
        type=float,
        default=POLL_TIMEOUT,
        help="Maximum seconds to wait for completion (default: %(default)s)",
    )
    common.add_argument(
        "--stream",
        action="store_true",
        help="Use Server-Sent Events to wait for completion (lower latency, fewer requests)",
    )

    p = sub.add_parser(
        "generate",
        parents=[common],
        help="Unified generation: provide any of --text, --image, --views, --mesh. "
        "The backend infers the mode from what you supply.",
    )
    p.add_argument("--text", help="Text prompt (or guide for image_to_3d)")
    p.add_argument("--image", help="Path to a single image (image_to_3d / texture reference)")
    p.add_argument(
        "--views",
        nargs=4,
        metavar=("FRONT", "BACK", "LEFT", "RIGHT"),
        help="Paths to 4 view images (multiview mode)",
    )
    p.add_argument(
        "--mesh",
        help="Path to a GLB mesh to re-texture (texture_mesh mode)",
    )
    p.add_argument("--no-rembg", action="store_true", help="Skip background removal (image_to_3d)")
    p.set_defaults(func=_cmd_generate)

    p = sub.add_parser(
        "text",
        parents=[common],
        help="[deprecated] Generate a 3D model from a text prompt (use 'generate --text=...')",
    )
    p.add_argument("prompt", help="Text prompt describing the model")
    p.set_defaults(func=_cmd_text)

    p = sub.add_parser("image", parents=[common], help="Generate a 3D model from a single image")
    p.add_argument("input", help="Path to the input image (PNG/JPEG/WebP)")
    p.add_argument("--no-rembg", action="store_true", help="Skip background removal")
    p.set_defaults(func=_cmd_image)

    p = sub.add_parser(
        "multiview",
        parents=[common],
        help="Generate from 4 view images (front back left right)",
    )
    p.add_argument("views", nargs=4, help="Paths to front, back, left, right images")
    p.set_defaults(func=_cmd_multiview)

    p = sub.add_parser(
        "texture-mesh",
        parents=[common],
        help="Re-texture an existing GLB mesh with a reference image or prompt",
    )
    p.add_argument("mesh", help="Path to the input .glb mesh")
    p.add_argument("--image", help="Reference image (optional if --prompt is given)")
    p.add_argument("--prompt", help="Reference text prompt (optional if --image is given)")
    p.set_defaults(func=_cmd_texture_mesh)

    p = sub.add_parser("status", help="Get the status of a single job")
    p.add_argument("uid", help="Job UID")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("list", help="List recent jobs")
    p.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    p.set_defaults(func=_cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return cast(int, args.func(args))


if __name__ == "__main__":
    sys.exit(main())
