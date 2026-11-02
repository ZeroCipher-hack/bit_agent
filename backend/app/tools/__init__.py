"""Auto-discovers every Tool subclass in this package."""
import importlib
import pkgutil

from .base import Tool, ToolContext, ToolError  # noqa: F401


def load_tools() -> dict[str, Tool]:
    registry: dict[str, Tool] = {}
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_") or mod.name == "base":
            continue
        module = importlib.import_module(f"{__name__}.{mod.name}")
        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, Tool) and obj is not Tool and obj.name:
                registry[obj.name] = obj()
    return registry
