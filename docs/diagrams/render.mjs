// Renders every src/*.mmd to ./<name>.svg using the shared theme.
// Set PUPPETEER_EXECUTABLE_PATH if Chrome is not auto-detected.
import { readdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, basename } from "node:path";

const here = new URL(".", import.meta.url).pathname;
const only = process.argv.slice(2);
for (const f of readdirSync(join(here, "src")).filter((f) => f.endsWith(".mmd"))) {
  const name = basename(f, ".mmd");
  if (only.length && !only.includes(name)) continue;
  execFileSync(join(here, "node_modules/.bin/mmdc"), [
    "-i", join(here, "src", f), "-o", join(here, `${name}.svg`),
    "-c", join(here, "mermaid.config.json"), "-p", join(here, "puppeteer.json"),
    "-b", "white",
  ], { stdio: "inherit" });
  console.log(`rendered ${name}.svg`);
}
