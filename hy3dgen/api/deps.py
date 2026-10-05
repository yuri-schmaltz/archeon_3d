from typing import cast

from fastapi import Request

from hy3dgen.api.manager import PriorityRequestManager
from hy3dgen.meshops.processor import MeshProcessor


async def get_manager(request: Request) -> PriorityRequestManager:
    """Dependency to retrieve the PriorityRequestManager instance."""
    return cast("PriorityRequestManager", request.app.state.manager)


def get_mesh_processor(request: Request) -> MeshProcessor:
    return cast("MeshProcessor", request.app.state.mesh_processor)
