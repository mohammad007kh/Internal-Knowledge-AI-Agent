"""conftest.py for connector unit tests.

Removes extra env vars that the root .env provides but are not declared in
Settings (which uses extra="forbid").  This allows the connectors module to be
imported without the full application database / Settings stack.
"""
from __future__ import annotations

import os

# These keys exist in the root .env (docker-compose config) but are NOT fields
# on src.core.config.Settings.  pydantic-settings uses extra="forbid" so they
# cause a ValidationError when Settings() is instantiated.  Removing them here
# (before any src import) keeps unit tests self-contained.
_EXTRA_KEYS = (
    "DB_USER",
    "DB_PASSWORD",
    "NEXT_PUBLIC_API_URL",
)
for _key in _EXTRA_KEYS:
    os.environ.pop(_key, None)
