from __future__ import annotations

from etf_cockpit.analysis.stock_metrics import Metric
from etf_cockpit.application import research_report as rr
from etf_cockpit.application.stock_views import format_metric
from etf_cockpit.data import document_chunks as store

SHA = "a" * 64
METRICS = (
    Metric("roic", "ROIC", 0.1234, "ratio", "ok", basis="TTM", as_of="2026-06-30", source="sec:0001"),
    Metric("pe_ratio", "P/E", 18.5, "multiple", "ok", as_of="2026-06-30", source="eodhd:price"),
)


def _chunk_store(root):
    path = root / "data" / store.CHUNK_STORE_NAME
    chunks = store.chunk_pages(["Ongoing charges were <b>0.22</b> percent."], document_sha256=SHA, source_id="annual-report",
                               published_at="2026-03-01T00:00:00Z", known_at="2026-03-02T00:00:00Z")
    store.index_document(path, chunks)
    return path, chunks[0]


def test_every_number_is_the_metric_rendering_and_a_tampered_number_fails(tmp_path) -> None:
    path, chunk = _chunk_store(tmp_path)
    claim = rr.Claim("Charges <script>alert(1)</script> 99.9%", chunk.chunk_id, SHA)
    report = rr.build_research_report("Fund <X>", "2026-07-01T00:00:00Z", METRICS, (claim,), commentary="Model says ROIC is 55.5%")

    markdown, page = rr.render_markdown(report), rr.render_html(report)

    for metric in METRICS:
        assert format_metric(metric) in markdown and format_metric(metric) in page
    assert "<script>" not in page and "Fund &lt;X&gt;" in page
    assert rr.check_grounding(report, markdown, path)["status"] == "ok"
    assert rr.check_grounding(report, page, path, html=True)["status"] == "ok"
    tampered = markdown.replace(format_metric(METRICS[0]), "55.5%")
    assert rr.check_grounding(report, tampered, path)["status"] == "failed"
    assert rr.check_grounding(report, page.replace(format_metric(METRICS[1]), "1.0x"), path, html=True)["status"] == "failed"


def test_a_real_chunk_id_resolves_a_bad_one_fails_and_nothing_is_written_when_ungrounded(tmp_path) -> None:
    path, chunk = _chunk_store(tmp_path)
    good = rr.build_research_report("Fund", "2026-07-01T00:00:00Z", METRICS, (rr.Claim("Charges fell.", chunk.chunk_id, SHA),))
    bad = rr.build_research_report("Fund", "2026-07-01T00:00:00Z", METRICS, (rr.Claim("Charges fell.", "0" * 64, SHA),))
    wrong_document = rr.build_research_report("Fund", "2026-07-01T00:00:00Z", METRICS, (rr.Claim("Charges fell.", chunk.chunk_id, "b" * 64),))

    assert rr.check_grounding(good, rr.render_markdown(good), path)["status"] == "ok"
    assert rr.check_grounding(bad, rr.render_markdown(bad), path)["status"] == "failed"
    assert rr.check_grounding(good, rr.render_markdown(good), tmp_path / "missing.sqlite3")["status"] == "failed"
    assert rr.check_grounding(wrong_document, rr.render_markdown(wrong_document), path)["status"] == "failed"
    early = rr.build_research_report("Fund", "2026-03-01T00:00:00Z", METRICS, (rr.Claim("Charges fell.", chunk.chunk_id, SHA),))
    assert rr.check_grounding(early, rr.render_markdown(early), path)["status"] == "failed"  # chunk known 2026-03-02

    assert rr.write_report(bad, tmp_path / "out" / "bad.md", path)["status"] == "unavailable"
    assert not (tmp_path / "out" / "bad.md").exists()
    assert rr.write_report(good, tmp_path / "out" / "good.html", path)["status"] == "written"
    assert "<h1>Fund</h1>" in (tmp_path / "out" / "good.html").read_text(encoding="utf-8")
