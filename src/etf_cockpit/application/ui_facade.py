"""Presentation-facing compatibility facade for the first ISSUE-0071 wave.

Pages, components and selectors depend on this application boundary instead
of importing storage/provider implementations directly. The underlying
implementations remain compatible while later slices move them behind typed
ports and application commands.
"""

from etf_cockpit.chatgpt_bridge.audit_packet import *  # noqa: F401,F403
from etf_cockpit.data.backup_restore import *  # noqa: F401,F403
from etf_cockpit.data.decision_journal import *  # noqa: F401,F403
from etf_cockpit.data.export_tables import *  # noqa: F401,F403
from etf_cockpit.data.fund_documents import *  # noqa: F401,F403
from etf_cockpit.data.fund_holdings import *  # noqa: F401,F403
from etf_cockpit.data.fundamentals import *  # noqa: F401,F403
from etf_cockpit.data.fx_data import *  # noqa: F401,F403
from etf_cockpit.data.health import *  # noqa: F401,F403
from etf_cockpit.data.import_export import *  # noqa: F401,F403
from etf_cockpit.data.local_storage import *  # noqa: F401,F403
from etf_cockpit.data.manual_notes import *  # noqa: F401,F403
from etf_cockpit.data.news_context import *  # noqa: F401,F403
from etf_cockpit.data.parsed_disclosures import *  # noqa: F401,F403
from etf_cockpit.data.provider_registry import *  # noqa: F401,F403
from etf_cockpit.data.reference_data import *  # noqa: F401,F403
from etf_cockpit.data.run_changes import *  # noqa: F401,F403
from etf_cockpit.data.score_history import *  # noqa: F401,F403
from etf_cockpit.data.trust_artifacts import *  # noqa: F401,F403
from etf_cockpit.data.universe_store import *  # noqa: F401,F403
from etf_cockpit.models.forecast_scores import *  # noqa: F401,F403
from etf_cockpit.models.local_weights import *  # noqa: F401,F403
from etf_cockpit.portfolio.allocation import *  # noqa: F401,F403
from etf_cockpit.portfolio.risk import *  # noqa: F401,F403
from etf_cockpit.portfolio.risk_analytics import *  # noqa: F401,F403
from etf_cockpit.signals.simple_scores import *  # noqa: F401,F403
