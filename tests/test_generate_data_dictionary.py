from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.generate_data_dictionary import _parse_tables


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_data_dictionary.py"


@pytest.fixture
def fixture_tree(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "9.8.7"\n', encoding="utf-8"
    )
    source = tmp_path / "src" / "etf_cockpit" / "data" / "sample.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        '''SCHEMA = """
CREATE TABLE accounts (
    account_id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    balance NUMERIC DEFAULT 0,
    CHECK (balance >= 0)
);
CREATE TABLE account_events (
    event_id TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(account_id)
);
"""
''',
        encoding="utf-8",
    )
    contracts = tmp_path / "src" / "etf_cockpit" / "application" / "contracts.py"
    contracts.parent.mkdir(parents=True)
    contracts.write_text(
        """from dataclasses import dataclass

@dataclass
class SampleContract:
    \"\"\"A sample public contract.\"\"\"
    instrument_id: str
    as_of: str | None
""",
        encoding="utf-8",
    )
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "sample.yaml").write_text(
        "schema_version: sample.v1\nname: sample\nitems:\n  - one\n",
        encoding="utf-8",
    )
    return tmp_path


def _run_generator(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--root", str(root), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_renders_all_sections_and_source_fields(fixture_tree: Path) -> None:
    result = _run_generator(fixture_tree)

    assert result.returncode == 0, result.stderr
    rendered = (fixture_tree / "docs" / "reference" / "data-dictionary.md").read_text(
        encoding="utf-8"
    )
    assert "Release version: `9.8.7`." in rendered
    assert "## SQLite tables" in rendered
    assert "| accounts | account_id | INTEGER | PRIMARY KEY |" in rendered
    assert "| accounts | balance | NUMERIC | DEFAULT 0 |" in rendered
    assert "FOREIGN KEY" not in rendered
    assert "| account_events | account_id | INTEGER | REFERENCES accounts(account_id) |" in rendered
    assert "## Application contracts" in rendered
    assert r"| SampleContract | as_of | str \| None | A sample public contract. |" in rendered
    assert "| SampleContract | instrument_id | str | A sample public contract. |" in rendered
    assert "## Configuration files" in rendered
    assert "| configs/sample.yaml | items, name, schema_version | schema_version=sample.v1 |" in rendered


def test_output_is_deterministic_across_runs(fixture_tree: Path) -> None:
    first = _run_generator(fixture_tree)
    output = fixture_tree / "docs" / "reference" / "data-dictionary.md"
    first_bytes = output.read_bytes()
    second = _run_generator(fixture_tree)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert output.read_bytes() == first_bytes
    assert b"\r\n" not in first_bytes
    assert fixture_tree.as_posix().encode("utf-8") not in first_bytes


def test_check_mode_accepts_fresh_file_and_reports_first_stale_line(
    fixture_tree: Path,
) -> None:
    generated = _run_generator(fixture_tree)
    assert generated.returncode == 0, generated.stderr

    fresh = _run_generator(fixture_tree, "--check")
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr
    assert "up to date" in fresh.stdout

    output = fixture_tree / "docs" / "reference" / "data-dictionary.md"
    fresh_bytes = output.read_bytes()
    output.write_bytes(fresh_bytes.replace(b"\n", b"\r\n"))
    newline_drift = _run_generator(fixture_tree, "--check")
    assert newline_drift.returncode == 1
    assert "first differing line 1" in newline_drift.stdout
    output.write_bytes(fresh_bytes)

    output.write_text("# Stale dictionary\n", encoding="utf-8")
    stale = _run_generator(fixture_tree, "--check")
    assert stale.returncode == 1
    assert "first differing line 1" in stale.stdout
    assert "# Data dictionary" in stale.stdout
    assert output.read_text(encoding="utf-8") == "# Stale dictionary\n"


def test_unparseable_create_table_fails_loudly(fixture_tree: Path) -> None:
    source = fixture_tree / "src" / "etf_cockpit" / "data" / "sample.py"
    source.write_text('SCHEMA = "CREATE TABLE (broken)"\n', encoding="utf-8")

    result = _run_generator(fixture_tree)

    assert result.returncode != 0
    assert "unparseable CREATE TABLE" in result.stderr


def test_quoted_table_and_column_identifiers_are_preserved() -> None:
    tables = _parse_tables(
        '''SCHEMA = """
CREATE TABLE "audit.events" (id INTEGER);
CREATE TABLE main.t ("id" PRIMARY KEY);
CREATE TABLE `audit.events` (`id` INTEGER);
CREATE TABLE [audit.events] ([id] INTEGER);
"""
''',
        "etf_cockpit/data/sample.py",
    )

    assert tables[0].name == "audit.events"
    assert tables[0].columns[0].name == "id"
    assert tables[1].name == "t"
    assert tables[1].columns[0].name == "id"
    assert tables[1].columns[0].constraints == "PRIMARY KEY"
    assert tables[2].name == "audit.events"
    assert tables[2].columns[0].name == "id"
    assert tables[3].name == "audit.events"
    assert tables[3].columns[0].name == "id"
