# -*- mode: python ; coding: utf-8 -*-

from importlib.util import find_spec
from pathlib import Path


def package_directory(name):
    origin = find_spec(name).origin
    if not origin or origin == 'built-in':
        raise RuntimeError(f'Could not locate package {name!r} for packaging.')
    return Path(origin).resolve().parent


flet_web_directory = package_directory('flet_web')
version_file = Path(__file__).resolve().parent / 'packaging' / 'windows_version_info.txt'
runtime_binaries = []
for package_name in ('numpy', 'scipy', 'pandas', 'pyarrow'):
    directory = package_directory(package_name).parent / f'{package_name}.libs'
    runtime_binaries.extend((str(path), '.') for path in directory.glob('*.dll'))


a = Analysis(
    ['src\\etf_cockpit\\main.py'],
    pathex=['src', str(flet_web_directory.parent)],
    binaries=runtime_binaries,
    datas=[('configs', 'configs'), ('models/lightgbm', 'models/lightgbm'), ('models/cached', 'models/cached'), (str(flet_web_directory), 'flet_web')],
    hiddenimports=['flet_web', 'flet_web.patch_index', 'flet_web.uploads', 'flet_web.fastapi', 'flet_web.fastapi.app', 'flet_web.fastapi.flet_app', 'flet_web.fastapi.flet_app_manager', 'flet_web.fastapi.flet_fastapi', 'flet_web.fastapi.flet_oauth', 'flet_web.fastapi.oauth_state', 'flet_web.fastapi.serve_fastapi_web_app', 'fastapi', 'fastapi.staticfiles', 'starlette', 'starlette.middleware.base', 'uvicorn', 'uvicorn.loops.auto', 'uvicorn.lifespan.on', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.websockets_sansio_impl', 'yfinance', 'curl_cffi', 'bs4', 'peewee', 'multitasking', 'platformdirs', 'pandas._libs._cyutility'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'transformers', 'timesfm', 'toto2', 'tensorflow', 'onnxruntime', 'torchaudio', 'torchvision', 'gluonts', 'einops', 'jaxtyping', 'accelerate', 'flet_desktop'],
    noarchive=False,
    optimize=0,
)
# This release runs Flet's local web view. The desktop client payload is not
# used by that mode and its generated font tree is a known PyInstaller copy
# race on Windows; keep the web package deterministic by excluding it from
# the collected payload as well as from module analysis above.
a.datas = [entry for entry in a.datas if 'flet_desktop' not in str(entry[0]).lower() and 'flet_desktop' not in str(entry[1]).lower()]
a.binaries = [entry for entry in a.binaries if 'flet_desktop' not in str(entry[0]).lower() and 'flet_desktop' not in str(entry[1]).lower()]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ETF_AI_Cockpit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(version_file),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ETF_AI_Cockpit',
)
