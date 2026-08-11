"""Guards on the repository's own shape.

These are not placeholder tests. Each one protects a decision that is cheap to hold now
and expensive to restore once violated — the layer boundaries especially, which erode
one convenient import at a time.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

LAYERS = [
    "tessera.domain",
    "tessera.solver",
    "tessera.repository",
    "tessera.api",
    "tessera.export",
    "tessera.importers",
    "tessera.cli",
]


@pytest.mark.parametrize("module_name", LAYERS)
def test_every_layer_imports(module_name):
    """Each architectural layer exists and is importable on its own."""
    assert importlib.import_module(module_name) is not None


@pytest.mark.parametrize("module_name", LAYERS)
def test_every_layer_documents_itself(module_name):
    """A layer whose purpose is not written down gets used for the wrong thing."""
    module = importlib.import_module(module_name)
    assert module.__doc__, f"{module_name} has no docstring explaining what belongs in it"


def test_version_is_single_sourced():
    """The package version and pyproject must not be able to disagree."""
    import tessera

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert tessera.__version__ == pyproject["project"]["version"]


def test_domain_imports_no_frameworks():
    """A second line of defence behind import-linter.

    import-linter reads the import graph statically; this asserts the same rule at
    runtime. Belt and braces, because this is the boundary the whole architecture
    rests on (ADR-003).
    """
    import tessera.domain

    source_files = list(Path(tessera.domain.__file__).parent.rglob("*.py"))
    banned = ("fastapi", "sqlalchemy", "ortools", "starlette", "reportlab")

    offenders = [
        (path.relative_to(REPO_ROOT), name)
        for path in source_files
        for name in banned
        if f"import {name}" in path.read_text()
    ]
    assert not offenders, f"domain must stay framework-free, found: {offenders}"


def test_assistant_artifacts_are_ignored():
    """The repository is the work product, not a record of what produced it."""
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    for pattern in ("CLAUDE.md", ".claude/", ".cursor/", ".aider*"):
        assert pattern in gitignore, f"{pattern} must be git-ignored"


def test_licence_is_mit():
    licence = (REPO_ROOT / "LICENSE").read_text()
    assert "MIT License" in licence
    assert "Devansh" in licence
