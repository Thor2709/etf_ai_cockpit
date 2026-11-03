"""Exercise SDK-facing annotations without importing the optional MCP SDK."""

from __future__ import annotations

from dataclasses import replace
import inspect
from typing import get_type_hints

import pytest

from etf_cockpit.mcp import http, server
from etf_cockpit.mcp.errors import MCPServerUnavailable
from etf_cockpit.mcp.registry import CallContext
from etf_cockpit.mcp.tiers import KNOWN_TIERS


@pytest.fixture
def stub_sdk(monkeypatch: pytest.MonkeyPatch):
    class StubServer:
        def __init__(self, *args, **kwargs):
            self.tools = {}

        def add_tool(self, function, *, name, **kwargs):
            self.tools[name] = function

        def resource(self, *args, **kwargs):
            return lambda function: function

        def prompt(self, *args, **kwargs):
            return lambda function: function

    monkeypatch.setattr(server, "_load_sdk", lambda: (StubServer, RuntimeError, dict))
    monkeypatch.setattr(server, "start_server_worker", lambda *args: None)
    monkeypatch.setattr(http, "_access_token_getter", lambda: lambda: None)


@pytest.fixture
def registered_wrappers(stub_sdk):
    specs = server.list_tools(profile="full", tiers=KNOWN_TIERS)
    assert specs
    instance = server.create_server(profile="full", tiers=KNOWN_TIERS, session=object())
    assert set(instance.tools) == {spec.name for spec in specs}
    context = CallContext(profile="full", enabled_tiers=KNOWN_TIERS)
    return [
        (spec, wrapper)
        for spec in specs
        for wrapper in (
            instance.tools[spec.name],
            http._tool_handler(spec, template=context, grants={}, tool_error=RuntimeError),
        )
    ]


def test_full_profile_wrapper_annotations_resolve(registered_wrappers) -> None:
    for spec, wrapper in registered_wrappers:
        expected = get_type_hints(spec.function, include_extras=True) | {"return": spec.output_model}
        assert get_type_hints(wrapper, include_extras=True) == expected, spec.name
        assert wrapper.__annotations__ == expected, spec.name
        assert not any(isinstance(value, str) for value in wrapper.__annotations__.values()), spec.name
        original = inspect.signature(spec.function)
        signature = inspect.signature(wrapper)
        assert signature.return_annotation is spec.output_model, spec.name
        assert tuple(signature.parameters) == tuple(original.parameters), spec.name
        for name, parameter in signature.parameters.items():
            assert not isinstance(parameter.annotation, str), (spec.name, name)
            assert parameter == original.parameters[name].replace(
                annotation=expected.get(name, original.parameters[name].annotation)
            ), (spec.name, name)


def test_full_profile_wrapper_signatures_build_pydantic_models(registered_wrappers) -> None:
    pydantic = pytest.importorskip("pydantic", reason="Pydantic is required to validate SDK argument schemas")
    for spec, wrapper in registered_wrappers:
        fields = {
            name: (
                parameter.annotation,
                ... if parameter.default is inspect.Parameter.empty else parameter.default,
            )
            for name, parameter in inspect.signature(wrapper).parameters.items()
        }
        model = pydantic.create_model(f"{spec.name}Arguments", **fields)
        # Schema generation forces resolution; create_model alone can leave an incomplete model.
        assert model.model_json_schema()["type"] == "object", spec.name


def test_unresolvable_annotation_refuses_server_startup(stub_sdk, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_tool(start: MissingToolDate) -> dict:  # noqa: F821
        raise AssertionError("Startup must never invoke a tool")

    original = server.list_tools(profile="full", tiers=KNOWN_TIERS)[0]
    spec = replace(original, name="broken_annotation_tool", function=broken_tool)
    monkeypatch.setattr(server, "list_tools", lambda **kwargs: (spec,))
    workers_started = []
    monkeypatch.setattr(server, "start_server_worker", lambda *args: workers_started.append(args))

    with pytest.raises(MCPServerUnavailable, match="broken_annotation_tool") as error:
        server.create_server(profile="full", tiers=KNOWN_TIERS, session=object())
    assert isinstance(error.value.__cause__, NameError)
    assert workers_started == []

    with pytest.raises(MCPServerUnavailable, match="broken_annotation_tool") as error:
        http._tool_handler(spec, template=CallContext(), grants={}, tool_error=RuntimeError)
    assert isinstance(error.value.__cause__, NameError)
