// Performance budgets (UX-11): fails the build when Studio ships more JavaScript or CSS than its
// budget. Measured after `next build`, gzipped, the way browsers download it:
//   * first-load JavaScript of every route (shared runtime + the route's own chunks);
//   * all CSS (one stylesheet, loaded on every page).
// Raise a budget only on purpose, in the same change that explains why.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { runInNewContext } from "node:vm";
import { gzipSync } from "node:zlib";

const NEXT = new URL("../.next/", import.meta.url).pathname;
const BUDGET = {
  routeJs: 350 * 1024, // first-load JS of any one route (largest: 314 KB, 2026-11-19)
  css: 28 * 1024, // 23 KB, 2026-11-19
};

const gz = new Map();
function size(file) {
  if (!gz.has(file)) gz.set(file, gzipSync(readFileSync(join(NEXT, file)), { level: 9 }).length);
  return gz.get(file);
}
const kb = (n) => `${(n / 1024).toFixed(1)} KB`;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else yield path;
  }
}

const manifest = JSON.parse(readFileSync(join(NEXT, "build-manifest.json"), "utf8"));
const shared = new Set(manifest.rootMainFiles);
const routes = [];
for (const file of walk(join(NEXT, "server", "app"))) {
  if (!file.endsWith("page_client-reference-manifest.js")) continue;
  const sandbox = { globalThis: {} };
  sandbox.globalThis = sandbox;
  runInNewContext(readFileSync(file, "utf8"), sandbox);
  for (const [route, rsc] of Object.entries(sandbox.__RSC_MANIFEST ?? {})) {
    const files = new Set(shared);
    for (const list of Object.values(rsc.entryJSFiles ?? {})) for (const f of list) files.add(f);
    const js = [...files].filter((f) => f.endsWith(".js")).reduce((sum, f) => sum + size(f), 0);
    routes.push({ route: route.replace(/\/page$/, "") || "/", js });
  }
}
const css = [...walk(join(NEXT, "static"))]
  .filter((f) => f.endsWith(".css"))
  .reduce((sum, f) => sum + size(relative(NEXT, f)), 0);

routes.sort((a, b) => b.js - a.js);
let failed = false;
for (const { route, js } of routes) {
  const over = js > BUDGET.routeJs;
  failed ||= over;
  console.log(`${over ? "OVER " : "     "}${kb(js).padStart(9)}  ${route}`);
}
console.log(`CSS: ${kb(css)} (budget ${kb(BUDGET.css)}); route JS budget ${kb(BUDGET.routeJs)}; ${routes.length} routes`);
if (css > BUDGET.css) failed = true;
if (routes.length === 0) {
  console.error("No route manifests found: run `next build` first.");
  process.exit(1);
}
if (failed) {
  console.error("Over budget. Split the heavy component (dynamic import) or justify raising the budget.");
  process.exit(1);
}
