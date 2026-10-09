"""Opt-in loader for the project's ``.env`` file.

Library callers and tests get hermetic settings by default: nothing in
this package reads the project ``.env`` until the entry point explicitly
opts in. The CLI, the FastAPI server and the launcher all call
``hy3dgen.env.bootstrap()`` before importing the ``Settings`` class, so
production deployments keep their project ``.env`` while a stray file
in a developer's working directory cannot leak values into
``Settings()`` and break hermetic assertions.

The flag used to gate this is ``POLYFORGE_LOAD_DOTENV`` (``"1"`` enables,
``"0"`` disables). Setting it to ``"1"`` is a no-op when the file is
absent.
"""

from __future__ import annotations

import os
from pathlib import Path


def bootstrap(env_file: str | os.PathLike[str] = ".env", *, override: bool = False) -> bool:
    """Enable ``.env`` loading for the current process.

    Idempotent: subsequent calls are no-ops unless ``override=True`` is
    passed. Returns ``True`` when a ``.env`` file was found and the flag
    is on, ``False`` otherwise.
    """
    flag = os.environ.get("POLYFORGE_LOAD_DOTENV", "0")
    if override or flag == "0":
        path = Path(env_file)
        if path.is_file():
            os.environ["POLYFORGE_LOAD_DOTENV"] = "1"
            return True
        os.environ["POLYFORGE_LOAD_DOTENV"] = "0"
        return False
    return flag == "1" and Path(env_file).is_file()


def is_loaded() -> bool:
    """Whether ``Settings()`` will read the project ``.env`` file."""
    return os.environ.get("POLYFORGE_LOAD_DOTENV") == "1"
