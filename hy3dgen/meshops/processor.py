from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import trimesh

logger = logging.getLogger(__name__)


class MeshProcessor:
    def __init__(self):
        pass

    def load_mesh(self, file_path: str) -> trimesh.Trimesh:
        import trimesh

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Mesh file not found: {file_path}")

        try:
            # Force 'mesh' to avoid getting a Scene object for single GLBs
            mesh = trimesh.load(file_path, force="mesh")
            return mesh
        except Exception as e:
            logger.error(f"Failed to load mesh {file_path}: {e}")
            raise e

    def decimate(self, mesh: trimesh.Trimesh, ratio: float) -> trimesh.Trimesh:
        """
        Reduce polygon count.
        ratio: 0.1 to 1.0 (target fraction of faces).
        """
        if ratio >= 1.0 or ratio <= 0.0:
            return mesh

        target_faces = int(len(mesh.faces) * ratio)
        logger.info(f"Decimating mesh from {len(mesh.faces)} to {target_faces} faces")

        try:
            # simplify_quadratic_decimation is the best balance
            simplified = mesh.simplify_quadric_decimation(face_count=target_faces)
            return simplified
        except Exception as e:
            logger.warning(f"Decimation failed: {e}")
            raise e

    def separate_parts(
        self,
        mesh: trimesh.Trimesh,
        min_face_count: int = 500,
        only_watertight: bool = False,
        repair: bool = True,
        min_volume_ratio: float = 0.0,
    ) -> trimesh.Scene:
        """Split a mesh into named parts using face-adjacency connectivity.

        Each connected component becomes a node in the returned
        ``trimesh.Scene`` so consumers (Blender, ``<model-viewer>``,
        three.js) can manipulate individual parts. Mirrors the
        "Auto-Separate Parts" feature shipped by Meshy/Hi3D.

        Parameters
        ----------
        mesh:
            Source mesh. ``trimesh.Trimesh.split`` already merges
            repeated face assignments before checking, which means
            duplicated faces (a common artifact of marching-cubes
            reconstruction) do not create spurious extra components.
        min_face_count:
            Discard components with fewer faces than this. Filters
            marching-cubes noise without dropping small but real parts.
        only_watertight:
            If True, keep only watertight components (recommended for
            3D-printing workflows). Internally forwarded to
            ``trimesh.Trimesh.split``.
        repair:
            If True, attempt to close small holes in each component
            before the watertight check.
        min_volume_ratio:
            After splitting, drop components whose volume is smaller
            than this fraction of the largest component. ``0`` keeps
            every surviving component. Useful for shedding long-thin
            floating triangles that survive the face-count filter.

        Returns
        -------
        trimesh.Scene
            A scene where each part is an independently selectable
            node. Node names follow the pattern
            ``part_{index:03d}_{face_count}f`` so the UI can use them
            as identifiers when listing parts.
        """
        import trimesh

        # ``split`` returns a list of Trimesh objects, one per
        # connected component. ``only_watertight`` and ``repair`` are
        # forwarded as-is. trimesh's connectivity math needs at least
        # one well-formed triangle; for degenerate inputs we short
        # circuit and return the mesh as the single part.
        if len(mesh.faces) < 1:
            scene = trimesh.Scene()
            scene.add_geometry(
                mesh, node_name="part_000_empty", geom_name="part_000_empty"
            )
            logger.warning("separate_parts called on empty mesh; returning single node")
            return scene

        try:
            parts = mesh.split(
                only_watertight=only_watertight,
                repair=repair,
            )
        except TypeError:
            # Older trimesh versions do not expose ``repair``/``only_watertight``
            # kw-args; fall back to the bare call so the feature degrades
            # gracefully on pinned environments.
            parts = mesh.split()
        except Exception as e:
            # trimesh's graph code raises on malformed inputs; fall back
            # to a single-node scene rather than 500ing the request.
            logger.warning("split() failed (%s); returning mesh as single part", e)
            parts = [mesh]

        if not parts:
            # Nothing to split (degenerate mesh). Wrap the input as the
            # only part so callers always get a valid Scene back.
            parts = [mesh]

        if min_face_count > 1:
            parts = [p for p in parts if len(p.faces) >= min_face_count]
            if not parts:
                # All components were below the threshold; relax the
                # filter and keep at least the largest one so the
                # operation does not silently produce an empty file.
                sorted_parts = sorted(mesh.split(), key=lambda p: len(p.faces), reverse=True)
                parts = [sorted_parts[0]] if sorted_parts else [mesh]

        # Volume-based filter (post-split).
        if min_volume_ratio > 0 and len(parts) > 1:
            try:
                volumes = [abs(p.volume) for p in parts]
                max_volume = max(volumes)
                if max_volume > 0:
                    threshold = max_volume * min_volume_ratio
                    parts = [
                        p for p, v in zip(parts, volumes, strict=False)
                        if v >= threshold
                    ]
            except Exception as e:  # pragma: no cover - volume calc rarely fails
                logger.warning("Volume-based filter skipped: %s", e)

        # Sort by descending face count so node names are deterministic
        # regardless of the order returned by ``trimesh.split``.
        parts.sort(key=lambda p: len(p.faces), reverse=True)

        scene = trimesh.Scene()
        for idx, part in enumerate(parts):
            name = f"part_{idx:03d}_{len(part.faces)}f"
            scene.add_geometry(part, node_name=name, geom_name=name)

        logger.info(
            "Separated mesh into %d parts (min_face_count=%d, only_watertight=%s, repair=%s)",
            len(parts),
            min_face_count,
            only_watertight,
            repair,
        )
        return scene

    def process(self, input_path: str, output_path: str, action: str, params: dict) -> str:
        """
        Load, process, and save mesh.
        """
        mesh = self.load_mesh(input_path)

        if action == "decimate":
            ratio = params.get("ratio", 0.5)
            mesh = self.decimate(mesh, ratio)
        elif action == "convert":
            pass  # Just loading and saving converts format based on extension
        elif action == "separate":
            scene = self.separate_parts(
                mesh,
                min_face_count=params.get("min_face_count", 500),
                only_watertight=params.get("only_watertight", False),
                repair=params.get("repair", True),
                min_volume_ratio=params.get("min_volume_ratio", 0.0),
            )
            # ``Scene.export`` honours the file extension the same way as
            # ``Trimesh.export``, so ``.glb`` writes a multi-body GLB.
            scene.export(output_path)
            logger.info("Saved separated mesh to %s", output_path)
            return output_path

        # Export
        # Trimesh exports based on file extension
        mesh.export(output_path)
        logger.info(f"Saved processed mesh to {output_path}")
        return output_path
