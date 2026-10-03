from __future__ import annotations

from pathlib import Path
import re
import tomllib

from etf_cockpit.app.router import PAGES, WORKSPACE_GROUPS


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
STAMPED_DOCUMENTS = (
    DOCS / "README.md",
    DOCS / "user" / "USER_GUIDE.md",
    DOCS / "user" / "WORKSPACES.md",
    DOCS / "user" / "TUTORIALS.md",
    DOCS / "user" / "LIMITATIONS.md",
    DOCS / "operations" / "OPERATOR_RUNBOOK.md",
    DOCS / "development" / "DEVELOPER_GUIDE.md",
    DOCS / "reference" / "methodology-index.md",
)
LABEL_DOCUMENTS = (
    DOCS / "user" / "WORKSPACES.md",
    DOCS / "user" / "TUTORIALS.md",
    DOCS / "operations" / "OPERATOR_RUNBOOK.md",
)
BOLD = re.compile(r"\*\*([^*]+)\*\*")
ROUTE_ROW = re.compile(r"(?m)^\| `(/[A-Za-z0-9/_-]*)` \| ([^|]+) \|")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_workspace_guide_matches_registered_routes_and_workspaces() -> None:
    guide = _text(DOCS / "user" / "WORKSPACES.md")
    documented = {route: title.strip() for route, title in ROUTE_ROW.findall(guide)}
    assert documented == {route: title for route, (title, _builder) in PAGES.items()}
    for workspace, routes in WORKSPACE_GROUPS:
        section = guide.split(f"### {workspace}\n", 1)
        assert len(section) == 2, workspace
        body = section[1].split("\n### ", 1)[0].split("\n## ", 1)[0]
        assert {route for route, _title in ROUTE_ROW.findall(body)} == set(routes), workspace


def test_documented_on_screen_labels_exist_in_application_source() -> None:
    corpus = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "src" / "etf_cockpit" / "app").rglob("*.py"))
    )
    for document in LABEL_DOCUMENTS:
        labels = {" ".join(label.split()) for label in BOLD.findall(_text(document))}
        assert labels, document
        missing = sorted(label for label in labels if label not in corpus)
        assert not missing, (document.name, missing)


def test_methodology_index_links_every_architecture_and_sdd_page() -> None:
    index = _text(DOCS / "reference" / "methodology-index.md")
    pages = sorted((DOCS / "architecture").glob("*.md")) + sorted((DOCS / "architecture").glob("*.json"))
    pages += sorted((DOCS / "sdd").glob("*.md"))
    # The presentation-boundary report is a test artefact, not a methodology page.
    missing = [
        page.relative_to(DOCS).as_posix()
        for page in pages
        if page.name != "presentation-boundary-report.json"
        and f"(../{page.relative_to(DOCS).as_posix()})" not in index
    ]
    assert not missing, missing


def test_documentation_release_stamps_match_project_version() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    for document in STAMPED_DOCUMENTS:
        lines = _text(document).splitlines()
        assert f"Release version: `{version}`." in lines[:4], document.name
