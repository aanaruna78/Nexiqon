from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib.metadata import EntryPoint, entry_points
from typing import Any

import jsonschema

from nexiqon_sdk.manifest import Manifest, PluginKind

GROUP = "nexiqon.plugins"


class PluginError(Exception):
    pass


class Registry:
    def __init__(self) -> None:
        self._plugins: dict[tuple[PluginKind, str], Any] = {}

    def register(self, plugin: Any) -> None:
        manifest = getattr(plugin, "manifest", None)
        if not isinstance(manifest, Manifest):
            raise PluginError(f"{plugin!r} has no Manifest")
        key = (manifest.kind, manifest.name)
        if key in self._plugins:
            raise PluginError(f"duplicate {manifest.kind} plugin {manifest.name!r}")
        jsonschema.Draft202012Validator.check_schema(manifest.config_schema)
        self._plugins[key] = plugin

    def discover(self, group: str = GROUP, eps: list[EntryPoint] | None = None) -> list[str]:
        """Load plugins from installed packages' entry points. Returns loaded plugin names."""
        loaded: list[str] = []
        for ep in eps if eps is not None else list(entry_points(group=group)):
            obj = ep.load()
            produced = obj() if callable(obj) and not hasattr(obj, "manifest") else obj
            for plugin in produced if isinstance(produced, list | tuple) else [produced]:
                self.register(plugin)
                loaded.append(plugin.manifest.name)
        return loaded

    def get(self, kind: PluginKind, name: str) -> Any:
        try:
            return self._plugins[(kind, name)]
        except KeyError:
            raise PluginError(f"no {kind} plugin named {name!r}") from None

    def manifests(self, kind: PluginKind | None = None) -> list[Manifest]:
        return sorted(
            (p.manifest for (k, _), p in self._plugins.items() if kind is None or k == kind),
            key=lambda m: (m.kind, m.name),
        )

    def parser_for(self, media_type: str, uri: str) -> Any:
        """Pick a parser by media type, then by file extension."""
        media = media_type.split(";")[0].strip().lower()
        parsers = [p for (k, _), p in self._plugins.items() if k == PluginKind.PARSER]
        for p in parsers:
            if media in p.manifest.media_types:
                return p
        path = uri.split("?", 1)[0].lower()
        for p in parsers:
            if any(path.endswith(ext) for ext in p.manifest.extensions):
                return p
        return None

    def validate_config(self, kind: PluginKind, name: str, config: Mapping[str, Any]) -> list[str]:
        plugin = self.get(kind, name)
        validator = jsonschema.Draft202012Validator(plugin.manifest.config_schema)
        return [
            f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in sorted(
                validator.iter_errors(dict(config)), key=lambda e: list(e.absolute_path)
            )
        ]


PluginFactory = Callable[[], Any]
