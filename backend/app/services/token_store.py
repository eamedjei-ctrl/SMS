"""Revoked-token registry.

Redis is the fast path. Redis is a cache, never a source of truth -- so when it
is unavailable the refresh-session table in PostgreSQL still governs whether a
session is alive, and the platform degrades in speed only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app

_client = None
_client_failed = False


def _redis():
    global _client, _client_failed
    if _client is not None or _client_failed:
        return _client
    try:
        import redis

        url = current_app.config["REDIS_URL"]
        db_index = current_app.config["REDIS_SESSION_DB"]
        _client = redis.Redis.from_url(f"{url}/{db_index}", socket_connect_timeout=1)
        _client.ping()
    except Exception:  # redis missing or unreachable -- degrade, do not fail
        _client_failed = True
        _client = None
    return _client


def _key(jti: str) -> str:
    env = current_app.config["ENV_NAME"]
    return f"{env}:v1:session:blacklist:{jti}"


def revoke(jti: str, ttl_seconds: int) -> None:
    if not jti:
        return
    client = _redis()
    if client is None:
        return
    try:
        client.setex(_key(jti), max(ttl_seconds, 1), "1")
    except Exception:
        pass


def is_revoked(jti: str) -> bool:
    if not jti:
        return False
    client = _redis()
    if client is None:
        return False
    try:
        return bool(client.exists(_key(jti)))
    except Exception:
        return False


def revoke_access_token(claims: dict) -> None:
    exp = claims.get("exp")
    if not exp:
        return
    remaining = int(exp - datetime.now(timezone.utc).timestamp())
    if remaining > 0:
        revoke(claims.get("jti", ""), remaining)


def reset_client() -> None:
    """Test helper -- forget the cached connection."""
    global _client, _client_failed
    _client = None
    _client_failed = False
