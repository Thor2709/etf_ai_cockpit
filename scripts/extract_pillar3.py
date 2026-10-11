"""Propose Pillar 3 / annual-report figures for the owner's confirm queue (semi-automatic).

Usage:
    python scripts/extract_pillar3.py --root <data root> --id <ID> --file report.pdf --source-url https://...
    python scripts/extract_pillar3.py --root <data root> --id <ID> --download https://... [--title ...]

Figures land in ``data/pending/pillar3/<ID>.json`` as ``pending`` and are never evidence until the owner confirms
them in the instrument page. A downloaded PDF is saved under ``data/inbox/pillar3/<ID>/`` and only parsed for text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from etf_cockpit.data.pillar3_extract import ingest_pdf

MAX_BYTES = 80 * 1024 * 1024


def download(url: str, destination: Path) -> Path:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("only https URLs are downloaded")
    request = Request(url, headers={"User-Agent": "etf-cockpit-pillar3/1 (local research)"})
    with urlopen(request, timeout=60) as response:  # noqa: S310 - https only, size capped, parsed for text only
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("document exceeds the size cap")
    if not payload.startswith(b"%PDF"):
        raise ValueError("download is not a PDF")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{hashlib.sha256(payload).hexdigest()[:16]}.pdf"
    target.write_bytes(payload)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--id", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path)
    group.add_argument("--download")
    parser.add_argument("--source-url")
    parser.add_argument("--title")
    args = parser.parse_args(argv)
    instrument_id = args.id.strip().upper()
    if args.download:
        path = download(args.download, args.root / "data" / "inbox" / "pillar3" / instrument_id)
        source_url = args.download
    else:
        if not args.source_url:
            parser.error("--source-url is required with --file")
        path, source_url = args.file, args.source_url
    result = ingest_pdf(args.root, instrument_id, str(path), source_url=source_url, title=args.title)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
