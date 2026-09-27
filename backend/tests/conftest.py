import pytest

AGENT_ONLINE = {"online": True, "provider": "anthropic", "model": "claude-opus-5", "name": "Claude Opus 5"}


@pytest.fixture(autouse=True)
def agent_status(monkeypatch):
    """The sidebar shows agent status on every page; don't call the network for it."""
    status = dict(AGENT_ONLINE)
    monkeypatch.setattr("pivend.web.context_processors.cached_agent_health", lambda: status)
    return status
