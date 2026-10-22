"""Local S&P membership evidence; effective intervals are half open.

Snapshots and Wikipedia's effective Date do NOT prove announcement dates.
Callers must supply an evidenced announcement for every transition and a
knowledge date for the baseline. Date-only announcements become usable at
23:59:59.999999 UTC. The baseline is an observed lower bound, never an inferred
original entry date. Open and closed revisions have separate knowledge dates:
an exit must not leak into an earlier replay. Missing evidence/unknown shapes
raise ValueError. Sources are compared, never silently combined.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timezone
from html.parser import HTMLParser
import io
import re


def day(value: str) -> str:
    value = re.sub(r"\[\d+\]", "", value).strip()
    for fmt in ("%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"unrecognised date: {value!r}")


def knowledge(value: str) -> str:
    """Require a date or an explicitly zoned timestamp; never assume a zone."""
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time.max, timezone.utc).isoformat()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("known_at requires a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def parse_fja_csv(text: str, *, date_column: str, tickers_column: str) -> list[dict]:
    """Column names are configured because the recorded upstream shape can vary."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames != [date_column, tickers_column]:
        raise ValueError("unexpected historical-components CSV header")
    result = []
    for row in reader:
        if None in row or not isinstance(row.get(tickers_column), str):
            raise ValueError("unexpected historical-components CSV row")
        members = [item.strip() for item in row[tickers_column].split(",")]
        if not members or any(not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]*", item) for item in members):
            raise ValueError("invalid ticker list")
        if len(set(members)) != len(members):
            raise ValueError("duplicate snapshot ticker")
        result.append({"date": day(row[date_column]), "tickers": sorted(members)})
    result.sort(key=lambda row: row["date"])
    if not result or len({row["date"] for row in result}) != len(result):
        raise ValueError("empty history or duplicate snapshot date")
    return result


class _Table(HTMLParser):
    def __init__(self, table_id: str):
        super().__init__(convert_charrefs=True)
        self.table_id, self.depth, self.matches = table_id, 0, 0
        self.rows, self.row, self.cell = [], [], None
        self.pending = {}
        self.spans = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            if self.depth:
                raise ValueError("nested changes table unsupported")
            if attrs.get("id") == self.table_id:
                self.depth, self.matches = 1, self.matches + 1
        if not self.depth:
            return
        if tag == "tr":
            self.row, self.spans = [], []
        if tag in {"td", "th"}:
            self.cell = []
            self.span = (int(attrs.get("rowspan", 1)), int(attrs.get("colspan", 1)))
        if tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.depth and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag in {"td", "th"} and self.cell is not None:
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            self.row.append(text)
            self.spans.append(self.span)
            self.cell = None
        if tag == "tr" and self.row:
            cells, column, upcoming = [], 0, {}
            def carry():
                nonlocal column
                while column in self.pending:
                    text, remaining = self.pending[column]
                    cells.append(text)
                    if remaining > 1:
                        upcoming[column] = (text, remaining - 1)
                    column += 1
            for text, (rows, columns) in zip(self.row, self.spans):
                carry()
                for _ in range(columns):
                    cells.append(text)
                    if rows > 1:
                        upcoming[column] = (text, rows - 1)
                    column += 1
            carry()
            self.rows.append(cells)
            self.pending = upcoming
        if tag == "table":
            self.depth = 0


def parse_wikipedia_changes(html: str, *, table_id: str) -> list[dict]:
    """Accept the configured selected-changes table, including rowspans.

    Two recorded shapes are verified: the original six-column table headed
    "Date" and the live "Historical components of the S&P 500" table headed
    "Effective Date" with an optional trailing "Refs" column (a row may omit it).
    Announcement evidence is supplied separately; the first column is effective.
    Any other header/column count is a hard failure, not a best-effort scrape.
    """
    parser = _Table(table_id)
    parser.feed(html)
    rows = parser.rows
    if parser.matches != 1 or len(rows) < 2:
        raise ValueError("expected exactly one configured selected-changes table")
    shapes = {("Date",): 6, ("Effective Date",): 6, ("Effective Date", "Refs"): 7}
    shape = next((key for key in shapes if rows[0] == [key[0], "Added", "Added", "Removed", "Removed", "Reason", *key[1:]]), None)
    if shape is None:
        raise ValueError("unexpected Wikipedia selected-changes header")
    if rows[1] != [shape[0], "Ticker", "Security", "Ticker", "Security", "Reason", *shape[1:]]:
        raise ValueError("unexpected Wikipedia selected-changes subheader")
    events = []
    for row in rows[2:]:
        # The live table omits the Refs cell on a few old rows.
        if len(row) not in {shapes[shape], shapes[shape] - len(shape[1:])}:
            raise ValueError("unexpected Wikipedia selected-changes row")
        effective = day(row[0])
        for action, index in (("add", 1), ("remove", 3)):
            ticker, name = row[index:index + 2]
            # Verified live artefact: three old rows carry a stray " |" after the ticker.
            ticker = re.sub(r" \|$", "", ticker)
            if ticker in {"", "—", "–"}:
                if name not in {"", "—", "–"}:
                    raise ValueError("security without ticker")
                continue
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]*", ticker) or not name:
                raise ValueError("invalid Wikipedia ticker/security")
            events.append({"date": effective, "action": action, "ticker": ticker, "name": name})
    return sorted(events, key=lambda row: (row["date"], row["action"], row["ticker"]))


def build_intervals(baseline: dict, events: list[dict], announcements: list[dict], *, source: str) -> list[dict]:
    """Preserve entry and exit revisions, including removed and renamed tickers."""
    dates = {}
    for row in announcements:
        key = (day(row["date"]), row["action"], row["ticker"])
        if key in dates:
            raise ValueError("duplicate announcement evidence")
        if not row.get("source"):
            raise ValueError("announcement needs an evidence source")
        dates[key] = knowledge(row["known_at"])
    start, known = day(baseline["date"]), knowledge(baseline["known_at"])
    active, result = {}, []
    for ticker in baseline["tickers"]:
        if ticker in active:
            raise ValueError("duplicate baseline member")
        active[ticker] = {"ticker": ticker, "valid_from": start, "valid_to": None,
                          "source": source, "known_at": known, "name": baseline.get("names", {}).get(ticker)}
        result.append(dict(active[ticker]))
    seen = set()
    for row in sorted(events, key=lambda row: (row["date"], row["action"], row["ticker"])):
        effective, ticker, action = day(row["date"]), row["ticker"], row["action"]
        key = (effective, action, ticker)
        if effective <= start or key in seen or key not in dates:
            raise ValueError(f"missing/duplicate/out-of-range announcement: {key}")
        seen.add(key)
        announced = dates[key]
        if announced[:10] > effective:
            raise ValueError("announcement after effective date cannot establish contemporaneous history")
        if action == "add" and ticker not in active:
            active[ticker] = {"ticker": ticker, "valid_from": effective, "valid_to": None,
                              "source": source, "known_at": announced, "name": row.get("name")}
            result.append(dict(active[ticker]))
        elif action == "remove" and ticker in active:
            previous = active.pop(ticker)
            if announced <= previous["known_at"]:
                raise ValueError("exit revision must have later knowledge than entry")
            result.append({**previous, "valid_to": effective, "known_at": announced,
                           "name": row.get("name") or previous.get("name")})
        else:
            raise ValueError(f"inconsistent membership transition: {key}")
    return sorted(result, key=lambda row: (row["ticker"], row["valid_from"], row["known_at"]))


def fja_events(snapshots: list[dict]) -> list[dict]:
    events = []
    for previous, current in zip(snapshots, snapshots[1:]):
        before, after = set(previous["tickers"]), set(current["tickers"])
        for action, tickers in (("add", after - before), ("remove", before - after)):
            events.extend({"date": current["date"], "action": action, "ticker": ticker} for ticker in sorted(tickers))
    return events


def intervals_from_fja(snapshots: list[dict], announcements: list[dict], *, baseline_known_at: str,
                       baseline_names: dict | None = None, extra_events: list[dict] = ()) -> list[dict]:
    """``extra_events`` extend the history past the last snapshot (each needs an announcement)."""
    return build_intervals({**snapshots[0], "known_at": baseline_known_at, "names": baseline_names or {}},
                           fja_events(snapshots) + list(extra_events), announcements, source="fja05680")


def compare_events(left: list[dict], right: list[dict], *, start: str, end: str) -> list[dict]:
    """Exact (date, action, ticker) differences inside [start, end]; never reconciles them.

    Wikipedia lists only selected changes and omits pure ticker renames, so a full
    history rarely agrees exactly. The caller decides whether differences block.
    """
    def keys(rows):
        return {(day(row["date"]), row["action"], row["ticker"]) for row in rows if start <= day(row["date"]) <= end}
    a, b = keys(left), keys(right)
    return [{"only_in": source, "date": date_, "action": action, "ticker": ticker}
            for source, items in (("fja05680", a - b), ("wikipedia", b - a))
            for date_, action, ticker in sorted(items)]


def cross_validate(left: list[dict], right: list[dict]) -> list[dict]:
    """Return every differing revision; callers must block publication on any diff."""
    fields = ("ticker", "valid_from", "valid_to", "known_at")
    a, b = ({tuple(row[key] for key in fields) for row in rows} for rows in (left, right))
    return [{"only_in": source, **dict(zip(fields, values))}
            for source, values_set in (("fja05680", a - b), ("wikipedia", b - a))
            for values in sorted(values_set, key=lambda item: tuple(str(value) for value in item))]
