# Plugin SDK

Connectors, parsers, chunkers and evaluators are **plugins**. A plugin is a Python object with a
**manifest**, installed as a normal package. The platform discovers it at start-up through an
entry point, so adding one changes no platform code. The SDK is the `nexiqon-sdk` package
(`nexiqon_sdk`).

| Kind | What it does | Loaded by |
|---|---|---|
| `connector` | Finds and fetches content from a source: a website, bucket or repository | Ingestion |
| `parser` | Turns a file into a title and ordered blocks (headings, paragraphs, lists, tables, code) | Ingestion |
| `chunker` | Splits blocks into passages for search | Ingestion |
| `evaluator` | Scores one evaluation case | Evaluation |

## The manifest

The manifest is what Studio shows in the connector gallery, and how a plugin's configuration is
validated:

```python
from nexiqon_sdk import Manifest, PluginKind

manifest = Manifest(
    name="intranet-wiki",  # lowercase, digits and dashes
    kind=PluginKind.CONNECTOR,
    version="1.0.0",
    title="Intranet wiki",
    description="Pages of the company wiki, with their access groups.",
    # JSON Schema (2020-12); Studio renders it as the source's settings form.
    config_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["base_url"],
        "properties": {
            "base_url": {"type": "string", "format": "uri", "title": "Wiki address"},
            "space": {"type": "string", "title": "Space"},
        },
    },
    capabilities=["discover", "incremental", "schedule"],
)
```

Parsers also declare their `media_types` and `extensions`.

## A connector

A connector **discovers** items, then **fetches** each one. Return a change token as `version`
(an ETag, a commit hash), so unchanged content is skipped on the next sync:

```python
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

from nexiqon_sdk import Content, ConnectorContext, Item


class IntranetWiki:
    manifest = manifest  # as above

    async def discover(
        self, ctx: ConnectorContext, config: Mapping[str, Any]
    ) -> AsyncIterator[Item]:
        r = await ctx.http.get(f"{config['base_url']}/api/pages?space={config.get('space', '')}")
        for page in json.loads(r.content)["pages"][: ctx.max_items]:
            yield Item(
                uri=page["url"], title=page["title"], version=page["etag"], media_type="text/html"
            )

    async def fetch(
        self,
        ctx: ConnectorContext,
        config: Mapping[str, Any],
        item: Item,
        previous_version: str | None,
    ) -> Content:
        if previous_version == item.version:
            return Content(uri=item.uri, not_modified=True)
        r = await ctx.http.get(item.uri)
        return Content(uri=item.uri, data=r.content, media_type="text/html", version=item.version)
```

**Rules for connectors:**

- **Use `ctx.http` for every request.** It is the platform's SSRF-safe client: it refuses private
  and internal addresses and pins the address it checked. A plugin must not open its own sockets.
- **Respect `ctx.max_items` and `ctx.max_bytes`.** The platform stops a run at those limits, and
  it never deletes content after an incomplete run.
- **Credentials come from configuration** that refers to the secret store. Never log them.

## A parser

```python
from nexiqon_sdk import Block, Manifest, ParsedDocument, PluginKind


class AsciidocParser:
    manifest = Manifest(
        name="asciidoc",
        kind=PluginKind.PARSER,
        title="AsciiDoc",
        media_types=["text/asciidoc"],
        extensions=[".adoc"],
        capabilities=["headings"],
    )

    def parse(self, data: bytes, media_type: str, uri: str) -> ParsedDocument:
        blocks = []
        for line in data.decode("utf-8", "replace").splitlines():
            if line.startswith("="):
                level = len(line) - len(line.lstrip("="))
                blocks.append(Block(kind="heading", text=line.lstrip("= ").strip(), level=level))
            elif line.strip():
                blocks.append(Block(kind="paragraph", text=line.strip()))
        return ParsedDocument(title=blocks[0].text if blocks else None, blocks=blocks)
```

Headings matter: they become the section path shown in citations ("Admin Guide › Teammates"), and
they let answers expand to whole sections.

## A chunker

A chunker takes blocks and returns `ChunkDraft`s, each with a text and a token count
(`nexiqon_sdk.estimate_tokens`). Set `uses_headings = True` to have the platform split by headings
first and call you once per section.

## An evaluator

An evaluator scores one case: an `EvalCase` (the question and what a right answer looks like)
against an `EvalObservation` (the answer, citations, latency and cost).

```python
from nexiqon_sdk import EvalCase, EvalObservation, Manifest, PluginKind, Score


class MentionsProduct:
    manifest = Manifest(
        name="mentions-product", kind=PluginKind.EVALUATOR, title="Names the product"
    )

    def applies(self, case: EvalCase) -> bool:
        return not case.must_abstain

    async def score(self, case: EvalCase, seen: EvalObservation, config) -> Score:
        ok = config.get("product", "").lower() in seen.answer.lower()
        return Score(
            value=1.0 if ok else 0.0, passed=ok, detail="" if ok else "The product is not named"
        )
```

Evaluators are deterministic by default. One that needs a model must use the platform's model
gateway, never a vendor SDK, so routing, budgets and data rules still apply.

## Packaging and registration

Declare the plugin under the `nexiqon.plugins` entry point group. Evaluators use the
`nexiqon.evaluators` group. Each entry point names either:

- a plugin **instance** (an object with a `manifest`);
- or a zero-argument **function** that returns one instance or a list of them.

Do not point an entry point at a class that has a `manifest` attribute: the class itself would be
registered instead of an instance of it.

```python
# acme_plugins/__init__.py
from acme_plugins.asciidoc import AsciidocParser
from acme_plugins.evals import MentionsProduct
from acme_plugins.wiki import IntranetWiki


def plugins():
    return [IntranetWiki(), AsciidocParser()]


mentions_product = MentionsProduct()
```

```toml
[project]
name = "acme-nexiqon-plugins"
dependencies = ["nexiqon-sdk"]

[project.entry-points."nexiqon.plugins"]
acme = "acme_plugins:plugins"

[project.entry-points."nexiqon.evaluators"]
mentions-product = "acme_plugins:mentions_product"
```

Install the package into the platform image (a derived image on top of `nexiqon/platform`), and
the plugins appear on the next start:

- connectors in the **Add source** gallery, with the form drawn from `config_schema`;
- parsers for their file types;
- evaluators in test runs.

A plugin whose manifest is invalid, or whose name clashes with another, is refused at start-up
with a clear error.

## Testing a plugin

The SDK's `Registry` loads plugins exactly as the platform does:

```python
from nexiqon_sdk import PluginKind, Registry

registry = Registry()
registry.register(IntranetWiki())
assert (
    registry.validate_config(
        PluginKind.CONNECTOR, "intranet-wiki", {"base_url": "https://wiki.example.com"}
    )
    == []
)
```

The built-in plugins in the ingestion service (`nexiqon_ingestion.plugins`: the web crawler, S3, Git and
file upload connectors, and the Markdown, HTML, PDF, Word, text, CSV and JSON parsers) are written against the same SDK.
They are the best examples.
