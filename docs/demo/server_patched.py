"""Same as hy3dgen.api.server but with the worker disabled (idle loop).

Listens on POLYFORGE_PORT (default 8765). Used by the demo and the
stress-test suite (which override POLYFORGE_PORT to avoid clashing with
the real backend).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import hy3dgen.api.manager as _mgr
import asyncio

async def _idle(self):
    while True:
        await asyncio.sleep(3600)

_mgr.PriorityRequestManager._process_queue = _idle

from hy3dgen.api.server import app

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("POLYFORGE_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
