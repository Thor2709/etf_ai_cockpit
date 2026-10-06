"""ChatGPT review-pack export and audit import facade (application; ADR-0002)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import pandas as pd

from etf_cockpit.audit.local_llm import (
    build_local_audit_context as build_local_audit_context,
    check_local_llm_status as check_local_llm_status,
    generate_local_audit_commentary as generate_local_audit_commentary,
    load_local_llm_settings as load_local_llm_settings,
    save_local_audit_commentary as save_local_audit_commentary,
)
from etf_cockpit.audit.thesis_diary import (
    ThesisDiaryIntegrityError as ThesisDiaryIntegrityError,
    ThesisDiaryStore as ThesisDiaryStore,
    disclosure_safe_entry as disclosure_safe_entry,
    disclosure_safe_outcome as disclosure_safe_outcome,
    disclosure_safe_review as disclosure_safe_review,
)
from etf_cockpit.backtest.engine import BacktestReport
from etf_cockpit.chatgpt_bridge.export_pack import export_review_pack
from etf_cockpit.chatgpt_bridge.import_audit import import_audit_json
from etf_cockpit.chatgpt_bridge.schemas import (
    ChatGPTAudit,
    ChatGPTAuditV2,
)
from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.types import (
    DataQualityReport,
    SignalResult,
)
from etf_cockpit.core.workflow import PublicationScopeFactory


class ChatGPTBridge:
    def __init__(self, config: AppConfig):
        self.config = config

    def export_review_pack(
        self,
        as_of_date: date,
        holdings: pd.DataFrame,
        features: pd.DataFrame,
        signals: list[SignalResult],
        backtest: BacktestReport,
        data_report: DataQualityReport | None = None,
        publish_guard: PublicationScopeFactory | None = None,
    ) -> Path:
        return export_review_pack(
            self.config,
            holdings,
            features,
            signals,
            backtest,
            as_of_date=as_of_date,
            data_report=data_report,
            publish_guard=publish_guard,
        )

    def import_audit_json(self, path: Path) -> ChatGPTAudit | ChatGPTAuditV2:
        return import_audit_json(path, self.config)
