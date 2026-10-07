"""Chart library drawn with flet.canvas only (FINAL_UI_SPEC section 4).

Named ``chartkit`` because ``components/charts.py`` (legacy) already owns the ``charts`` module name.
Every chart takes plain data plus ``width``/``height`` and returns a control whose ``.data`` is a ChartHandle
(``.scene`` for tests, ``.resize(w, h)`` to redraw at a new size).
"""
from etf_cockpit.app.components.chartkit import palette
from etf_cockpit.app.components.chartkit.bars import (
    BarSeries, LineSeries, Segment, bar_chart, grouped_bar_chart, histogram, horizontal_stacked_bar,
)
from etf_cockpit.app.components.chartkit.core import (
    ChartHandle, Hit, Margins, Scene, empty_state, scene_of,
)
from etf_cockpit.app.components.chartkit.flow import SankeyLink, SankeyNode, TreeItem, sankey, squarify, treemap
from etf_cockpit.app.components.chartkit.lines import (
    Band, EventMark, Series, drawdown_panel, line_chart, price_drawdown_chart, sparkline,
)
from etf_cockpit.app.components.chartkit.radial import RadarSeries, Slice, donut_chart, gauge, radar_chart
from etf_cockpit.app.components.chartkit.scatter import Bubble, scatter_bubble
from etf_cockpit.app.components.chartkit.surface import surface3d

__all__ = [
    "palette", "BarSeries", "LineSeries", "Segment", "bar_chart", "grouped_bar_chart", "histogram",
    "horizontal_stacked_bar", "ChartHandle", "Hit", "Margins", "Scene", "empty_state", "scene_of", "SankeyLink",
    "SankeyNode", "TreeItem", "sankey", "squarify", "treemap", "Band", "EventMark", "Series", "drawdown_panel",
    "line_chart", "price_drawdown_chart", "sparkline", "RadarSeries", "Slice", "donut_chart", "gauge",
    "radar_chart", "Bubble", "scatter_bubble", "surface3d",
]
