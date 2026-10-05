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


def decode_base64(value: str) -> bytes:
    return base64.b64decode(value.split(",", 1)[-1], validate=True)


def load_image_from_base64(image_b64: str) -> Image.Image:
    from PIL import Image

    with Image.open(BytesIO(decode_base64(image_b64))) as image:
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
        multiview_model_path="tencent/Hunyuan3D-2mv",
        multiview_subfolder="hunyuan3d-dit-v2-mv",
    ):
        self.model_path = model_path
        self.tex_model_path = tex_model_path
        self.subfolder = subfolder
        self.device = device
        self.enable_tex = enable_tex
        self.enable_t2i = enable_t2i
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

    def _image_from_text(self, prompt: str):
        if not self.enable_t2i:
            raise ValueError("Text-to-3D is not enabled for this worker.")
        if self.pipeline_t2i is None:
            from hy3dgen.text2image import HunyuanDiTPipeline

            self.pipeline_t2i = HunyuanDiTPipeline(
                "Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled",
                device=self.device,
            )
        return self.pipeline_t2i(prompt)

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
            image = self._image_from_text(params["text"])
            if remove_background:
                image = self._remove_background(image)
        else:
            raise ValueError("No input image or text provided.")

        if params.get("mesh"):
            import trimesh

            mesh = trimesh.load(
                BytesIO(decode_base64(params["mesh"])),
                file_type="glb",
                force="mesh",
            )
        else:
            pipeline = self._load_shape_pipeline(multiview)
            started = time.monotonic()
            mesh = pipeline(
                image=image,
                generator=torch.Generator(self.device).manual_seed(params.get("seed", 1234)),
                octree_resolution=params.get("octree_resolution", 256),
                num_inference_steps=params.get("steps", 50),
                guidance_scale=params.get("guidance", 5.0),
                mc_algo="dmc",
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
