"""Valida o ZIP e abre a entrega Cython extraida sem executar consultas."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_support import VERSION
from package_release import ROOT, sha256, validate_payload


def main():
    zip_path = ROOT / "dist" / f"Extrator_SGD-{VERSION}-windows-x64.zip"
    checksum, filename = zip_path.with_suffix(".zip.sha256").read_text().strip().split("  ", 1)
    if filename != zip_path.name or sha256(zip_path) != checksum:
        raise AssertionError("ZIP does not match its SHA-256 file.")

    with tempfile.TemporaryDirectory(prefix="sgd-release-", dir=ROOT / "build") as temporary:
        with ZipFile(zip_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise AssertionError("Duplicate ZIP entries.")
            for name in names:
                path = PurePosixPath(name)
                if (path.is_absolute() or ".." in path.parts or "\\" in name
                        or ":" in name or path.parts[0] != "Extrator_SGD"):
                    raise AssertionError(f"Unexpected ZIP entry: {name}")
            manifest_name = "Extrator_SGD/SHA256SUMS.txt"
            manifest = archive.read(manifest_name).decode("utf-8").splitlines()
            covered = set()
            for line in manifest:
                expected, relative = line.split("  ", 1)
                name = f"Extrator_SGD/{relative}"
                if name in covered:
                    raise AssertionError(f"Duplicate manifest entry: {name}")
                with archive.open(name) as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != expected:
                    raise AssertionError(f"Payload hash mismatch: {name}")
                covered.add(name)
            if covered != set(names) - {manifest_name}:
                raise AssertionError("Manifest does not cover the entire payload.")
            archive.extractall(temporary)

        bundle = Path(temporary) / "Extrator_SGD"
        exe = validate_payload(bundle)
        info = json.loads((bundle / "build-info.json").read_text(encoding="utf-8"))
        if info["exe_sha256"] != sha256(exe) or info["version"] != VERSION:
            raise AssertionError("Build identity does not match the executable.")
        # Confere o cabecalho PE e os recursos de versao do executavel.
        import pefile
        with pefile.PE(str(exe), fast_load=False) as pe:
            if pe.FILE_HEADER.Machine != 0x8664:
                raise AssertionError("Expected x64 executable.")
            strings = {key: value for group in pe.FileInfo for entry in group
                       for table in getattr(entry, "StringTable", [])
                       for key, value in table.entries.items()}
            if strings.get(b"ProductVersion") != VERSION.encode("ascii"):
                raise AssertionError("Windows version resource does not match the release.")
            security = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4]
            if info["application_signature"] == "unsigned" and security.Size:
                raise AssertionError("Unsigned release unexpectedly contains a signature table.")

        subprocess.run([
            "powershell.exe", "-NoProfile", "-File", str(ROOT / "tests/smoke_packaged.ps1"),
            "-Exe", str(exe),
        ], check=True)
    print(f"PASS: {len(names)} ZIP files; SHA-256 manifest, x64 PE, version and extracted app.")
    print(f"ZIP: {zip_path.name} ({zip_path.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
