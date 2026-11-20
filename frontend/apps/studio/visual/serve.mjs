// Static server for the visual tests: Storybook's build at /sb/, the built widget at /widget/, and
// the widget harness page. No network access is needed, so screenshots are reproducible.
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const here = new URL(".", import.meta.url).pathname;
const roots = {
  "/sb/": join(here, "../storybook-static"),
  "/widget/": join(here, "../../widget/dist"),
  "/": here,
};
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".png": "image/png" };

createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  const prefix = Object.keys(roots).find((p) => path.startsWith(p));
  let file = normalize(join(roots[prefix], path.slice(prefix.length)));
  if (!file.startsWith(roots[prefix])) return res.writeHead(403).end();
  if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
  if (!existsSync(file)) return res.writeHead(404).end();
  res.writeHead(200, { "content-type": types[extname(file)] ?? "application/octet-stream" });
  createReadStream(file).pipe(res);
}).listen(Number(process.env.PORT ?? 4400), "127.0.0.1");
