"""
Tests for the Archeon API Pydantic schemas (hy3dgen.api.schemas).

These tests validate the discriminated-union ``JobRequest`` and the response
models. They do not require GPU or model loading — only pydantic.
"""
import pytest
from pydantic import TypeAdapter, ValidationError

from hy3dgen.api.schemas import (
    BaseGenerationRequest,
    ImageTo3DRequest,
    JobRequest,
    JobResponse,
    JobStatus,
    MeshOpsAction,
    MeshOpsRequest,
    MultiviewRequest,
    TextTo3DRequest,
    TextureMeshRequest,
)


# ``JobRequest`` is an ``Annotated[Union[...], Field(discriminator='type')]``
# not a ``BaseModel`` subclass, so it has no ``model_validate``. Use a
# ``TypeAdapter`` to drive discriminated-union validation.
_job_adapter = TypeAdapter(JobRequest)


# ---------------------------------------------------------------------------
# BaseGenerationRequest defaults + validation
# ---------------------------------------------------------------------------

class TestBaseGenerationRequest:
    def test_defaults(self):
        req = TextTo3DRequest(prompt="a red chair")
        assert req.seed == 1234
        assert req.steps == 50
        assert req.guidance == 5.0
        assert req.octree_resolution == 256
        assert req.format == "glb"
        assert req.texture is False
        assert req.face_count == 40000
        assert req.type == "text_to_3d"

    def test_custom_values(self):
        req = TextTo3DRequest(
            prompt="dragon",
            seed=42,
            steps=30,
            guidance=7.5,
            octree_resolution=512,
            format="obj",
            texture=True,
            face_count=20000,
        )
        assert req.seed == 42
        assert req.steps == 30
        assert req.format == "obj"
        assert req.texture is True

    def test_steps_bounds(self):
        with pytest.raises(ValidationError):
            TextTo3DRequest(prompt="x", steps=0)
        with pytest.raises(ValidationError):
            TextTo3DRequest(prompt="x", steps=101)

    def test_guidance_bounds(self):
        with pytest.raises(ValidationError):
            TextTo3DRequest(prompt="x", guidance=0.5)
        with pytest.raises(ValidationError):
            TextTo3DRequest(prompt="x", guidance=20.5)

    def test_octree_bounds(self):
        with pytest.raises(ValidationError):
            TextTo3DRequest(prompt="x", octree_resolution=8)
        with pytest.raises(ValidationError):
            TextTo3DRequest(prompt="x", octree_resolution=1024)

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            TextTo3DRequest(prompt="x", unknown_field="bad")

    def test_format_must_be_literal(self):
        with pytest.raises(ValidationError):
            TextTo3DRequest(prompt="x", format="fbx")


# ---------------------------------------------------------------------------
# Discriminated union routing
# ---------------------------------------------------------------------------

class TestDiscriminatedUnion:
    def test_text_to_3d_parses(self):
        req = _job_adapter.validate_python({
            "type": "text_to_3d",
            "prompt": "a cat",
        })
        assert isinstance(req, TextTo3DRequest)
        assert req.prompt == "a cat"

    def test_image_to_3d_parses(self):
        req = _job_adapter.validate_python({
            "type": "image_to_3d",
            "image": "aGVsbG8=",
        })
        assert isinstance(req, ImageTo3DRequest)
        assert req.image == "aGVsbG8="
        assert req.remove_background is True

    def test_multiview_parses(self):
        req = _job_adapter.validate_python({
            "type": "multiview",
            "front": "Zg==",
            "back": "Zg==",
            "left": "Zg==",
            "right": "Zg==",
        })
        assert isinstance(req, MultiviewRequest)

    def test_texture_mesh_with_image_parses(self):
        req = _job_adapter.validate_python({
            "type": "texture_mesh",
            "mesh": "Z2xiX2Jhc2U2NA==",
            "image": "aW1hZ2VfYjY0",
        })
        assert isinstance(req, TextureMeshRequest)
        assert req.has_reference is True
        assert req.type == "texture_mesh"

    def test_texture_mesh_with_prompt_parses(self):
        req = _job_adapter.validate_python({
            "type": "texture_mesh",
            "mesh": "Z2xiX2Jhc2U2NA==",
            "prompt": "weathered bronze",
        })
        assert isinstance(req, TextureMeshRequest)
        assert req.has_reference is True

    def test_texture_mesh_without_reference_is_constructible_but_invalid_for_dispatch(self):
        # The schema allows the constructor without image/prompt (both are
        # Optional) so the manager can return a clean 422-like error explaining
        # what's missing instead of a Pydantic validation error at the boundary.
        req = TextureMeshRequest(mesh="Z2xiX2Jhc2U2NA==")
        assert req.has_reference is False

    def test_texture_mesh_requires_mesh(self):
        import pytest as _pt
        with _pt.raises(ValidationError):
            TextureMeshRequest(image="aW1hZ2VfYjY0")

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            _job_adapter.validate_python({
                "type": "voice_to_3d",
                "prompt": "x",
            })

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            _job_adapter.validate_python({"type": "text_to_3d"})

    def test_image_to_3d_requires_image(self):
        with pytest.raises(ValidationError):
            _job_adapter.validate_python({"type": "image_to_3d"})


# ---------------------------------------------------------------------------
# JobStatus enum
# ---------------------------------------------------------------------------

class TestJobStatus:
    def test_status_values(self):
        assert JobStatus.QUEUED.value == "queued"
        assert JobStatus.PROCESSING.value == "processing"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.CANCELLED.value == "cancelled"

    def test_status_is_string_enum(self):
        # Used directly in JSON responses; must serialize as plain string.
        assert JobStatus.QUEUED == "queued"


# ---------------------------------------------------------------------------
# JobResponse
# ---------------------------------------------------------------------------

class TestJobResponse:
    def test_minimal(self):
        resp = JobResponse(
            uid="abc",
            status=JobStatus.QUEUED,
            created_at="2025-01-01T00:00:00",
        )
        assert resp.uid == "abc"
        assert resp.status == JobStatus.QUEUED
        assert resp.completed_at is None
        assert resp.error is None
        assert resp.file_path is None

    def test_full_response(self):
        resp = JobResponse(
            uid="abc",
            status=JobStatus.COMPLETED,
            created_at="2025-01-01T00:00:00",
            completed_at="2025-01-01T00:01:00",
            file_path="/cache/hy3dgen/archeon/abc.glb",
        )
        data = resp.model_dump()
        assert data["status"] == "completed"
        assert data["file_path"].endswith("abc.glb")


# ---------------------------------------------------------------------------
# MeshOpsRequest
# ---------------------------------------------------------------------------

class TestMeshOpsRequest:
    def test_decimate_defaults(self):
        req = MeshOpsRequest(job_uid="abc", action=MeshOpsAction.DECIMATE)
        assert req.action == MeshOpsAction.DECIMATE
        assert req.ratio == 0.5
        assert req.format == "glb"

    def test_custom_ratio(self):
        req = MeshOpsRequest(
            job_uid="abc",
            action=MeshOpsAction.DECIMATE,
            ratio=0.25,
            format="obj",
        )
        assert req.ratio == 0.25
        assert req.format == "obj"

    def test_separate_defaults(self):
        """The new SEPARATE action shares the MeshOpsRequest schema."""
        req = MeshOpsRequest(job_uid="abc", action=MeshOpsAction.SEPARATE)
        # Enum should survive the round-trip and serialise to its value.
        assert req.action == MeshOpsAction.SEPARATE
        # Defaults are tuned for "real" geometry, not micro-floaters.
        assert req.min_face_count == 500
        assert req.only_watertight is False
        assert req.repair is True
        assert req.min_volume_ratio == 0.0

    def test_separate_accepts_string_action(self):
        """HTTP clients send the enum as a plain string."""
        req = MeshOpsRequest(job_uid="abc", action="separate")
        assert req.action == MeshOpsAction.SEPARATE

    def test_separate_custom_tuning(self):
        req = MeshOpsRequest(
            job_uid="abc",
            action=MeshOpsAction.SEPARATE,
            min_face_count=2000,
            only_watertight=True,
            repair=False,
            min_volume_ratio=0.01,
            format="obj",
        )
        assert req.min_face_count == 2000
        assert req.only_watertight is True
        assert req.repair is False
        assert req.min_volume_ratio == 0.01
        assert req.format == "obj"

    def test_separate_validates_min_face_count(self):
        with pytest.raises(ValidationError):
            MeshOpsRequest(job_uid="abc", action="separate", min_face_count=0)

    def test_separate_validates_min_volume_ratio(self):
        with pytest.raises(ValidationError):
            MeshOpsRequest(job_uid="abc", action="separate", min_volume_ratio=1.5)

    def test_separate_serialises_to_string_action(self):
        """``use_enum_values=True`` means model_dump yields the string."""
        req = MeshOpsRequest(job_uid="abc", action=MeshOpsAction.SEPARATE)
        assert req.model_dump()["action"] == "separate"

    def test_action_enum_has_separate(self):
        assert MeshOpsAction.SEPARATE.value == "separate"
        assert "separate" in {a.value for a in MeshOpsAction}
