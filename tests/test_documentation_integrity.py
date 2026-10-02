from __future__ import annotations

import ast
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
import tomllib
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SCRIPT_COMMAND = re.compile(r"\bpython\s+scripts/([A-Za-z0-9_./-]+\.py)\b")
MODULE_COMMAND = re.compile(r"\bpython\s+-m\s+(etf_cockpit(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")


def _documentation_files() -> tuple[Path, ...]:
    roots = (ROOT / "README.md", ROOT / "CONTRIBUTING.md")
    return roots + tuple(sorted(DOCS.rglob("*.md")))


def _link_destination(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1 : raw.index(">")]
    return raw.split()[0]


def test_relative_markdown_links_resolve_and_are_portable() -> None:
    for document in _documentation_files():
        content = document.read_text(encoding="utf-8")
        for raw in MARKDOWN_LINK.findall(content):
            target = _link_destination(raw)
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or target.startswith("#"):
                continue
            path_part = unquote(parsed.path)
            windows_path = PureWindowsPath(path_part)
            assert not Path(path_part).is_absolute(), (document, target)
            assert not windows_path.is_absolute() and not windows_path.drive, (document, target)
            assert not path_part.startswith(("/", "\\")), (document, target)
            if not path_part:
                continue
            assert (document.parent / path_part).resolve().exists(), (document, target)


def _command_documents() -> tuple[Path, ...]:
    return tuple(
        document
        for document in _documentation_files()
        if (DOCS / "history") not in document.parents
    )


def _argparse_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    module_aliases = {"argparse"}
    class_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "argparse":
                    module_aliases.add(item.asname or "argparse")
        elif isinstance(node, ast.ImportFrom) and node.module == "argparse":
            for item in node.names:
                if item.name == "ArgumentParser":
                    class_aliases.add(item.asname or item.name)
    return module_aliases, class_aliases


def _builds_argparse_parser(script: Path) -> bool:
    tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    module_aliases, class_aliases = _argparse_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name) and function.id in class_aliases:
            return True
        if (
            isinstance(function, ast.Attribute)
            and function.attr == "ArgumentParser"
            and isinstance(function.value, ast.Name)
            and function.value.id in module_aliases
        ):
            return True
    return False


def test_documented_python_scripts_and_modules_resolve() -> None:
    for document in _command_documents():
        content = document.read_text(encoding="utf-8")
        for match in SCRIPT_COMMAND.finditer(content):
            script = ROOT / "scripts" / match.group(1)
            assert script.is_file(), (document, match.group(0))
        for match in MODULE_COMMAND.finditer(content):
            module_parts = match.group(1).split(".")
            module_root = ROOT / "src" / Path(*module_parts)
            assert module_root.with_suffix(".py").is_file() or (
                module_root / "__main__.py"
            ).is_file(), (document, match.group(0))


def test_documented_argparse_scripts_accept_help() -> None:
    scripts: set[Path] = set()
    for document in _command_documents():
        content = document.read_text(encoding="utf-8")
        scripts.update(
            (ROOT / "scripts" / match.group(1)).resolve()
            for match in SCRIPT_COMMAND.finditer(content)
        )
    for script in sorted(scripts):
        if not _builds_argparse_parser(script):
            continue
        environment = os.environ.copy()
        configured_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            value
            for value in (str(ROOT / "src"), configured_pythonpath)
            if value
        )
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=environment,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, (
            script.relative_to(ROOT),
            result.stdout[-2000:],
            result.stderr[-2000:],
        )


def test_generated_documentation_has_no_drift() -> None:
    for script in (
        "generate_data_dictionary.py",
        "generate_application_api_docs.py",
    ):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, (script, result.stdout, result.stderr)


def test_data_dictionary_version_matches_project_release() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    dictionary = (ROOT / "docs" / "reference" / "data-dictionary.md").read_text(
        encoding="utf-8"
    )
    assert dictionary.splitlines()[2] == f"Release version: `{version}`."
