"""Plugin packages.

A plugin is a subpackage of ``app.plugins`` that exposes a module-level
``MANIFEST`` dict describing itself:

    # app/plugins/example/__init__.py
    MANIFEST = {
        "name": "example",           # required, unique, machine key
        "version": "1.0.0",          # required
        "capabilities": ["demo"],    # optional list of capability strings
        "enabled": True,             # optional, default True
    }

Discovery is by PRESENCE — installing a plugin means its package is importable
here; there is no registry table to keep in sync (the same "absence is the gate"
principle the edition check uses). See app.services.plugin_registry.

This package intentionally ships empty in the base build. Plugins are added by
dropping a subpackage in beside this file.
"""
