import pytest

AGENT_ONLINE = {"online": True, "ok": True}


@pytest.fixture(autouse=True)
def agent_status(monkeypatch):
    """The sidebar shows agent status on every page; don't call the network for it."""
    status = dict(AGENT_ONLINE)
    monkeypatch.setattr("pivend.web.context_processors.cached_agent_health", lambda: status)
    return status


def connect_llm(user, provider="anthropic", model="claude-opus-5", api_key="sk-ant-user", **kwargs):
    from pivend.accounts.services import save_llm

    return save_llm(user, provider, model, kwargs.get("base_url", ""), api_key, kwargs.get("reasoning", False))


def connect_naver(user):
    from pivend.accounts.models import Credential
    from pivend.accounts.services import save_naver

    save_naver(user, Credential.Kind.NAVER_SEARCHAD, {"api_key": "ak", "secret_key": "sk", "customer_id": "1234567"})
    save_naver(user, Credential.Kind.NAVER_OPENAPI, {"client_id": "cid", "client_secret": "csecret"})
