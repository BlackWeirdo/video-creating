import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const standaloneDir = path.join(root, ".next", "standalone");

if (!fs.existsSync(standaloneDir)) {
  console.error("Missing .next/standalone directory; run `next build` first.");
  process.exit(1);
}

const staticSrc = path.join(root, ".next", "static");
const staticDst = path.join(standaloneDir, ".next", "static");
if (fs.existsSync(staticSrc)) {
  fs.mkdirSync(path.dirname(staticDst), { recursive: true });
  fs.cpSync(staticSrc, staticDst, { recursive: true, force: true });
}

const publicSrc = path.join(root, "public");
const publicDst = path.join(standaloneDir, "public");
if (fs.existsSync(publicSrc)) {
  fs.cpSync(publicSrc, publicDst, { recursive: true, force: true });
}

console.log("Standalone static assets copied successfully.");
