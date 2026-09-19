"""Compila os modulos da aplicacao como extensoes Cython."""

from Cython.Build import cythonize
from setuptools import Extension, setup
from build_support import NATIVE_MODULES, VERSION

extensions = [
    Extension(name, [source])
    for name, source in NATIVE_MODULES.items()
]

setup(
    name="extrator-sgd-native",
    version=VERSION,
    ext_modules=cythonize(
        extensions,
        build_dir="build/cython/generated",
        compiler_directives={
            "language_level": 3,
            "binding": True,
            "embedsignature": False,
            "emit_code_comments": False,
        },
        annotate=False,
    ),
)
