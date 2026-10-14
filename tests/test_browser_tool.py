"""The opt-in `browser` MCP tool over the hypruse-browser bridge, with the client faked."""

import asyncio
import importlib

import pytest

import hypruse.browser
from hypruse import server as srv


class FakeClient:
    calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def tabs(self):
        FakeClient.calls.append(("tabs",))
        return [{"id": 7, "active": True}]

    def snapshot(self, tab_id=None, *, max=120, settle_ms=0):
        FakeClient.calls.append(("snapshot", tab_id, max, settle_ms))
        return {"snapshot_id": "s1-x", "elements": []}

    def top_sites(self):
        FakeClient.calls.append(("top_sites",))
        return []

    def open(self, url, where="new"):
        FakeClient.calls.append(("open", url, where))
        return 9

    def click(self, snapshot_id, element_id):
        FakeClient.calls.append(("click", snapshot_id, element_id))

    def type(self, snapshot_id, element_id, text, *, submit=False):
        FakeClient.calls.append(("type", snapshot_id, element_id, text, submit))

    def scroll(self, direction, tab_id=None):
        FakeClient.calls.append(("scroll", direction, tab_id))
        return {"scroll_y": 100, "scroll_height": 900}

    def activate(self, tab_id):
        FakeClient.calls.append(("activate", tab_id))

    def close_tab(self, tab_id):
        FakeClient.calls.append(("close", tab_id))

    def history(self, tab_id, direction):
        FakeClient.calls.append(("history", tab_id, direction))


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(hypruse.browser, "BrowserClient", FakeClient)
    monkeypatch.setattr(srv.safety, "touch", lambda *a: None)
    monkeypatch.delenv("HYPRUSE_DRYRUN", raising=False)


def test_observe_actions_return_the_bridge_data():
    assert srv.browser("tabs") == [{"id": 7, "active": True}]
    assert srv.browser("snapshot", settle_ms=500)["snapshot_id"] == "s1-x"
    assert srv.browser("top_sites") == []
    assert FakeClient.calls == [("tabs",), ("snapshot", None, 120, 500), ("top_sites",)]


def test_act_actions_reach_the_client_with_their_arguments():
    assert "9" in srv.browser("open", url="https://example.com/", where="current")
    srv.browser("click", snapshot_id="s1-x", element_id="e3")
    srv.browser("type", snapshot_id="s1-x", element_id="e4", text="zażółć", submit=True)
    assert srv.browser("scroll", direction="bottom", tab_id=7)["scroll_y"] == 100
    srv.browser("activate", tab_id=7)
    srv.browser("back", tab_id=7)
    srv.browser("forward", tab_id=7)
    srv.browser("close", tab_id=7)
    assert FakeClient.calls == [
        ("open", "https://example.com/", "current"),
        ("click", "s1-x", "e3"),
        ("type", "s1-x", "e4", "zażółć", True),
        ("scroll", "bottom", 7),
        ("activate", 7),
        ("history", 7, "back"),
        ("history", 7, "forward"),
        ("close", 7),
    ]


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"action": "reload"}, "unknown action"),
        ({"action": "close"}, "needs tab_id"),
        ({"action": "back"}, "needs tab_id"),
        ({"action": "open"}, "needs url"),
        ({"action": "click", "snapshot_id": "s1-x"}, "needs snapshot_id and element_id"),
        ({"action": "type", "snapshot_id": "s1-x", "element_id": "e4"}, "needs text"),
    ],
)
def test_bad_arguments_are_refused_before_the_bridge(kwargs, message):
    with pytest.raises(ValueError, match=message):
        srv.browser(**kwargs)
    assert FakeClient.calls == []


def test_read_only_mode_observes_but_refuses_to_act(monkeypatch):
    monkeypatch.setattr(srv, "READONLY", True)
    assert srv.browser("tabs")
    with pytest.raises(ValueError, match="read-only"):
        srv.browser("click", snapshot_id="s1-x", element_id="e3")
    assert FakeClient.calls == [("tabs",)]


def test_dry_run_rehearses_without_reaching_the_bridge(monkeypatch):
    monkeypatch.setenv("HYPRUSE_DRYRUN", "1")
    assert srv.browser("type", snapshot_id="s1-x", element_id="e4", text="abc").startswith(
        srv._DRY
    )
    assert FakeClient.calls == []


@pytest.fixture
def reloaded(monkeypatch):
    def _with_env(browser: str | None, readonly: str | None):
        for name, value in (("HYPRUSE_BROWSER", browser), ("HYPRUSE_READONLY", readonly)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        return importlib.reload(srv)

    yield _with_env
    monkeypatch.delenv("HYPRUSE_BROWSER", raising=False)
    monkeypatch.delenv("HYPRUSE_READONLY", raising=False)
    importlib.reload(srv)


def _tools(module):
    return {t.name: t for t in asyncio.run(module.mcp.list_tools())}


def test_the_tool_exists_only_when_opted_in(reloaded):
    assert "browser" not in _tools(reloaded(None, None))
    tool = _tools(reloaded("1", None))["browser"]
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.openWorldHint is True


def test_read_only_mode_registers_it_as_an_observation_tool(reloaded):
    tool = _tools(reloaded("1", "1"))["browser"]
    assert tool.annotations.readOnlyHint is True
