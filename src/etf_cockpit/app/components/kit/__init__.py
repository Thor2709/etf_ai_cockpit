"""Final-UI component kit (FINAL_UI_SPEC section 3).

``from etf_cockpit.app.components.kit import GlassCard, Well, ...`` gives the 28 spec components. The
previous lower-case helpers (``glass_panel``, ``card``, ``kpi_tile`` ...) live in ``legacy`` and stay
importable from here until every page has moved to the new kit.
"""

from etf_cockpit.app.components.kit.controls import Button, Disclosure, Field, Segmented, Toggle, field_input_style
from etf_cockpit.app.components.kit.data import (
    Badge,
    DataTable,
    EvidenceTable,
    EvidenceTableSwitcher,
    GlossaryItem,
    ListRow,
    ScoreBar,
    Tag,
    TableColumn,
    score_colors,
)
from etf_cockpit.app.components.kit.flows import GateCheck, Pipeline, StepSpec, Stepper
from etf_cockpit.app.components.kit.legacy import (
    backdrop,
    card,
    cta_button,
    cylinder_bar,
    glass_panel,
    kpi_tile,
    pill_group,
    status_tag,
    table_style,
    toggle,
)
from etf_cockpit.app.components.kit.legacy import score_bar as legacy_score_bar
from etf_cockpit.app.components.kit.surfaces import (
    CardMenu,
    EmptyState,
    FloatingPanel,
    GlassCard,
    MenuItem,
    Note,
    SectionHeader,
    Well,
)
from etf_cockpit.app.components.kit.tiles import Headline, KpiStrip, KpiStripItem, KpiTile, StatTile, VerdictRing

# The 28 components of spec section 3, in spec order.
KIT_COMPONENTS = (
    "GlassCard",
    "Well",
    "DataTable",
    "Tag",
    "ScoreBar",
    "KpiTile",
    "StatTile",
    "Field",
    "Toggle",
    "Segmented",
    "Button.primary",
    "Button.secondary",
    "ListRow",
    "GlossaryItem",
    "Headline",
    "VerdictRing",
    "GateCheck",
    "Pipeline",
    "KpiStrip",
    "FloatingPanel",
    "Badge",
    "Note",
    "EmptyState",
    "CardMenu",
    "SectionHeader",
    "Disclosure",
    "EvidenceTableSwitcher",
    "Stepper",
)

KIT_COMPONENT_COUNT = len(KIT_COMPONENTS)

# score_bar (lower case) keeps its legacy signature for existing pages.
score_bar = legacy_score_bar

__all__ = [
    "KIT_COMPONENTS",
    "KIT_COMPONENT_COUNT",
    "Badge",
    "Button",
    "CardMenu",
    "DataTable",
    "Disclosure",
    "EmptyState",
    "EvidenceTable",
    "EvidenceTableSwitcher",
    "Field",
    "FloatingPanel",
    "GateCheck",
    "GlassCard",
    "GlossaryItem",
    "Headline",
    "KpiStrip",
    "KpiStripItem",
    "KpiTile",
    "ListRow",
    "MenuItem",
    "Note",
    "Pipeline",
    "ScoreBar",
    "SectionHeader",
    "Segmented",
    "StatTile",
    "StepSpec",
    "Stepper",
    "TableColumn",
    "Tag",
    "Toggle",
    "VerdictRing",
    "Well",
    "backdrop",
    "card",
    "cta_button",
    "cylinder_bar",
    "glass_panel",
    "kpi_tile",
    "pill_group",
    "score_bar",
    "field_input_style",
    "score_colors",
    "status_tag",
    "table_style",
    "toggle",
]
