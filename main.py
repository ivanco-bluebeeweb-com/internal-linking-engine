"""Entry point for the web core and CLI (`imperal validate` / `build`).

Prepares sys.path, clears the module cache, and imports every layer so their
decorators register on ONE Extension instance. The cache clear matters
because the validator can load several extensions in one process: a stale
cached module here would mean "tools never registered".
"""

import os
import sys

_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
if _EXT_DIR not in sys.path:
    sys.path.insert(0, _EXT_DIR)

_LOCAL = (
    "app", "schemas", "storage", "relevance",
    "handlers_settings", "handlers_index", "handlers_relevance", "handlers_plans",
    "panels", "expose",
)
for _mod in _LOCAL:
    sys.modules.pop(_mod, None)

from app import ext, chat  # noqa: E402,F401
import handlers_settings  # noqa: E402,F401
import handlers_index  # noqa: E402,F401
import handlers_relevance  # noqa: E402,F401
import handlers_plans  # noqa: E402,F401
import panels  # noqa: E402,F401
import expose  # noqa: E402,F401
