"""Importing this package self-registers the builtin plugins."""

from __future__ import annotations

from . import builtin  # noqa: F401  (import triggers directive registration)
