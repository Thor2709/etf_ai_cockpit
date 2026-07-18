from __future__ import annotations

from etf_cockpit.app.command_palette import all_commands, search_commands


PAGES = {
    "/": ("Home", object()),
    "/comparison": ("Comparison", object()),
    "/operations": ("Operations Centre", object()),
}
GROUPS = (("Home", ("/",)), ("Discover", ("/comparison",)), ("Backtest/Paper", ("/operations",)))


def test_command_palette_preserves_workspace_order() -> None:
    commands = all_commands(PAGES, GROUPS)

    assert [(item.route, item.workspace) for item in commands] == [
        ("/", "Home"),
        ("/comparison", "Discover"),
        ("/operations", "Backtest/Paper"),
    ]


def test_command_palette_searches_titles_routes_and_workspace_names() -> None:
    assert [item.route for item in search_commands(PAGES, GROUPS, "comparison")] == ["/comparison"]
    assert [item.route for item in search_commands(PAGES, GROUPS, "  CoMpArIsOn  ")] == ["/comparison"]
    assert [item.route for item in search_commands(PAGES, GROUPS, "paper")] == ["/operations"]
    assert [item.route for item in search_commands(PAGES, GROUPS, "/")] == ["/", "/comparison", "/operations"]
    assert search_commands(PAGES, GROUPS, "missing") == ()


def test_command_palette_limits_results_deterministically() -> None:
    assert len(search_commands(PAGES, GROUPS, "", limit=2)) == 2
    assert search_commands(PAGES, GROUPS, "", limit=0) == ()
