// Fails the build when the widget grows past its budget (W-01: under 60 KB gzipped).
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const BUDGET = 60 * 1024;
const file = new URL("../dist/nexiqon-chat.js", import.meta.url);
const size = gzipSync(readFileSync(file), { level: 9 }).length;
const kb = (n) => `${(n / 1024).toFixed(1)} KB`;
if (size > BUDGET) {
  console.error(`nexiqon-chat.js is ${kb(size)} gzipped, over the ${kb(BUDGET)} budget`);
  process.exit(1);
}
console.log(`nexiqon-chat.js: ${kb(size)} gzipped (budget ${kb(BUDGET)})`);
