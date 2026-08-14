"""Plugin discovery.

Walks the ``app.plugins`` package and returns the manifest of each installed
plugin. Discovery is by presence: a plugin is whatever subpackage sits under
app/plugins and exposes a MANIFEST dict. There is no database — installing a
plugin means its package is importable, mirroring the edition check's
"absence is the gate" design.

Robustness: a plugin that fails to import or has a malformed manifest is skipped
(and logged), never raised. The capabilities endpoint is public and must not be
brought down by one bad third-party plugin.
"""
import importlib
import logging
import pkgutil
from functools import lru_cache
from typing import List, Optional

logger = logging.getLogger(__name__)


class PluginManifest:
    """Normalized view of a plugin's MANIFEST."""

    __slots__ = ("name", "version", "capabilities", "enabled")

    def __init__(self, name: str, version: str, capabilities: List[str], enabled: bool):
        self.name = name
        self.version = version
        self.capabilities = capabilities
        self.enabled = enabled


def _coerce(raw: dict, package_name: str) -> Optional[PluginManifest]:
    """Validate a raw MANIFEST dict. Returns None (and logs) if unusable."""
    if not isinstance(raw, dict):
        logger.warning("Plugin %s: MANIFEST is not a dict; skipping", package_name)
        return None
    name = raw.get("name")
    version = raw.get("version")
    if not name or not isinstance(name, str):
        logger.warning("Plugin %s: MANIFEST missing a string 'name'; skipping", package_name)
        return None
    if not version or not isinstance(version, str):
        logger.warning("Plugin %s: MANIFEST missing a string 'version'; skipping", name)
        return None
    caps = raw.get("capabilities", [])
    if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
        logger.warning("Plugin %s: 'capabilities' must be a list of strings; ignoring", name)
        caps = []
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        enabled = True
    return PluginManifest(name=name, version=version, capabilities=caps, enabled=enabled)


def _discover_uncached() -> List[PluginManifest]:
    try:
        import app.plugins as plugins_pkg
    except Exception:  # noqa: BLE001 — no plugins package is a valid, empty state
        logger.debug("app.plugins is not importable; no plugins discovered")
        return []

    found: dict[str, PluginManifest] = {}
    for mod in pkgutil.iter_modules(plugins_pkg.__path__):
        if not mod.ispkg:
            continue  # only subpackages are plugins
        pkg_name = f"app.plugins.{mod.name}"
        try:
            module = importlib.import_module(pkg_name)
        except Exception:  # noqa: BLE001 — one broken plugin must not break the rest
            logger.exception("Plugin %s failed to import; skipping", pkg_name)
            continue
        raw = getattr(module, "MANIFEST", None)
        if raw is None:
            logger.warning("Plugin %s has no MANIFEST; skipping", pkg_name)
            continue
        manifest = _coerce(raw, pkg_name)
        if manifest is None:
            continue
        if manifest.name in found:
            logger.warning(
                "Duplicate plugin name '%s' (from %s); keeping the first", manifest.name, pkg_name
            )
            continue
        found[manifest.name] = manifest

    return sorted(found.values(), key=lambda m: m.name)


@lru_cache(maxsize=1)
def _cached() -> tuple:
    # Cache as an immutable tuple; the plugin set is fixed for a process lifetime
    # (installing a plugin is a deploy, not a runtime action).
    return tuple(_discover_uncached())


def discover(*, use_cache: bool = True) -> List[PluginManifest]:
    """Return the installed plugins' manifests. Cached per process by default."""
    if use_cache:
        return list(_cached())
    return _discover_uncached()


def clear_cache() -> None:
    """Drop the discovery cache (tests that install a temporary plugin use this)."""
    _cached.cache_clear()
