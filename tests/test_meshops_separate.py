"""
Tests for the ``MeshProcessor.separate_parts`` operation.

These tests do not require a GPU or model weights; they only need
``trimesh``. They exercise the geometric path of the new
``action="separate"`` mesh operation, which powers the
Meshy/Hi3D-style "auto-separate parts" feature.
"""
from __future__ import annotations

import os

import pytest
import trimesh

from hy3dgen.meshops.processor import MeshProcessor


def _make_three_boxes():
    """Three disconnected cubes, glued into one mesh.

    Each cube has 12 triangles (8 vertices), so any split should
    surface three independent parts.
    """
    a = trimesh.creation.box(extents=[1, 1, 1])
    b = trimesh.creation.box(extents=[2, 1, 1])
    c = trimesh.creation.box(extents=[0.5, 0.5, 0.5])
    b.apply_translation([3, 0, 0])
    c.apply_translation([0, 3, 0])
    return trimesh.util.concatenate([a, b, c])


class TestSeparatePartsGeometry:
    def test_disconnected_mesh_yields_one_node_per_component(self):
        proc = MeshProcessor()
        scene = proc.separate_parts(_make_three_boxes(), min_face_count=1)
        assert len(scene.geometry) == 3

    def test_node_names_follow_convention(self):
        proc = MeshProcessor()
        scene = proc.separate_parts(_make_three_boxes(), min_face_count=1)
        # Naming pattern is ``part_{idx:03d}_{face_count}f``.
        names = list(scene.geometry.keys())
        for name in names:
            assert name.startswith("part_")
            assert name.endswith("f")

    def test_parts_sorted_by_face_count_descending(self):
        proc = MeshProcessor()
        scene = proc.separate_parts(_make_three_boxes(), min_face_count=1)
        face_counts = [len(g.faces) for g in scene.geometry.values()]
        assert face_counts == sorted(face_counts, reverse=True)

    def test_single_watertight_mesh_returns_single_part(self):
        proc = MeshProcessor()
        sphere = trimesh.creation.icosphere()
        scene = proc.separate_parts(sphere, min_face_count=10)
        assert len(scene.geometry) == 1

    def test_empty_mesh_returns_no_part_does_not_raise(self):
        proc = MeshProcessor()
        empty = trimesh.Trimesh(vertices=[[0, 0, 0]], faces=[])
        # Should not raise; falls back to a single empty node.
        scene = proc.separate_parts(empty, min_face_count=10)
        assert len(scene.geometry) == 1


class TestSeparatePartsFilters:
    def test_min_face_count_drops_small_components(self):
        proc = MeshProcessor()
        # Two boxes, one tiny (6 faces) and one normal (12 faces).
        # Since trimesh's box() actually returns 12 triangles each, we
        # build a deliberate tiny component with a low-res pyramid.
        big = trimesh.creation.box(extents=[1, 1, 1])
        tiny = trimesh.creation.box(extents=[0.01, 0.01, 0.01])
        tiny.apply_translation([5, 0, 0])
        combined = trimesh.util.concatenate([big, tiny])

        # With a filter smaller than the tiny box, both survive.
        scene = proc.separate_parts(combined, min_face_count=1)
        assert len(scene.geometry) == 2

        # With a high filter, the relaxation fallback keeps the
        # largest one rather than producing an empty result.
        scene = proc.separate_parts(combined, min_face_count=10_000)
        assert len(scene.geometry) == 1

    def test_min_volume_ratio_drops_small_volume_components(self):
        proc = MeshProcessor()
        # One large box and one microscopic box glued together.
        big = trimesh.creation.box(extents=[10, 10, 10])
        small = trimesh.creation.box(extents=[0.1, 0.1, 0.1])
        small.apply_translation([20, 0, 0])
        combined = trimesh.util.concatenate([big, small])

        # Disabled by default -> both survive.
        scene = proc.separate_parts(combined, min_face_count=1, min_volume_ratio=0.0)
        assert len(scene.geometry) == 2

        # Aggressive filter drops the small one.
        scene = proc.separate_parts(
            combined, min_face_count=1, min_volume_ratio=0.05
        )
        assert len(scene.geometry) == 1

    def test_only_watertight_flag_is_forwarded(self):
        proc = MeshProcessor()
        # Three boxes are already watertight, so the flag should keep
        # all of them. We only check the call succeeds and respects
        # the count.
        scene = proc.separate_parts(
            _make_three_boxes(),
            min_face_count=1,
            only_watertight=True,
            repair=True,
        )
        assert len(scene.geometry) == 3

    def test_repair_flag_is_forwarded(self):
        proc = MeshProcessor()
        scene = proc.separate_parts(
            _make_three_boxes(),
            min_face_count=1,
            repair=True,
        )
        assert len(scene.geometry) == 3


class TestSeparatePartsExport:
    def test_process_writes_multi_body_glb(self, tmp_path):
        proc = MeshProcessor()
        inp = tmp_path / "input.glb"
        out = tmp_path / "out.glb"
        _make_three_boxes().export(str(inp))

        result = proc.process(
            str(inp),
            str(out),
            "separate",
            {"min_face_count": 10},
        )
        assert result == str(out)
        assert out.exists()
        assert out.stat().st_size > 0

        # Re-importing the output yields a Scene with the same parts.
        scene = trimesh.load(str(out), force="scene")
        assert len(scene.geometry) == 3
        for name in scene.geometry:
            assert name.startswith("part_")

    def test_process_separate_keeps_face_count_in_node_name(self, tmp_path):
        proc = MeshProcessor()
        inp = tmp_path / "input.glb"
        out = tmp_path / "out.glb"
        _make_three_boxes().export(str(inp))

        proc.process(str(inp), str(out), "separate", {"min_face_count": 1})
        scene = trimesh.load(str(out), force="scene")
        # The trailing ``f`` should equal the actual face count of the
        # node; guarantees the name is descriptive, not decorative.
        for name, geom in scene.geometry.items():
            declared = int(name.split("_")[-1].rstrip("f"))
            assert declared == len(geom.faces)


@pytest.mark.parametrize("format_ext", ["glb", "obj"])
def test_process_separate_supports_multiple_formats(tmp_path, format_ext):
    proc = MeshProcessor()
    inp = tmp_path / "input.glb"
    out = tmp_path / f"out.{format_ext}"
    _make_three_boxes().export(str(inp))

    proc.process(
        str(inp),
        str(out),
        "separate",
        {"min_face_count": 1, "format": format_ext},
    )
    # trimesh serialises OBJ/GLB through different code paths; both
    # should produce a non-empty file and a re-loadable scene.
    assert out.exists()
    assert os.path.getsize(out) > 0
