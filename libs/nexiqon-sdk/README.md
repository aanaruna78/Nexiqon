# nexiqon-sdk

Ports and manifests for Nexiqon plugins: **connectors** (find and fetch content), **parsers** (bytes to
ordered blocks with heading levels and pages) and **chunkers** (blocks to chunks).

```toml
[project.entry-points."nexiqon.plugins"]
my-plugins = "my_package:plugins"   # an object with a `manifest`, or a factory returning a list
```

Each plugin declares a `Manifest`: name, kind, title, JSON Schema for its configuration (rendered as a
form in Studio), capabilities, and for parsers the media types and extensions. Connectors get a
`ConnectorContext` with the platform's SSRF-safe HTTP client, host checks, a scratch directory and
named credentials. They must not open their own sockets.
