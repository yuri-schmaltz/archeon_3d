"""Lazy inference worker. Importing the API does not import the ML stack."""

from __future__ import annotations

import base64
import gc
import logging
import os
import time
from io import BytesIO
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)
VIEW_KEYS = ("front", "back", "left", "right")
# Canonical text-to-image checkpoint. The API layer reports this ID in
# capabilities/status responses, so keep it in one place.
DEFAULT_T2I_MODEL = "Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_MESH_BYTES = 30 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000


def decode_base64(value: str, *, max_bytes: int | None = None) -> bytes:
    encoded = value.split(",", 1)[-1]
    if max_bytes is not None and len(encoded) > ((max_bytes + 2) // 3) * 4:
        raise ValueError(f"Base64 payload exceeds the maximum size of {max_bytes} bytes.")
    decoded = base64.b64decode(encoded, validate=True)
    if max_bytes is not None and len(decoded) > max_bytes:
        raise ValueError(f"Decoded payload exceeds the maximum size of {max_bytes} bytes.")
    return decoded


def load_image_from_base64(image_b64: str) -> Image.Image:
    from PIL import Image

    with Image.open(BytesIO(decode_base64(image_b64, max_bytes=MAX_IMAGE_BYTES))) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError(f"Image dimensions exceed the {MAX_IMAGE_PIXELS}-pixel limit.")
        return image.convert("RGBA")


class ModelWorker:
    """Load only the models needed by a request; keep one shape pipeline."""

    def __init__(
        self,
        model_path="tencent/Hunyuan3D-2mini",
        tex_model_path="tencent/Hunyuan3D-2",
        subfolder="hunyuan3d-dit-v2-mini-turbo",
        device="cuda",
        enable_tex=False,
        enable_t2i=False,
        t2i_model_path: str | None = None,
        multiview_model_path="tencent/Hunyuan3D-2mv",
        multiview_subfolder="hunyuan3d-dit-v2-mv",
    ):
        self.model_path = model_path
        self.tex_model_path = tex_model_path
        self.subfolder = subfolder
        self.device = device
        self.enable_tex = enable_tex
        self.enable_t2i = enable_t2i
        self.t2i_model_path = t2i_model_path or DEFAULT_T2I_MODEL
        self.multiview_model_path = multiview_model_path
        self.multiview_subfolder = multiview_subfolder
        self.pipeline: Any = None
        self.pipeline_tex: Any = None
        self.pipeline_t2i: Any = None
        self.rembg: Any = None
        self._shape_mode: str | None = None

    def _load_shape_pipeline(self, multiview: bool = False):
        mode = "multiview" if multiview else "single"
        if self.pipeline is not None and self._shape_mode == mode:
            return self.pipeline
        import torch

        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

        # Release the previous geometry model before loading another one.
        self.pipeline = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        model = self.multiview_model_path if multiview else self.model_path
        folder = self.multiview_subfolder if multiview else self.subfolder
        logger.info("Loading shape model %s/%s", model, folder)
        self.pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            model,
            subfolder=folder,
            use_safetensors=True,
            device=self.device,
            dtype=torch.float32 if self.device == "cpu" else torch.float16,
        )
        if "turbo" in folder:
            self.pipeline.enable_flashvdm()
        self._shape_mode = mode
        return self.pipeline

    def _prepare_image(self, value: str, remove_background: bool):
        image = load_image_from_base64(value)
        return self._remove_background(image) if remove_background else image

    def _remove_background(self, image):
        if self.rembg is None:
            from hy3dgen.rembg import BackgroundRemover

            self.rembg = BackgroundRemover()
        return self.rembg(image)

    def _image_from_text(self, prompt: str, seed: int = 0):
        if not self.enable_t2i:
            raise ValueError("Text-to-3D is not enabled for this worker.")
        if self.pipeline_t2i is None:
            from hy3dgen.text2image import HunyuanDiTPipeline

            self.pipeline_t2i = HunyuanDiTPipeline(
                self.t2i_model_path,
                device=self.device,
            )
        return self.pipeline_t2i(prompt, seed=seed)

    def _texture(self, mesh, image, face_count: int):
        if not self.enable_tex:
            raise ValueError("Texture generation is not enabled for this worker.")
        from hy3dgen.shapegen import DegenerateFaceRemover, FaceReducer, FloaterRemover
        from hy3dgen.texgen import Hunyuan3DPaintPipeline

        if self.pipeline_tex is None:
            self.pipeline_tex = Hunyuan3DPaintPipeline.from_pretrained(
                self.tex_model_path,
                device=self.device,
            )
        mesh = FloaterRemover()(mesh)
        mesh = DegenerateFaceRemover()(mesh)
        mesh = FaceReducer()(mesh, max_facenum=face_count)
        return self.pipeline_tex(mesh, image)

    def generate(self, uid: str, params: dict, save_dir: str) -> str:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("Install hy3dgen[ml] to enable model inference.") from exc
        with torch.inference_mode():
            return self._generate(uid, params, save_dir)

    def warmup(self, multiview: bool = False) -> None:
        """Eagerly load the shape pipeline so the first ``generate``
        call doesn't pay the download + load latency.

        This is what ``POST /v1/models/load`` triggers behind the
        scenes. The download + weight load can take a few minutes on
        a cold cache; subsequent calls reuse the cached weights.
        """
        self._load_shape_pipeline(multiview=multiview)

    def _generate(self, uid: str, params: dict, save_dir: str) -> str:
        import torch

        multiview = params.get("type") == "multiview"
        remove_background = params.get("remove_background", True)
        if multiview:
            if not all(params.get(key) for key in VIEW_KEYS):
                raise ValueError("Multiview requires front, back, left and right images.")
            image = {key: self._prepare_image(params[key], remove_background) for key in VIEW_KEYS}
        elif params.get("image"):
            image = self._prepare_image(params["image"], remove_background)
        elif params.get("text"):
            image = self._image_from_text(params["text"], params.get("seed", 1234))
            if remove_background:
                image = self._remove_background(image)
        else:
            raise ValueError("No input image or text provided.")

        if params.get("mesh"):
            import trimesh

            mesh = trimesh.load(
                BytesIO(decode_base64(params["mesh"], max_bytes=MAX_MESH_BYTES)),
                file_type="glb",
                force="mesh",
            )
        else:
            pipeline = self._load_shape_pipeline(multiview)
            started = time.monotonic()
            # ``mc_algo`` is caller-overridable: "dmc" needs the optional
            # ``diso`` CUDA package, "mc" works on any device. Defaults
            # to "dmc" when ``diso`` is available, otherwise falls back.
            mc_algo = params.get("mc_algo")
            if mc_algo is None:
                try:
                    import diso  # noqa: F401 - availability check

                    mc_algo = "dmc"
                except ImportError:
                    mc_algo = "mc"
            mesh = pipeline(
                image=image,
                generator=torch.Generator(self.device).manual_seed(params.get("seed", 1234)),
                octree_resolution=params.get("octree_resolution", 256),
                num_inference_steps=params.get("steps", 50),
                guidance_scale=params.get("guidance", 5.0),
                mc_algo=mc_algo,
                output_type="trimesh",
            )[0]
            logger.info("Shape generation took %.2fs", time.monotonic() - started)

        if params.get("texture", False):
            # Paint takes a reference image, not the shape pipeline's view dictionary.
            reference = image["front"] if multiview else image
            mesh = self._texture(mesh, reference, params.get("face_count", 40000))

        file_type = params.get("format", "glb")
        if file_type not in ("glb", "obj", "ply", "stl"):
            raise ValueError(f"Unsupported output format: {file_type}")
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, f"{uid}.{file_type}")
        mesh.export(save_path)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return save_path


def worker_model_state(worker, defaults: dict | None = None) -> dict:
    """Summarise which model families a worker has loaded.

    ``None`` is a valid worker: it simply reports everything unloaded.
    Custom test doubles only need the attributes they exercise; missing
    attributes fall back to safe defaults. ``defaults`` supplies the
    manager/service configuration so capabilities report the configured
    model IDs even before the first worker exists.
    """
    configured = defaults or {}
    shape_loaded = worker is not None and getattr(worker, "pipeline", None) is not None
    texture_loaded = worker is not None and getattr(worker, "pipeline_tex", None) is not None
    t2i_loaded = worker is not None and getattr(worker, "pipeline_t2i", None) is not None
    t2i_enabled = worker is not None and bool(getattr(worker, "enable_t2i", False))
    multiview_loaded = worker is not None and getattr(worker, "_shape_mode", None) == "multiview"
    return {
        "shape_loaded": bool(shape_loaded),
        "texture_loaded": bool(texture_loaded),
        "t2i_loaded": bool(t2i_loaded),
        "t2i_enabled": t2i_enabled,
        "multiview_loaded": bool(multiview_loaded),
        # ``text`` is usable while T2I is enabled even before its weights
        # have been downloaded; it is not usable from shape weights alone
        # when the T2I stage is disabled.
        "text_available": bool(t2i_loaded or (shape_loaded and t2i_enabled)),
        "shape_model": getattr(worker, "model_path", None)
        or configured.get("shape_model", "tencent/Hunyuan3D-2mini"),
        "shape_subfolder": getattr(worker, "subfolder", None) or configured.get("shape_subfolder"),
        "multiview_model": getattr(worker, "multiview_model_path", None)
        or configured.get("multiview_model", "tencent/Hunyuan3D-2mv"),
        "multiview_subfolder": getattr(worker, "multiview_subfolder", None)
        or configured.get("multiview_subfolder"),
        "texture_model": getattr(worker, "tex_model_path", None)
        or configured.get("texture_model", "tencent/Hunyuan3D-2"),
        "t2i_model": getattr(worker, "t2i_model_path", None)
        or configured.get("t2i_model")
        or DEFAULT_T2I_MODEL,
    }


def model_capability_snapshot(state: dict) -> dict:
    """Build the modes/models section of ``/v1/capabilities``."""
    text_available = state["text_available"]
    shape_loaded = state["shape_loaded"]
    texture_loaded = state["texture_loaded"]
    t2i_loaded = state["t2i_loaded"]
    multiview_loaded = state["multiview_loaded"]
    return {
        "modes": {
            "text": {
                "available": text_available,
                "reason": None if text_available else "Shape/text-to-image model not loaded.",
                "requires": ["text_to_image"] if not t2i_loaded else [],
            },
            "image": {
                "available": shape_loaded,
                "reason": None if shape_loaded else "Shape model not loaded.",
                "requires": [],
            },
            "multiview": {
                "available": bool(multiview_loaded or shape_loaded),
                "reason": None
                if (multiview_loaded or shape_loaded)
                else "Multiview model not loaded.",
                "requires": [],
            },
            "texture": {
                "available": bool(texture_loaded or shape_loaded),
                "reason": None if (texture_loaded or shape_loaded) else "Texture model not loaded.",
                "requires": [],
            },
        },
        "models": {
            "shape": {
                "id": state["shape_model"],
                "subfolder": state["shape_subfolder"],
                "loaded": shape_loaded,
            },
            "multiview": {
                "id": state["multiview_model"],
                "subfolder": state["multiview_subfolder"],
                "loaded": multiview_loaded,
            },
            "texture": {
                "id": state["texture_model"],
                "subfolder": None,
                "loaded": texture_loaded,
            },
            "text_to_image": {
                "id": state["t2i_model"],
                "subfolder": None,
                "loaded": t2i_loaded,
            },
        },
    }
