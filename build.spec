# -*- mode: python ; coding: utf-8 -*-
import certifi
import os

block_cipher = None

# Get certifi CA bundle path
certifi_path = os.path.dirname(certifi.where())

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('stravagonuts/templates', 'stravagonuts/templates'),
        ('stravagonuts/static', 'stravagonuts/static'),
        (certifi.where(), 'certifi'),
    ],
    hiddenimports=[
        'certifi',
        'pip_system_certs',
        'pip_system_certs.wrapt_requests',
        'shapely.geometry',
        'geopandas',
        'folium',
        'openpyxl',
        'contextily',
        'shapely',
        'fiona',
        'pyproj',
        'rtree',
        'rasterio',
        'rasterio._shim',
        'rasterio.sample',
        'rasterio.vrt',
        'rasterio._err',
        'rasterio.control',
        'rasterio.crs',
        'rasterio.dtypes',
        'rasterio.enums',
        'rasterio.errors',
        'rasterio.features',
        'rasterio.fill',
        'rasterio.mask',
        'rasterio.merge',
        'rasterio.plot',
        'rasterio.profiles',
        'rasterio.transform',
        'rasterio.warp',
        'rasterio.windows',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='StravaGoNuts',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Show console for progress messages
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None  # TODO: Add icon file if desired
)
