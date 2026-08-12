"""auth/jwks.py — JWKS key cache for Security module JWT verification.

Fetches the Security module JWKS endpoint once and caches keys by `kid`.
Thread-safe lazy refresh on cache miss or TTL expiry.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx
from jose import jwk  # type: ignore[import]
from jose.backends.base import Key  # type: ignore[import]

logger = logging.getLogger(__name__)

_TTL_SECONDS = 3600  # Refresh keys at most once per hour


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
        """Return the public Key for *kid*, refreshing if needed."""
        with self._lock:
            if kid in self._keys and not self._is_stale():
                return self._keys[kid]
            self._refresh()
            return self._keys.get(kid)

    def _is_stale(self) -> bool:
        return (time.monotonic() - self._fetched_at) > _TTL_SECONDS

    def _refresh(self) -> None:
        """Fetch JWKS and rebuild the key map.  Must be called under _lock."""
        try:
            resp = httpx.get(self._url, timeout=5.0)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except Exception as exc:
            logger.warning("jwks_refresh_failed", extra={"url": self._url, "error": str(exc)})
            return  # keep stale keys rather than clearing on transient error

        new_keys: dict[str, Key] = {}
        for key_data in data.get("keys", []):
            kid = key_data.get("kid", "")
            try:
                new_keys[kid] = jwk.construct(key_data)
            except Exception as exc:
                logger.warning("jwks_key_construct_failed", extra={"kid": kid, "error": str(exc)})
        self._keys = new_keys
        self._fetched_at = time.monotonic()
        logger.info("jwks_refreshed", extra={"key_count": len(new_keys)})


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
