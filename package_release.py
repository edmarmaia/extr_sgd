"""Valida e empacota a distribuicao desktop Cython."""

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile

from build_support import NATIVE_MODULES, VERSION

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "dist" / "Extrator_SGD"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_environment():
    if (sys.platform != "win32" or sys.version_info[:2] != (3, 12)
            or struct.calcsize("P") != 8 or sys.prefix == sys.base_prefix):
        raise RuntimeError("Use o ambiente isolado .venv-build com CPython 3.12 x64 no Windows.")
    normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
    expected = {}
    for line in (ROOT / "requirements-build.lock").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==")
            expected[normalize(name)] = version
    installed = {normalize(dist.metadata["Name"]): dist.version for dist in metadata.distributions()}
    if expected != installed:
        differences = {name: {"expected": expected.get(name), "installed": installed.get(name)}
                       for name in expected.keys() | installed.keys()
                       if expected.get(name) != installed.get(name)}
        raise RuntimeError(f"Ambiente diverge do lock; revise/recrie .venv-build: {differences}")
    return dict(sorted(installed.items()))


def validate_payload(bundle):
    from PyInstaller.archive.readers import CArchiveReader

    exe = bundle / "Extrator_SGD.exe"
    internal = bundle / "_internal"
    config = bundle / "Extrator_SGD.exe.config"
    local_config = bundle / "config.local.json"
    if (not exe.is_file() or not config.is_file() or not local_config.is_file()
            or not (internal / "frontend/dist/index.html").is_file()):
        raise RuntimeError("Distribuicao incompleta: EXE, configuracao ou frontend ausente.")
    runtime = internal / "pythonnet" / "runtime"
    for name in ("Python.Runtime.dll", "Python.Runtime.deps.json", "netstandard.dll"):
        if not (runtime / name).is_file():
            raise RuntimeError(f"Runtime .NET incompleto: pythonnet/runtime/{name} ausente.")
    for name in NATIVE_MODULES:
        if len(list(internal.glob(f"{name}*.pyd"))) != 1:
            raise RuntimeError(f"Modulo nativo ausente ou ambiguo: {name}")

    # Valida o executavel gerado, nao apenas a configuracao do spec.
    archive = CArchiveReader(str(exe))
    if any(entry[-1] == "b" for entry in archive.toc.values()):
        raise RuntimeError("EXE contem binarios para extracao; esperado build onedir.")
    pyz = archive.open_embedded_archive("PYZ.pyz")
    protected = set(NATIVE_MODULES) | {"desktop", "build_support", "package_release"}
    if protected.intersection(pyz.toc):
        raise RuntimeError("Implementacao Python propria encontrada no EXE em vez de Cython.")
    if any(name.split(".")[0] in {"Cython", "pyximport"} for name in pyz.toc):
        raise RuntimeError("Compilador Cython encontrado na entrega; somente os modulos compilados sao necessarios.")

    forbidden = {"node_modules", ".git", ".venv-build", ".pytest_cache"}
    for path in bundle.rglob("*"):
        relative = path.relative_to(bundle)
        if path.is_symlink() or forbidden.intersection(relative.parts):
            raise RuntimeError(f"Conteudo nao permitido na entrega: {relative}")
        if path.is_file() and path.suffix.lower() in {".py", ".pyc", ".c", ".cpp"}:
            if path.name.split(".")[0] in protected:
                raise RuntimeError(f"Fonte/bytecode proprio encontrado na entrega: {relative}")
    return exe


def package(signed=False):
    dependencies = check_environment()
    exe = validate_payload(BUNDLE)
    (BUNDLE / "LEIA-ME.txt").write_text(
        (ROOT / "DISTRIBUTION.md").read_text(encoding="utf-8"), encoding="utf-8")
    source_files = ["build_cython.ps1", "build_support.py", "setup_cython.py",
                    "package_release.py", "cython_launcher.py", "Extrator_SGD_Cython.spec",
                    "requirements-build.lock", "frontend/package-lock.json", "frontend/package.json",
                    "frontend/index.html", "frontend/vite.config.ts", "frontend/tsconfig.json",
                    "icon.ico", "Extrator_SGD.exe.config", "DISTRIBUTION.md",
                    *NATIVE_MODULES.values()]
    source_files += [path.relative_to(ROOT).as_posix()
                     for path in sorted((ROOT / "frontend/src").rglob("*")) if path.is_file()]
    info = {
        "product": "Extrator SGD", "version": VERSION,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "format": "cython-onedir", "upx": False,
        "application_signature": "signed-with-timestamp" if signed else "unsigned",
        "python": platform.python_version(), "architecture": platform.machine(),
        "node": subprocess.check_output(["node", "--version"], text=True).strip(),
        "npm": subprocess.check_output(["npm.cmd", "--version"], text=True).strip(),
        "dependencies": dependencies,
        "source_sha256": {name: sha256(ROOT / name) for name in sorted(source_files)},
        "exe_sha256": sha256(exe),
    }
    (BUNDLE / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    # O manifesto cobre todos os arquivos do pacote, exceto ele proprio.
    manifest = BUNDLE / "SHA256SUMS.txt"
    files = sorted(path for path in BUNDLE.rglob("*") if path.is_file() and path != manifest)
    manifest.write_text("".join(f"{sha256(path)}  {path.relative_to(BUNDLE).as_posix()}\n"
                                for path in files), encoding="utf-8")

    zip_path = BUNDLE.parent / f"Extrator_SGD-{VERSION}-windows-x64.zip"
    temporary = zip_path.with_suffix(".zip.tmp")
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for path in [*files, manifest]:
                archive.write(path, path.relative_to(BUNDLE.parent).as_posix())
        with ZipFile(temporary) as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError(f"Falha de integridade no ZIP: {bad}")
        temporary.replace(zip_path)
    finally:
        temporary.unlink(missing_ok=True)
    checksum = zip_path.with_suffix(".zip.sha256")
    checksum.write_text(f"{sha256(zip_path)}  {zip_path.name}\n", encoding="utf-8")
    print(f"ZIP: {zip_path}\nSHA-256: {checksum}\nArquivos: {len(files) + 1}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-environment", action="store_true")
    parser.add_argument("--signed", action="store_true",
                        help="Usado pelo build somente apos validar assinatura e timestamp.")
    args = parser.parse_args()
    if args.check_environment:
        check_environment()
        print("Ambiente isolado corresponde ao requirements-build.lock.")
    else:
        package(signed=args.signed)
