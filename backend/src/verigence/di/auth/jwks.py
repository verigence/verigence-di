"""auth/jwks.py — JWKS key cache for Security module JWT verification.

Fetches the Security module JWKS endpoint once and caches keys by `kid`.
Thread-safe lazy refresh on cache miss or TTL expiry.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import structlog
from jose import jwk  # type: ignore[import]
from jose.backends.base import Key  # type: ignore[import]

from verigence.di.runtime_errors import correlation_headers, safe_exception_context

logger = structlog.get_logger(__name__)

_TTL_SECONDS = 3600  # Refresh keys at most once per hour


class JWKSUnavailableError(RuntimeError):
    """The Security JWKS could not be fetched and no usable key is cached.

    This is a dependency outage, not an invalid token: callers must answer 503,
    never 401.
    """


class JWKSCache:
    """Thread-safe in-process cache for Clerk JWKS public keys.

    Keys are indexed by `kid` (Key ID).  On a cache miss the
    endpoint is re-fetched once; stale keys are refreshed after TTL.
    """

    def __init__(self, jwks_url: str) -> None:
        self._url = jwks_url
        self._lock = threading.Lock()
        self._keys: dict[str, Key] = {}
        self._fetched_at: float = 0.0

    def get_key(self, kid: str) -> Key | None:
        """Return the public Key for *kid*, refreshing if needed.

        Returns ``None`` when the JWKS was fetched but does not contain *kid*
        (an invalid token). Raises ``JWKSUnavailableError`` when the JWKS could
        not be fetched and *kid* is not cached.
        """
        with self._lock:
            if kid in self._keys and not self._is_stale():
                return self._keys[kid]
            refreshed = self._refresh()
            key = self._keys.get(kid)
            if refreshed:
                return key
            if key is not None:
                logger.warning(
                    "jwks_stale_keys_in_use",
                    reason="refresh_failed",
                    key_count=len(self._keys),
                    stale_seconds=round(time.monotonic() - self._fetched_at),
                )
                return key
            raise JWKSUnavailableError("Security JWKS is unavailable")

    def _is_stale(self) -> bool:
        return (time.monotonic() - self._fetched_at) > _TTL_SECONDS

    def _refresh(self) -> bool:
        """Fetch JWKS and rebuild the key map.  Must be called under _lock.

        Returns False (keeping any previously cached keys) on a fetch failure.
        """
        try:
            resp = httpx.get(self._url, timeout=5.0, headers=correlation_headers())
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except Exception as exc:
            status_code = (
                exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            )
            logger.warning(
                "jwks_refresh_failed",
                reason="http_status" if status_code is not None else "fetch_failed",
                http_status=status_code,
                cached_key_count=len(self._keys),
                **safe_exception_context(exc),
            )
            return False  # keep stale keys rather than clearing on transient error

        new_keys: dict[str, Key] = {}
        for key_data in data.get("keys", []):
            kid = key_data.get("kid", "")
            try:
                new_keys[kid] = jwk.construct(key_data)
            except Exception as exc:
                logger.warning(
                    "jwks_key_construct_failed",
                    kid=str(kid)[:64],
                    **safe_exception_context(exc),
                )
        self._keys = new_keys
        self._fetched_at = time.monotonic()
        logger.info("jwks_refreshed", key_count=len(new_keys))
        return True


# Module-level singleton — instantiated lazily in get_jwks_cache()
_cache: JWKSCache | None = None
_cache_lock = threading.Lock()


def get_jwks_cache() -> JWKSCache:
    """Return (or create) the process-level JWKS cache."""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                from verigence.di.settings import get_settings
                settings = get_settings()
                _cache = JWKSCache(jwks_url=settings.security_jwks_url)
    return _cache
