"""PyInstaller spec for the engine sidecar.

onedir rather than onefile: onefile re-extracts itself to a temporary directory on every
launch, which is slow and leaves debris behind. onedir also lets each nested Mach-O
binary be signed individually, which is what notarization requires.
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "tessera" / "engine.py")],
    pathex=[str(ROOT)],
    # Alembic loads migration scripts from disk at runtime, so they travel as data
    # rather than being importable modules. tessera.engine.migrations_directory finds
    # them under sys._MEIPASS once frozen.
    # Templates are read from disk at render time, exactly like the migrations above, so
    # they travel the same way. Miss this and the console works in development and serves
    # a stack trace from the .dmg — which is why smoke-test.sh fetches a console page.
    datas=[
        (str(ROOT / "tessera" / "repository" / "migrations"), "repository/migrations"),
        (str(ROOT / "tessera" / "templates"), "templates"),
    ],
    # Every one of these is imported by a string at runtime, which static analysis
    # cannot see. Without them the frozen engine builds cleanly and dies on launch with
    # ModuleNotFoundError — the most common way a PyInstaller build fails.
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "alembic.autogenerate",
        "alembic.ddl.sqlite",
        "sqlalchemy.dialects.sqlite",
    ],
    hookspath=[],
    excludes=["tkinter", "matplotlib", "PIL", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="tessera-engine",
    console=True,
    strip=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="tessera-engine",
)
