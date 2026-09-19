"""Identidade do produto e modulos compilados no build Cython."""

VERSION = "1.2.1"
NATIVE_MODULES = {
    "desktop_native": "desktop.py",
    "desktop_api": "desktop_api.py",
    "extrator_desligamentos": "extrator_desligamentos.py",
    "extrator_negacao": "extrator_negacao.py",
    "localizador_programacao": "localizador_programacao.py",
    "runtime_config": "runtime_config.py",
}


def version_info(filename):
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )

    number = (*map(int, VERSION.split(".")), 0)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=number, prodvers=number, mask=0x3F,
                          flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("041604B0", [
                StringStruct("FileDescription", "Extrator SGD - Consultas e relatorios"),
                StringStruct("FileVersion", VERSION),
                StringStruct("ProductName", "Extrator SGD"),
                StringStruct("ProductVersion", VERSION),
                StringStruct("OriginalFilename", filename),
                StringStruct("InternalName", filename.removesuffix(".exe")),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
        ],
    )
