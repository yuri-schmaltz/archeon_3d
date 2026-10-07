from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hy3dgen.api import config as config_module


def _setting_default(name: str):
    """Read an operator-configurable generation default at validation time."""

    return lambda: getattr(config_module.settings, name)


def _setting_field(name: str, **kwargs: Any):
    """Declare a settings-backed default without freezing it in validation.

    ``default_factory`` keeps the runtime value dynamic when operators change
    ``POLYFORGE_DEFAULT_*`` and restart. ``json_schema_extra`` preserves the
    startup default in OpenAPI/docs.
    """

    return Field(
        default_factory=_setting_default(name),
        json_schema_extra={"default": getattr(config_module.settings, name)},
        **kwargs,
    )


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MeshOpsAction(str, Enum):
    DECIMATE = "decimate"
    CONVERT = "convert"
    SEPARATE = "separate"


class BaseGenerationRequest(BaseModel):
    """Common parameters for all generation types."""

    seed: int = _setting_field(
        "default_seed",
        description="Random seed for the generated 3D output. For text_to_3d it also seeds the reference image.",
        examples=[1234],
    )
    steps: int = _setting_field(
        "default_steps",
        ge=1,
        le=100,
        description="Denoising steps for shape reconstruction. The text_to_3d reference image uses a fixed step count.",
        examples=[50, 5],
    )
    guidance: float = _setting_field(
        "default_guidance",
        ge=1.0,
        le=20.0,
        description="Guidance scale for shape reconstruction. It does not change the fixed text_to_3d reference-image settings.",
        examples=[5.0, 7.5],
    )
    octree_resolution: int = _setting_field(
        "default_octree",
        ge=16,
        le=512,
        description="Voxel resolution",
        examples=[256, 384],
    )
    format: Literal["glb", "obj", "ply", "stl"] = Field(
        "glb",
        description="Output mesh format",
        examples=["glb"],
    )
    texture: bool = Field(False, description="Generate texture?", examples=[False, True])
    face_count: int = _setting_field(
        "default_face_count",
        ge=100,
        le=1000000,
        description="Target face count for reduction",
        examples=[40000],
    )

    model_config = ConfigDict(extra="forbid")


class TextTo3DRequest(BaseGenerationRequest):
    type: Literal["text_to_3d"] = "text_to_3d"
    prompt: str = Field(
        ...,
        min_length=1,
        description="Text prompt. The reference-image stage uses its first 60 characters plus a fixed style suffix.",
        examples=["a cute cat with white fur"],
    )


class ImageTo3DRequest(BaseGenerationRequest):
    type: Literal["image_to_3d"] = "image_to_3d"
    image: str = Field(
        ...,
        description="Base64 encoded image (optionally with a `data:image/...;base64,` prefix)",
        examples=[
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        ],
    )
    remove_background: bool = Field(
        True,
        description="Remove background using rembg?",
        examples=[True],
    )


class MultiviewRequest(BaseGenerationRequest):
    type: Literal["multiview"] = "multiview"
    front: str = Field(..., description="Front view base64", examples=["<base64 png>"])
    back: str = Field(..., description="Back view base64", examples=["<base64 png>"])
    left: str = Field(..., description="Left view base64", examples=["<base64 png>"])
    right: str = Field(..., description="Right view base64", examples=["<base64 png>"])


class TextureMeshRequest(BaseGenerationRequest):
    """Re-texture an existing mesh (GLB) using either a reference image or a text prompt.

    The mesh is supplied as a base64-encoded ``.glb`` payload; the image (optional)
    and prompt (optional) steer the texture synthesis. At least one of ``image``
    or ``prompt`` must be provided. ``texture`` is implicitly true for this job
    type and is forced to True by the manager before dispatch.
    """

    type: Literal["texture_mesh"] = "texture_mesh"
    mesh: str = Field(..., description="Base64-encoded GLB of the mesh to re-texture")
    image: str | None = Field(
        None, description="Optional base64 image used as the texture reference"
    )
    prompt: str | None = Field(
        None, min_length=1, description="Optional text prompt used as the texture reference"
    )

    @property
    def has_reference(self) -> bool:
        return bool(self.image) or bool(self.prompt)


# Discriminated Union for polymorphic handling
JobRequest = Annotated[
    TextTo3DRequest | ImageTo3DRequest | MultiviewRequest | TextureMeshRequest,
    Field(discriminator="type"),
]


class JobResponse(BaseModel):
    uid: str
    status: JobStatus
    created_at: str
    completed_at: str | None = None
    error: str | None = None
    file_path: str | None = None
    updated_at: str | None = None
    request_type: str | None = None
    # Stage progress (PR for Fase 2): the inference worker can emit
    # intermediate states so the UI can render a meaningful progress bar
    # instead of just "queued"/"processing". ``stage`` is a short label
    # (e.g. "loading_model", "shape_generation", "texturing",
    # "exporting"); ``stage_progress`` is a float in [0, 1].
    stage: str | None = None
    stage_progress: float | None = None

    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    error: str
    code: int = 400


class MeshOpsRequest(BaseModel):
    job_uid: str = Field(
        ..., description="UID of the source job to operate on", examples=["abc-123"]
    )
    action: MeshOpsAction = Field(
        ..., description="Mesh operation to apply", examples=[MeshOpsAction.DECIMATE]
    )
    format: Literal["glb", "obj", "ply", "stl"] = Field(
        "glb", description="Output mesh format", examples=["glb"]
    )
    ratio: float = Field(
        0.5,
        ge=0.01,
        le=1.0,
        description="For decimate: target ratio of faces to keep",
        examples=[0.5, 0.25],
    )
    # ------------------------------------------------------------------
    # Fields below are only honoured when ``action == "separate"``.
    # They mirror the parameters exposed by the ``MeshProcessor`` so
    # the UI can tune the split without poking at Python internals.
    # ------------------------------------------------------------------
    min_face_count: int = Field(
        500,
        ge=10,
        description=(
            "For separate: discard components with fewer faces than this "
            "(filters marching-cubes noise)."
        ),
        examples=[500, 1000],
    )
    only_watertight: bool = Field(
        False,
        description=(
            "For separate: keep only watertight components (recommended for 3D-printing workflows)."
        ),
        examples=[False, True],
    )
    repair: bool = Field(
        True,
        description=(
            "For separate: try to fill small holes in each component "
            "before checking watertightness."
        ),
        examples=[True, False],
    )
    min_volume_ratio: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description=(
            "For separate: discard components whose volume is smaller "
            "than this fraction of the largest component (0 disables)."
        ),
        examples=[0.0, 0.01],
    )
    model_config = ConfigDict(use_enum_values=True)


# ---------------------------------------------------------------------------
# Unified generation request (PR #7)
# ---------------------------------------------------------------------------


class _MultiviewViews(BaseModel):
    """The 4 base64-encoded views used by multiview generation."""

    model_config = ConfigDict(extra="forbid")

    front: str = Field(..., description="Front view base64 PNG")
    back: str = Field(..., description="Back view base64 PNG")
    left: str = Field(..., description="Left view base64 PNG")
    right: str = Field(..., description="Right view base64 PNG")


class GenerationRequest(BaseModel):
    """Single, unified generation request.

    Inputs are all optional at the type level, but a model validator
    enforces that at least one of them is provided and that the
    combination makes sense. The backend infers which generation
    mode to use from the fields you fill in.

    Inference rules (first match wins):
        1. ``mesh`` + (any of text/image)      -> texture_mesh
        2. ``views`` with all 4 sides          -> multiview
        3. ``image`` (text may also be set)    -> image_to_3d
        4. ``text`` (or text+image)            -> text_to_3d

    Common parameters (``seed``, ``steps``, ``guidance``, etc.) control
    the final 3D/mesh reconstruction. ``seed`` is also passed to the
    ``text_to_3d`` reference-image stage; that stage otherwise uses fixed
    diffusion settings. ``texture`` is honoured for ``text_to_3d`` and
    ``image_to_3d``; for ``texture_mesh`` it is forced to True.
    """

    model_config = ConfigDict(extra="forbid")

    # --- Inputs (any combination, validated below) -------------------
    text: str | None = Field(
        None,
        description="Text prompt or guidance. Required for text_to_3d. The reference-image stage uses its first 60 characters plus a fixed style suffix.",
        examples=["a small red cube"],
    )
    image: str | None = Field(
        None,
        description="Base64-encoded image (single view, used by image_to_3d).",
    )
    views: _MultiviewViews | None = Field(
        None,
        description="Four base64-encoded views (front/back/left/right).",
    )
    mesh: str | None = Field(
        None,
        description="Base64-encoded GLB to re-texture (texture_mesh).",
    )

    # --- Common generation parameters -------------------------------
    seed: int = _setting_field(
        "default_seed",
        description="Random seed for the generated 3D output. For text_to_3d it also seeds the reference image.",
        examples=[1234],
    )
    steps: int = _setting_field(
        "default_steps",
        ge=1,
        le=100,
        description="Denoising steps for shape reconstruction. The text_to_3d reference image uses a fixed step count.",
        examples=[50],
    )
    guidance: float = _setting_field(
        "default_guidance",
        ge=1.0,
        le=20.0,
        description="Guidance scale for shape reconstruction. It does not change the fixed text_to_3d reference-image settings.",
    )
    octree_resolution: int = _setting_field(
        "default_octree",
        ge=16,
        le=512,
        description="Voxel resolution",
    )
    format: Literal["glb", "obj", "ply", "stl"] = Field(
        "glb",
        description="Output mesh format",
    )
    texture: bool = Field(
        False,
        description="Generate texture? (Honoured for text_to_3d / image_to_3d; forced on for texture_mesh.)",
    )
    face_count: int = _setting_field(
        "default_face_count",
        ge=100,
        le=1_000_000,
        description="Target face count for reduction",
    )
    remove_background: bool = Field(
        True,
        description="Remove background using rembg? (image_to_3d only.)",
    )

    # --- Validation -------------------------------------------------

    @model_validator(mode="after")
    def _check_inputs(self) -> "GenerationRequest":
        if not any([self.text, self.image, self.views, self.mesh]):
            raise ValueError("At least one of `text`, `image`, `views`, `mesh` must be provided.")
        if self.views is not None and not all(
            [self.views.front, self.views.back, self.views.left, self.views.right]
        ):
            raise ValueError("`views` requires front, back, left, right (all non-empty).")
        if self.mesh is not None and not (self.text or self.image):
            raise ValueError(
                "`mesh` requires a reference: at least one of `text` or `image` must also be set."
            )
        return self

    # --- Mode inference + dispatch ----------------------------------

    def infer_mode(self) -> str:
        """Return the internal mode tag for this request.

        The mapping is deterministic and matches the rules documented
        on the class. Used by the manager to dispatch to the right
        internal ``JobRequest`` variant.

        Order of precedence (first match wins):
            1. ``mesh`` + (any of text/image) -> ``texture_mesh``
            2. ``views`` with all 4 sides      -> ``multiview``
            3. ``text`` provided               -> ``text_to_3d``
               (text wins over image when both are set; image is ignored)
            4. ``image`` only                  -> ``image_to_3d``
        """
        if self.mesh and (self.text or self.image):
            return "texture_mesh"
        if self.views is not None:
            return "multiview"
        if self.text:
            return "text_to_3d"
        return "image_to_3d"

    def to_internal_request(self):
        """Convert this unified request to the internal ``JobRequest`` variant.

        Returns a ``TextTo3DRequest`` / ``ImageTo3DRequest`` /
        ``MultiviewRequest`` / ``TextureMeshRequest`` depending on the
        inferred mode. The manager dispatches based on the resulting
        ``type`` discriminator.
        """
        from typing import cast

        common = cast(
            "dict[str, Any]",
            {
                "seed": self.seed,
                "steps": self.steps,
                "guidance": self.guidance,
                "octree_resolution": self.octree_resolution,
                "format": self.format,
                "face_count": self.face_count,
            },
        )
        mode = self.infer_mode()
        if mode == "texture_mesh":
            assert self.mesh is not None  # guaranteed by validator
            return TextureMeshRequest(
                type="texture_mesh",
                mesh=self.mesh,
                image=self.image,
                prompt=self.text,
                **common,
            )
        if mode == "multiview":
            assert self.views is not None  # validated above
            return MultiviewRequest(
                type="multiview",
                front=self.views.front,
                back=self.views.back,
                left=self.views.left,
                right=self.views.right,
                texture=self.texture,
                **common,
            )
        if mode == "image_to_3d":
            assert self.image is not None  # validated above
            return ImageTo3DRequest(
                type="image_to_3d",
                image=self.image,
                remove_background=self.remove_background,
                texture=self.texture,
                **common,
            )
        # text_to_3d
        assert self.text is not None  # validated above
        return TextTo3DRequest(
            type="text_to_3d",
            prompt=self.text,
            texture=self.texture,
            **common,
        )


# ---------------------------------------------------------------------------
# Capabilities (PR for Fase 2)
# ---------------------------------------------------------------------------


class ModeCapability(BaseModel):
    """Whether a generation mode is currently usable.

    ``available`` reflects both the loaded model and the configured
    environment. ``reason`` is a short human-readable string used by
    the UI to explain why a tab is disabled; it should be ``None``
    when ``available`` is True.
    """

    available: bool
    reason: str | None = None
    requires: list[str] = Field(
        default_factory=list,
        description="Optional list of capability flags this mode depends on (e.g. 'text_to_image').",
    )


class ModelInfo(BaseModel):
    """Model identifier for the UI."""

    id: str
    subfolder: str | None = None
    loaded: bool = Field(
        description="True if the model is currently in memory.",
    )


class PresetInfo(BaseModel):
    """Named parameter preset exposed to the UI.

    The optional ``expected_elapsed_s`` / ``expected_vram_mb`` /
    ``calibrated_on`` fields are populated when a calibration
    benchmark JSON is present on disk; see
    ``scripts/benchmark_presets.py`` and
    ``hy3dgen.api.inference_service._load_calibrated_presets``.
    """

    steps: int
    guidance: float
    octree_resolution: int
    expected_elapsed_s: float | None = None
    expected_vram_mb: float | None = None
    calibrated_on: str | None = None


class CapabilityLimits(BaseModel):
    """Server-side limits surfaced to the client.

    The frontend uses these to size client-side validation and to
    show informative error messages before submitting.
    """

    image_bytes: int
    mesh_bytes: int
    queue_depth: int
    body_bytes: int | None


class CapabilitiesResponse(BaseModel):
    """Static + dynamic capabilities advertised by the API.

    Returned from ``GET /v1/capabilities``. The frontend uses this
    to gate tabs, preselect presets, and size uploads.
    """

    modes: dict[str, ModeCapability]
    models: dict[str, ModelInfo]
    presets: dict[str, PresetInfo]
    limits: CapabilityLimits
    version: str


class LibraryResponse(BaseModel):
    """Paginated library view returned by ``GET /v1/library``.

    The frontend renders ``items`` directly and uses ``total`` for
    pagination UI (``page_size`` is fixed for now; ``page`` is
    1-indexed). ``has_more`` is a convenience flag so the UI can
    hide a "next" button without recomputing.
    """

    items: list[JobResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
