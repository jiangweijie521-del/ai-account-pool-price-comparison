import { cp, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const workerRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.dirname(workerRoot);
const publicRoot = path.join(workerRoot, "public");
const files = [
  "index.html",
  "styles.css",
  "app.js",
  "analytics.js",
  "robots.txt",
  "sitemap.xml",
];

await rm(publicRoot, { recursive: true, force: true });
await mkdir(publicRoot, { recursive: true });
for (const filename of files) {
  await cp(path.join(projectRoot, filename), path.join(publicRoot, filename));
}
await cp(path.join(projectRoot, "assets"), path.join(publicRoot, "assets"), { recursive: true });

console.log(`Prepared ${files.length} files and assets in ${publicRoot}`);
