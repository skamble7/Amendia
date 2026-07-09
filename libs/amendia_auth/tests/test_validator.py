# tests/test_validator.py
"""TokenValidator: happy path, iss/aud/exp rejection, alg-confusion, and the
unknown-kid → single-refresh rotation path."""
from __future__ import annotations

import jwt
import pytest

from amendia_auth.errors import AuthError
from amendia_auth.validator import TokenValidator

from .conftest import AUDIENCE, ISSUER


async def test_valid_token_yields_principal(validator, idp):
    token = idp.mint("k1", sub="kc-123", email="riya@bank.test", name="Riya")
    principal = await validator.validate(token)
    assert principal.iss == ISSUER
    assert principal.sub == "kc-123"
    assert principal.email == "riya@bank.test"
    assert principal.name == "Riya"
    assert principal.raw_claims["aud"] == AUDIENCE


async def test_wrong_issuer_rejected(validator, idp):
    token = idp.mint("k1", iss="https://evil.test/realms/x")
    with pytest.raises(AuthError) as exc:
        await validator.validate(token)
    assert exc.value.reason == "wrong_issuer"


async def test_wrong_audience_rejected(validator, idp):
    token = idp.mint("k1", aud="some-other-api")
    with pytest.raises(AuthError) as exc:
        await validator.validate(token)
    assert exc.value.reason == "wrong_audience"


async def test_expired_rejected(validator, idp):
    token = idp.mint("k1", exp_delta=-3600, nbf_delta=-7200)
    with pytest.raises(AuthError) as exc:
        await validator.validate(token)
    assert exc.value.reason == "expired"


async def test_alg_none_rejected(validator):
    token = jwt.encode({"iss": ISSUER, "sub": "x", "aud": AUDIENCE}, key="", algorithm="none")
    with pytest.raises(AuthError) as exc:
        await validator.validate(token)
    assert exc.value.reason.startswith("unsupported_alg")


async def test_hs256_confusion_rejected(validator):
    token = jwt.encode(
        {"iss": ISSUER, "sub": "x", "aud": AUDIENCE}, key="shared-secret", algorithm="HS256"
    )
    with pytest.raises(AuthError) as exc:
        await validator.validate(token)
    assert exc.value.reason.startswith("unsupported_alg")


async def test_unknown_kid_triggers_single_refresh(validator, idp):
    # Prime the cache with k1.
    await validator.validate(idp.mint("k1"))
    calls_before = idp.jwks_calls
    # IdP rotates: a new key k2 appears, a token is signed with it.
    idp.add_key("k2")
    token = idp.mint("k2")
    principal = await validator.validate(token)
    assert principal.sub == "kc-sub-riya"
    # Exactly one extra JWKS fetch happened (the rotation refresh).
    assert idp.jwks_calls == calls_before + 1


async def test_unknown_kid_after_refresh_still_fails(validator, idp):
    await validator.validate(idp.mint("k1"))
    # Sign with a key that the IdP then retires, so even a refresh can't find it.
    idp.add_key("k3")
    token = idp.mint("k3")
    idp.drop_keys()
    idp.add_key("k1")
    with pytest.raises(AuthError) as exc:
        await validator.validate(token)
    assert exc.value.reason == "unknown_kid"


async def test_explicit_jwks_uri_skips_discovery(idp):
    # Compose footgun: validate iss against the browser-facing issuer but fetch
    # keys from an explicit (internal) JWKS URL, never touching discovery.
    from amendia_auth.settings import AuthSettings
    from amendia_auth.validator import TokenValidator

    settings = AuthSettings(issuer=ISSUER, audience=AUDIENCE, jwks_uri=idp.jwks_uri, leeway_seconds=10)
    v = TokenValidator(settings, http_client_factory=idp.client_factory())
    principal = await v.validate(idp.mint("k1"))
    assert principal.iss == ISSUER
    assert idp.discovery_calls == 0  # discovery bypassed
    assert idp.jwks_calls == 1


async def test_jwks_cached_across_calls(validator, idp):
    await validator.validate(idp.mint("k1"))
    first = idp.jwks_calls
    await validator.validate(idp.mint("k1"))
    await validator.validate(idp.mint("k1"))
    assert idp.jwks_calls == first  # no extra fetches while cache is fresh
