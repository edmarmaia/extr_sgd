# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from runpy import run_path
from shutil import copy2


root = Path(SPECPATH)
native = root / 'build' / 'cython' / 'lib'
support = run_path(str(root / 'build_support.py'))
module_names = support['NATIVE_MODULES']

if not (root / 'frontend' / 'dist' / 'index.html').is_file():
    raise RuntimeError('Compile frontend antes: npm ci e npm run build.')
if not (root / 'config.local.json').is_file():
    raise RuntimeError('Crie config.local.json a partir de config.example.json.')

native_binaries = []
for module_name in module_names:
    matches = list(native.glob(f'{module_name}*.pyd'))
    if len(matches) != 1:
        raise RuntimeError(f'Modulo Cython ausente ou ambiguo: {module_name}: {matches}')
    native_binaries.append((str(matches[0]), '.'))

a = Analysis(
    [str(root / 'cython_launcher.py')],
    pathex=[str(native)],
    binaries=native_binaries,
    datas=[(str(root / 'frontend' / 'dist'), 'frontend/dist'),
           (str(root / 'icon.ico'), '.')],
    hiddenimports=[
        'webview', 'webview.platforms.edgechromium', 'webview.platforms.winforms',
        'requests', 'bs4', 'pandas', 'openpyxl', 'xlrd', 'lxml.html',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[
        'desktop', 'build_support', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3',
        'IPython', 'matplotlib', 'sqlalchemy', 'pytest',
        'Cython', 'pyximport',
    ],
    noarchive=False,
)
# Os imports Cython nao sao detectados pelo Analysis; os binarios sao incluidos acima.
leaked = set(module_names).intersection(item[0] for item in a.pure)
if leaked:
    raise RuntimeError(f'Modulos proprios encontrados como bytecode: {sorted(leaked)}')
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='Extrator_SGD', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    contents_directory='_internal',
    version=support['version_info']('Extrator_SGD.exe'),
    icon=str(root / 'icon.ico'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Extrator_SGD')
copy2(root / 'Extrator_SGD.exe.config', Path(DISTPATH) / 'Extrator_SGD')
copy2(root / 'config.local.json', Path(DISTPATH) / 'Extrator_SGD')
