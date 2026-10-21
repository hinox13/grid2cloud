// Package web/dist for GitHub Pages after `npm run build`, identically in CI and locally:
//   node pages.mjs
// Adds the repository's licence files and the licences of the bundled third-party software and
// fonts, marks the site as plain static files (.nojekyll), then checks that the build holds no
// source map, no 3D engine and no script loaded from another origin. Exits 1 on any failure.
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const DIST = "dist";
const fail = [];
if (!existsSync(join(DIST, "index.html"))) fail.push("dist/index.html missing: run npm run build first");

const copy = [
  ["../LICENSE", "LICENSE"],
  ["../NOTICE", "NOTICE"],
  ["../docs/DATA_LICENSES.md", "DATA_LICENSES.md"],
  ["node_modules/react/LICENSE", "third-party/react-MIT.txt"],
  ["node_modules/react-dom/LICENSE", "third-party/react-dom-MIT.txt"],
  ["node_modules/@fontsource/libre-franklin/LICENSE", "third-party/libre-franklin-OFL-1.1.txt"],
  ["node_modules/@fontsource/source-serif-4/LICENSE", "third-party/source-serif-4-OFL-1.1.txt"],
];
mkdirSync(join(DIST, "third-party"), { recursive: true });
for (const [from, to] of copy) {
  if (existsSync(from)) copyFileSync(from, join(DIST, to));
  else fail.push(`missing ${from}`);
}
writeFileSync(join(DIST, ".nojekyll"), "");

const files = (d) => readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? files(join(d, f)) : [join(d, f)]));
for (const f of files(DIST)) {
  if (f.endsWith(".map")) fail.push(`source map: ${f}`);
  if (f.endsWith(".js") && readFileSync(f, "utf8").includes("isWebGLRenderer")) fail.push(`3D engine bundled: ${f}`);
}
if (/<script[^>]+src="(https?:)?\/\//.test(readFileSync(join(DIST, "index.html"), "utf8"))) fail.push("script from another origin in index.html");

if (fail.length) {
  console.error("pages: FAILED\n" + fail.map((f) => `  - ${f}`).join("\n"));
  process.exit(1);
}
console.log(`pages: ${files(DIST).length} files ready in ${DIST}/`);
