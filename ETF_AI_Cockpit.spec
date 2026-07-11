# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\etf_cockpit\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('configs', 'configs'), ('models/lightgbm', 'models/lightgbm'), ('models/cached', 'models/cached'), ('.venv/Lib/site-packages/flet_web/web', 'flet_web/web')],
    hiddenimports=['flet_web', 'flet_web.patch_index', 'flet_web.uploads', 'flet_web.fastapi', 'flet_web.fastapi.app', 'flet_web.fastapi.flet_app', 'flet_web.fastapi.flet_app_manager', 'flet_web.fastapi.flet_fastapi', 'flet_web.fastapi.flet_oauth', 'flet_web.fastapi.oauth_state', 'flet_web.fastapi.serve_fastapi_web_app', 'fastapi', 'fastapi.staticfiles', 'starlette', 'starlette.middleware.base', 'uvicorn', 'uvicorn.loops.auto', 'uvicorn.lifespan.on', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.websockets_sansio_impl', 'yfinance', 'curl_cffi', 'bs4', 'peewee', 'multitasking', 'platformdirs'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
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
    version='C:\\Users\\thor2\\AppData\\Local\\Temp\\71b070ff-2d64-4fdc-95cc-c3541792ead2',
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
