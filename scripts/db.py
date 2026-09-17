"""Project scripts re-use core database helpers."""

from core.db import connect, execute, fetch, scalar_value

__all__ = ["connect", "execute", "fetch", "scalar_value"]
