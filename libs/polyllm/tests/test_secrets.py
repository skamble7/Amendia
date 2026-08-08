# tests/test_secrets.py
"""CompositeSecretProvider routes by ref scheme and surfaces the REAL cause on a miss — a wrong-scheme
provider (e.g. FileSecretProvider given an ``env:`` ref) must never mask "the value simply isn't set"."""
import pytest

from polyllm.secrets import (
    CompositeSecretProvider,
    EnvSecretProvider,
    FileSecretProvider,
    LiteralSecretProvider,
    default_secret_provider,
)


def _composite():
    return default_secret_provider()  # (Literal, Env, File)


def test_env_ref_resolves_when_set(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "s3cr3t")
    assert _composite().get("env:MY_TOKEN") == "s3cr3t"


def test_literal_ref_resolves():
    assert _composite().get("literal:abc123") == "abc123"


def test_unset_env_ref_gives_clear_error_not_filesecretprovider_message(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    with pytest.raises(ValueError) as ei:
        _composite().get("env:AWS_ACCESS_KEY_ID")
    msg = str(ei.value)
    # names the ref + the real cause…
    assert "env:AWS_ACCESS_KEY_ID" in msg and "did not resolve" in msg
    # …and NOT the misleading wrong-scheme message that used to surface
    assert "only supports file:*" not in msg


def test_unknown_scheme_is_named_clearly():
    with pytest.raises(ValueError) as ei:
        _composite().get("vault:secret/foo#bar")
    assert "unknown secret scheme 'vault:'" in str(ei.value)


def test_malformed_ref_rejected():
    with pytest.raises(ValueError):
        _composite().get("no-scheme-here")


def test_file_ref_missing_key_reports_file_source(tmp_path):
    f = tmp_path / "secrets.json"
    f.write_text('{"PRESENT": "v"}')
    comp = CompositeSecretProvider(providers=(LiteralSecretProvider(), EnvSecretProvider(), FileSecretProvider()))
    assert comp.get(f"file:{f}#PRESENT") == "v"
    with pytest.raises(ValueError) as ei:
        comp.get(f"file:{f}#ABSENT")
    msg = str(ei.value)
    assert "did not resolve" in msg and "'file'" in msg
