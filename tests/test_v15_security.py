"""Tests for security improvements: shell injection prevention, risk weights."""
from __future__ import annotations

from hx.policy import command_allowed, risk_weights
from hx.templates import policy_toml


def _minimal_policy(**overrides: object) -> dict:
    import tomllib

    base = tomllib.loads(policy_toml())
    base.update(overrides)
    return base


class TestCommandAllowedRejectsShellInjection:
    """command_allowed must reject shell operators to prevent injection."""

    def test_rejects_semicolon(self) -> None:
        policy = _minimal_policy()
        assert command_allowed(policy, "pytest; rm -rf /") is False

    def test_rejects_pipe(self) -> None:
        policy = _minimal_policy()
        assert command_allowed(policy, "pytest | cat") is False

    def test_rejects_double_ampersand(self) -> None:
        policy = _minimal_policy()
        assert command_allowed(policy, "pytest && rm -rf /") is False

    def test_rejects_double_pipe(self) -> None:
        policy = _minimal_policy()
        assert command_allowed(policy, "pytest || true") is False

    def test_rejects_backtick(self) -> None:
        policy = _minimal_policy()
        assert command_allowed(policy, "pytest `whoami`") is False

    def test_rejects_dollar_paren(self) -> None:
        policy = _minimal_policy()
        assert command_allowed(policy, "pytest $(whoami)") is False

    def test_allows_clean_command(self) -> None:
        policy = _minimal_policy()
        assert command_allowed(policy, "pytest -q tests/") is True

    def test_allows_exact_prefix(self) -> None:
        policy = _minimal_policy()
        assert command_allowed(policy, "ruff") is True


class TestRiskWeightsConfigurable:
    """Risk weights can be configured via policy."""

    def test_default_weights(self) -> None:
        w = risk_weights({})
        assert w == {"entropy": 0.35, "churn": 0.25, "pressure": 0.25, "failures": 0.15}

    def test_policy_override(self) -> None:
        w = risk_weights({"risk_weights": {"entropy": 0.5, "churn": 0.1}})
        assert w["entropy"] == 0.5
        assert w["churn"] == 0.1
        assert w["pressure"] == 0.25  # default preserved
