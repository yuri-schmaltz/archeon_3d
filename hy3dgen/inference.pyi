from typing import Any

class ModelWorker:
    def __init__(
        self,
        model_path: str = ...,
        tex_model_path: str = ...,
        subfolder: str = ...,
        device: str = ...,
        enable_tex: bool = ...,
        enable_t2i: bool = ...,
        multiview_model_path: str = ...,
        multiview_subfolder: str = ...,
    ) -> None: ...
    def generate(self, uid: str, params: dict[str, Any], save_dir: str) -> str: ...
