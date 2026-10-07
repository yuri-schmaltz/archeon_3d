from typing import Any

DEFAULT_T2I_MODEL: str

class ModelWorker:
    def __init__(
        self,
        model_path: str = ...,
        tex_model_path: str = ...,
        subfolder: str = ...,
        device: str = ...,
        enable_tex: bool = ...,
        enable_t2i: bool = ...,
        t2i_model_path: str | None = ...,
        multiview_model_path: str = ...,
        multiview_subfolder: str = ...,
    ) -> None: ...
    def generate(self, uid: str, params: dict[str, Any], save_dir: str) -> str: ...

def worker_model_state(worker: Any, defaults: dict[str, Any] | None = ...) -> dict[str, Any]: ...
def model_capability_snapshot(state: dict[str, Any]) -> dict[str, Any]: ...
