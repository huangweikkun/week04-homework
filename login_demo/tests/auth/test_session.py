"""login_demo 登录会话的单元测试。

规则来源：docs/session-rules.md（登录会话 20 分钟、now == expires_at 视为已过期）。
运行方式：python -m pytest tests/test_session.py -q
"""

from __future__ import annotations

import importlib

import pytest

from app import auth, config, session
from app.session import SESSION_TTL_SECONDS

BASE_NOW = 1_700_000_000


@pytest.fixture(autouse=True)
def clean_token_store():
    """每个用例都从一个空的令牌存储开始。"""
    auth._TOKEN_STORE.clear()
    yield
    auth._TOKEN_STORE.clear()


class TestSessionRules:
    def test_ttl_is_twenty_minutes(self):
        assert SESSION_TTL_SECONDS == 20 * 60

    def test_valid_before_expiry(self):
        assert session.is_session_valid(BASE_NOW, BASE_NOW + 1) is True

    def test_expire_boundary(self):
        # now == expires_at 属于已过期，有效条件必须是 now < expires_at
        assert session.is_session_valid(BASE_NOW, BASE_NOW) is False

    def test_expired_after_expiry(self):
        assert session.is_session_valid(BASE_NOW + 1, BASE_NOW) is False

    def test_refresh_extends_ttl(self):
        assert session.refresh_expiry(BASE_NOW) == BASE_NOW + 20 * 60

    def test_refresh_uses_default_ttl_not_config(self, monkeypatch):
        # config.SESSION_TTL_MINUTES 只是运维覆盖位，不能影响默认有效期
        monkeypatch.setenv("SESSION_TTL_MINUTES", "5")
        reloaded = importlib.reload(config)
        try:
            assert reloaded.SESSION_TTL_MINUTES == "5"
            assert session.refresh_expiry(BASE_NOW) == BASE_NOW + 20 * 60
            assert session.SESSION_TTL_SECONDS == 20 * 60
        finally:
            monkeypatch.delenv("SESSION_TTL_MINUTES", raising=False)
            importlib.reload(config)


class TestVerifyToken:
    def test_accepts_issued_token(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        assert auth.verify_token(token) is True

    def test_rejects_tampered_signature(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
        assert auth.verify_token(tampered) is False

    def test_rejects_tampered_user_id(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        _, rest = token.split(".", 1)
        assert auth.verify_token(f"mallory.{rest}") is False

    @pytest.mark.parametrize(
        "token",
        ["", "not-a-token", "a.b.c", "a.b.c.d.e"],
    )
    def test_rejects_malformed_token(self, token):
        assert auth.verify_token(token) is False


class TestIssueAndCheck:
    def test_issued_token_is_checkable(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        assert auth.check(token, now=BASE_NOW) is True

    def test_expire_at_returns_issued_expiry(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        assert auth.expire_at(token) == BASE_NOW + SESSION_TTL_SECONDS

    def test_expire_at_unknown_token(self):
        assert auth.expire_at("nobody.0.abc.def") is None

    def test_valid_just_before_expiry(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        assert auth.check(token, now=BASE_NOW + SESSION_TTL_SECONDS - 1) is True

    def test_invalid_at_expiry_boundary(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        assert auth.check(token, now=BASE_NOW + SESSION_TTL_SECONDS) is False

    def test_unknown_but_well_signed_token_is_invalid(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        auth._TOKEN_STORE.pop(token)
        assert auth.verify_token(token) is True
        assert auth.check(token, now=BASE_NOW) is False


class TestTouch:
    def test_touch_extends_expiry_from_now(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        later = BASE_NOW + 10 * 60
        assert auth.touch(token, now=later) == later + SESSION_TTL_SECONDS
        assert auth.expire_at(token) == later + SESSION_TTL_SECONDS

    def test_touch_keeps_session_valid(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        later = BASE_NOW + 10 * 60
        auth.touch(token, now=later)
        assert auth.check(token, now=later + 10 * 60) is True

    def test_touch_returns_none_for_unknown_token(self):
        assert auth.touch("nobody.0.abc.def", now=BASE_NOW) is None

    def test_touch_does_not_revive_expired_session(self):
        token = auth.issue_token("alice", now=BASE_NOW)
        assert auth.touch(token, now=BASE_NOW + SESSION_TTL_SECONDS) is None
        assert auth.expire_at(token) == BASE_NOW + SESSION_TTL_SECONDS


class TestPurgeExpired:
    def test_purges_only_expired_records(self):
        alive = auth.issue_token("alice", now=BASE_NOW)
        dead = auth.issue_token("bob", now=BASE_NOW)
        later = BASE_NOW + SESSION_TTL_SECONDS
        auth.touch(alive, now=later - 1)  # 到期前续期，逾期后再清理

        assert auth.purge_expired(now=later) == 1
        assert auth.check(alive, now=later) is True
        assert auth.check(dead, now=later) is False

    def test_returns_zero_when_nothing_expired(self):
        auth.issue_token("alice", now=BASE_NOW)
        assert auth.purge_expired(now=BASE_NOW) == 0
