"""Package discovery and opt-in native extensions; metadata lives in pyproject.toml."""

import os

from setuptools import Extension, find_namespace_packages, setup


def native_extensions():
    if os.environ.get("ARCHEON_BUILD_NATIVE") != "1":
        return [], {}
    import pybind11
    from torch.utils.cpp_extension import BuildExtension, CUDAExtension

    rasterizer = "hy3dgen/texgen/custom_rasterizer/lib/custom_rasterizer_kernel"
    return [
        CUDAExtension(
            "custom_rasterizer_kernel",
            [
                f"{rasterizer}/{name}"
                for name in ("rasterizer.cpp", "grid_neighbor.cpp", "rasterizer_gpu.cu")
            ],
        ),
        Extension(
            "mesh_processor",
            ["hy3dgen/texgen/differentiable_renderer/mesh_processor.cpp"],
            include_dirs=[pybind11.get_include()],
            language="c++",
            extra_compile_args=["/std:c++14"] if os.name == "nt" else ["-std=c++14"],
        ),
    ], {"build_ext": BuildExtension}


ext_modules, cmdclass = native_extensions()
setup(
    packages=[*find_namespace_packages(include=["hy3dgen*"]), "custom_rasterizer"],
    package_dir={"custom_rasterizer": "hy3dgen/texgen/custom_rasterizer/custom_rasterizer"},
    ext_modules=ext_modules,
    cmdclass=cmdclass,
)
