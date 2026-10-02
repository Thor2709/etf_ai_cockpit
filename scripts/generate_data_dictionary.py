"""Generate a source-derived dictionary of local schemas and contracts."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import re
import tomllib


CREATE_TABLE = re.compile(r"\bCREATE\s+TABLE\b", re.IGNORECASE)
TABLE_HEADER = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>(?:\"(?:[^\"]|\"\")*\"|`[^`]*`|\[[^\]]+\]|[A-Za-z_][\w$]*)"
    r"(?:\s*\.\s*(?:\"(?:[^\"]|\"\")*\"|`[^`]*`|\[[^\]]+\]|[A-Za-z_][\w$]*))?)\s*\(",
    re.IGNORECASE,
)
CONSTRAINT_WORDS = {
    "AS",
    "CHECK",
    "COLLATE",
    "CONSTRAINT",
    "DEFAULT",
    "FOREIGN",
    "GENERATED",
    "NOT",
    "PRIMARY",
    "REFERENCES",
    "UNIQUE",
}
TABLE_CONSTRAINT_WORDS = {"CONSTRAINT", "CHECK", "FOREIGN", "PRIMARY", "UNIQUE"}
SCHEMA_VERSION_KEY = re.compile(r"(?:^|_)(?:schema|version)(?:_|$)", re.IGNORECASE)
TOP_LEVEL_KEY = re.compile(r"^([^\s:#][^:]*?)\s*:\s*(.*)$")


@dataclass(frozen=True)
class Column:
    name: str
    declared_type: str
    constraints: str


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    module: str


@dataclass(frozen=True)
class ContractField:
    contract: str
    name: str
    annotation: str
    documentation: str


@dataclass(frozen=True)
class Configuration:
    path: str
    keys: tuple[str, ...]
    schema_version: str


def _mask_comments(sql: str) -> str:
    """Replace SQL comments with spaces while preserving quoted contents."""
    result = list(sql)
    quote: str | None = None
    index = 0
    while index < len(sql):
        character = sql[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            elif character == "\\" and quote == "'":
                index += 2
                continue
        elif character in "'\"`":
            quote = character
        elif character == "[":
            quote = "]"
        elif sql.startswith("--", index):
            end = sql.find("\n", index)
            end = len(sql) if end < 0 else end
            for position in range(index, end):
                if result[position] != "\n":
                    result[position] = " "
            index = end
            continue
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                raise ValueError("unclosed SQL block comment")
            for position in range(index, end + 2):
                if result[position] != "\n":
                    result[position] = " "
            index = end + 2
            continue
        index += 1
    return "".join(result)


def _matching_close(sql: str, opening: int) -> int:
    quote: str | None = None
    depth = 0
    index = opening
    while index < len(sql):
        character = sql[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            elif character == "\\" and quote == "'":
                index += 2
                continue
        elif character in "'\"`":
            quote = character
        elif character == "[":
            quote = "]"
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("unclosed CREATE TABLE column list")


def _split_definitions(body: str) -> list[str]:
    definitions: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(body):
        character = body[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(body) and body[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            elif character == "\\" and quote == "'":
                index += 2
                continue
        elif character in "'\"`":
            quote = character
        elif character == "[":
            quote = "]"
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced parentheses in CREATE TABLE column list")
        elif character == "," and depth == 0:
            definitions.append(body[start:index].strip())
            start = index + 1
        index += 1
    if quote is not None or depth != 0:
        raise ValueError("unbalanced quote or parentheses in CREATE TABLE column list")
    definitions.append(body[start:].strip())
    if any(not definition for definition in definitions):
        raise ValueError("empty column or constraint in CREATE TABLE")
    return definitions


def _top_level_words(text: str) -> list[tuple[str, int, int]]:
    words: list[tuple[str, int, int]] = []
    quote: str | None = None
    depth = 0
    index = 0
    while index < len(text):
        character = text[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif character in "'\"`":
            quote = character
        elif character == "[":
            quote = "]"
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif depth == 0 and (character.isalpha() or character == "_"):
            start = index
            index += 1
            while index < len(text) and (text[index].isalnum() or text[index] in "_$"):
                index += 1
            words.append((text[start:index].upper(), start, index))
            continue
        index += 1
    return words


def _column(definition: str) -> Column:
    match = re.match(
        r"^\s*(?P<name>\"(?:[^\"]|\"\")*\"|`[^`]*`|\[[^\]]+\]|[^\s]+)"
        r"(?:\s+(?P<tail>.*))?$",
        definition,
        re.DOTALL,
    )
    if match is None:
        raise ValueError(f"cannot parse column definition: {definition}")
    name = match.group("name")
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1].replace('""', '"')
    elif name.startswith("`") and name.endswith("`"):
        name = name[1:-1]
    elif name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    tail = (match.group("tail") or "").strip()
    words = _top_level_words(tail)
    constraint_start: int | None = None
    for index, (word, start, _end) in enumerate(words):
        next_word = words[index + 1][0] if index + 1 < len(words) else ""
        if word == "NOT" and next_word == "NULL":
            constraint_start = start
            break
        if word == "PRIMARY" and next_word == "KEY":
            constraint_start = start
            break
        if word in CONSTRAINT_WORDS:
            constraint_start = start
            break
    if constraint_start is None:
        return Column(name, tail, "")
    return Column(
        name,
        tail[:constraint_start].strip(),
        " ".join(tail[constraint_start:].split()),
    )


def _parse_tables(source: str, module: str) -> list[Table]:
    try:
        tree = ast.parse(source, filename=module)
    except SyntaxError as exc:
        raise ValueError(f"cannot parse Python source for {module}: {exc}") from exc
    sql_strings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if CREATE_TABLE.search(node.value):
                sql_strings.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            if any(
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and CREATE_TABLE.search(value.value)
                for value in node.values
            ):
                raise ValueError(f"unparseable dynamic CREATE TABLE in {module}")

    tables: list[Table] = []
    for sql in sql_strings:
        index = 0
        while match := CREATE_TABLE.search(sql, index):
            try:
                masked = _mask_comments(sql)
                header = TABLE_HEADER.match(masked, match.start())
                if header is None:
                    raise ValueError("invalid CREATE TABLE header")
                opening = header.end() - 1
                closing = _matching_close(masked, opening)
                raw_name = header.group("name").split(".")[-1].strip()
                name = raw_name
                if name.startswith('"') and name.endswith('"'):
                    name = name[1:-1].replace('""', '"')
                elif name.startswith("`") and name.endswith("`"):
                    name = name[1:-1]
                elif name.startswith("[") and name.endswith("]"):
                    name = name[1:-1]
                definitions = _split_definitions(masked[opening + 1 : closing])
                columns: list[Column] = []
                for definition in definitions:
                    first_word = _top_level_words(definition)
                    if first_word and first_word[0][0] in TABLE_CONSTRAINT_WORDS:
                        columns.append(
                            Column("<table constraint>", "", " ".join(definition.split()))
                        )
                    else:
                        columns.append(_column(definition))
                if not name or not columns:
                    raise ValueError("table name or columns are missing")
                tables.append(Table(name, tuple(columns), module))
                index = closing + 1
            except ValueError as exc:
                raise ValueError(f"unparseable CREATE TABLE in {module}: {exc}") from exc
    return tables


def _first_docstring_line(node: ast.ClassDef) -> str:
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(
        node.body[0].value, ast.Constant
    ) and isinstance(node.body[0].value.value, str):
        return node.body[0].value.value.strip().splitlines()[0].strip()
    return ""


def _is_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name) and target.id == "dataclass":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "dataclass":
            return True
    return False


def _contracts(path: Path) -> list[ContractField]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise ValueError(f"cannot parse application contracts: {exc}") from exc
    result: list[ContractField] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        if not _is_dataclass(node):
            continue
        documentation = _first_docstring_line(node)
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                result.append(
                    ContractField(
                        node.name,
                        statement.target.id,
                        ast.unparse(statement.annotation),
                        documentation,
                    )
                )
    return result


def _configurations(root: Path) -> list[Configuration]:
    configurations: list[Configuration] = []
    for path in sorted((root / "configs").glob("*.yaml")):
        keys: list[str] = []
        versions: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line[0].isspace() or line.startswith("#") or line.startswith("---"):
                continue
            match = TOP_LEVEL_KEY.match(line)
            if match is None:
                continue
            key = match.group(1).strip().strip("\"'")
            keys.append(key)
            if SCHEMA_VERSION_KEY.search(key):
                value = match.group(2).split(" #", 1)[0].strip()
                versions.append(f"{key}={value}" if value else key)
        configurations.append(
            Configuration(
                path.relative_to(root).as_posix(),
                tuple(sorted(keys, key=str.casefold)),
                "; ".join(sorted(versions, key=str.casefold)) or "—",
            )
        )
    return configurations


def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|") or "—"


def render(root: Path) -> str:
    root = root.resolve()
    with (root / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]

    tables: list[Table] = []
    source_root = root / "src" / "etf_cockpit"
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(root / "src").as_posix()
        tables.extend(_parse_tables(path.read_text(encoding="utf-8"), relative))
    tables.sort(key=lambda table: (table.name.casefold(), table.name, table.module))

    contract_fields = _contracts(source_root / "application" / "contracts.py")
    contract_fields.sort(
        key=lambda item: (item.contract.casefold(), item.name.casefold(), item.annotation)
    )
    configurations = _configurations(root)

    lines = [
        "# Data dictionary",
        "",
        f"Release version: `{version}`.",
        "",
        "Generated with `python scripts/generate_data_dictionary.py`. Regenerate after a contract change; use `python scripts/generate_data_dictionary.py --check` to detect drift.",
        "",
        "## SQLite tables",
        "",
        "| Table | Column | Type | Constraints | Defining module |",
        "| --- | --- | --- | --- | --- |",
    ]
    table_rows = [
        (table.name, column.name, column.declared_type, column.constraints, table.module)
        for table in tables
        for column in table.columns
    ]
    table_rows.sort(key=lambda row: tuple(value.casefold() for value in row))
    for row in table_rows:
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    if not table_rows:
        lines.append("| — | — | — | — | — |")

    lines.extend(
        [
            "",
            "## Application contracts",
            "",
            "| Dataclass | Field | Annotation | First docstring line |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in contract_fields:
        row = (item.contract, item.name, item.annotation, item.documentation)
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    if not contract_fields:
        lines.append("| — | — | — | — |")

    lines.extend(
        [
            "",
            "## Configuration files",
            "",
            "| File | Top-level keys | Declared schema/version key |",
            "| --- | --- | --- |",
        ]
    )
    for config in configurations:
        row = (config.path, ", ".join(config.keys), config.schema_version)
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    if not configurations:
        lines.append("| — | — | — |")
    return "\n".join(lines) + "\n"


def _report_difference(path: Path, expected: str, actual: str | None) -> None:
    expected_lines = expected.splitlines(keepends=True)
    actual_lines = actual.splitlines(keepends=True) if actual is not None else []
    first_difference = next(
        (
            index
            for index, (expected_line, actual_line) in enumerate(
                zip(expected_lines, actual_lines), start=1
            )
            if expected_line != actual_line
        ),
        min(len(expected_lines), len(actual_lines)) + 1,
    )
    expected_line = (
        expected_lines[first_difference - 1].rstrip("\r\n")
        if first_difference <= len(expected_lines)
        else "<end of generated file>"
    )
    actual_line = (
        actual_lines[first_difference - 1].rstrip("\r\n")
        if first_difference <= len(actual_lines)
        else "<missing file>" if actual is None else "<end of file>"
    )
    print(f"STALE: {path}")
    print(f"first differing line {first_difference}: expected: {expected_line}")
    print(f"actual: {actual_line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    destination = root / "docs" / "reference" / "data-dictionary.md"
    rendered = render(root)
    if args.check:
        try:
            actual = destination.read_bytes().decode("utf-8")
        except FileNotFoundError:
            actual = None
        if actual != rendered:
            _report_difference(destination, rendered, actual)
            return 1
        print("OK: data dictionary is up to date")
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(rendered.encode("utf-8"))
    print(f"WROTE: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
