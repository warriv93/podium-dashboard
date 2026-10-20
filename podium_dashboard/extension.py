"""The run's orchestrator extension: the .py file podium.json's `orchestrator.extension` names.

It may define COMMANDS ({verb: fn(p, args)}), ACTIONS (extra request actions), prompt(p, kind, target_id),
on_asana_refresh(p, task_json) and SYNC_MAJOR(event). Every helper here takes the module or None.
"""
import importlib.util
import os
import sys

CORE_ACTIONS = {"assign", "plan", "build-all", "stop", "confirm", "reverse", "domain-story"}
MODULE = "podium_extension"
_loaded = {}


def path_of(p):
    """The extension's absolute path, None when the run names none; `~` expands, and a relative path is relative to
    the folder holding podium.json."""
    orchestrator = p.data.get("orchestrator")
    ext = orchestrator.get("extension") if isinstance(orchestrator, dict) else None
    if not ext:
        return None
    return os.path.normpath(os.path.join(p.dir, os.path.expanduser(str(ext))))


def load(p):
    """(module, None), or (None, None) when the run names no extension, or (None, why) when it does not load, `why`
    reading `extension <path> not loadable: <reason>`. A module loads once per path and modification time."""
    path = path_of(p)
    if not path:
        return None, None
    try:
        key = (os.path.realpath(path), os.stat(path).st_mtime_ns)
        if key not in _loaded:
            spec = importlib.util.spec_from_file_location(MODULE, path)
            if spec is None or spec.loader is None:
                raise ImportError("not a Python file")
            module = importlib.util.module_from_spec(spec)
            sys.modules[MODULE] = module  # dataclasses and pickle look a module up by name while it runs
            try:
                spec.loader.exec_module(module)
            except BaseException:
                sys.modules.pop(MODULE, None)
                raise
            _loaded[key] = module
        return _loaded[key], None
    except FileNotFoundError:
        return None, f"extension {path} not loadable: no such file"
    except (Exception, SystemExit) as e:
        return None, f"extension {path} not loadable: {type(e).__name__}: {e}"


def commands(module):
    found = getattr(module, "COMMANDS", None)
    return found if isinstance(found, dict) else {}


def actions(module):
    """The request actions the server accepts: the core's and the extension's ACTIONS."""
    extra = getattr(module, "ACTIONS", None)
    return CORE_ACTIONS | (set(extra) if isinstance(extra, (set, frozenset, list, tuple)) else set())


def hook(module, name):
    found = getattr(module, name, None)
    return found if callable(found) else None


def prompt(module):
    return hook(module, "prompt")


def on_asana_refresh(module):
    return hook(module, "on_asana_refresh")


def sync_major(module):
    return hook(module, "SYNC_MAJOR")
