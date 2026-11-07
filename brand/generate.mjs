// Regenerate committed brand assets: pnpm --dir site/docs install && node brand/generate.mjs
import { createRequire } from "node:module";
import { readFile, writeFile, mkdir, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../", import.meta.url));
const require = createRequire(path.join(root, "site/docs/package.json"));
const sharp = require("sharp");
const mark = await readFile(path.join(root, "brand/mark.svg"), "utf8");
const stroke = mark.match(/<path[^>]+\/>/)[0];
const adaptive =
  "<style>:root{color:#19191f}@media(prefers-color-scheme:dark){:root{color:#f5f4fa}}</style>";
const icon = mark.replace("<title>rowlab</title>", "<title>rowlab</title>" + adaptive);
const logo = `<svg xmlns="http://www.w3.org/2000/svg" width="154" height="40" viewBox="0 0 154 40"><title>rowlab</title>${adaptive}<g transform="translate(0 4)" fill="none">${stroke}</g><text x="44" y="30" fill="currentColor" font-family="Arial, sans-serif" font-size="30" font-weight="600" letter-spacing="-1">rowlab</text></svg>`;
const tile = `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><rect width="512" height="512" rx="112" fill="#17161d"/><g transform="translate(96 96) scale(10)" color="#f5f4fa" fill="none">${stroke}</g></svg>`;
const png = (size) => sharp(Buffer.from(tile)).resize(size, size).png().toBuffer();
// ICO container with PNG entries, including an actual 16px raster for small tab icons.
const sizes = [16, 32, 48];
const images = await Promise.all(sizes.map(png));
const header = Buffer.alloc(6 + 16 * sizes.length);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(sizes.length, 4);
let offset = header.length;
images.forEach((b, i) => {
  const p = 6 + i * 16;
  header[p] = sizes[i];
  header[p + 1] = sizes[i];
  header.writeUInt16LE(1, p + 4);
  header.writeUInt16LE(32, p + 6);
  header.writeUInt32LE(b.length, p + 8);
  header.writeUInt32LE(offset, p + 12);
  offset += b.length;
});
const ico = Buffer.concat([header, ...images]);
const destinations = ["site/www/public", "site/docs/public", "web/public"];
for (const target of destinations) {
  const dir = path.join(root, target);
  await mkdir(path.join(dir, "brand/social"), { recursive: true });
  for (const [name, contents] of [
    ["favicon.svg", icon],
    ["favicon.ico", ico],
    ["apple-touch-icon.png", await png(180)],
    ["brand/mark.svg", mark],
    ["brand/logo.svg", logo],
  ])
    await writeFile(path.join(dir, name), contents);
}
await mkdir(path.join(root, "site/docs/src/assets"), { recursive: true });
for (const [theme, color] of [
  ["light", "#19191f"],
  ["dark", "#f5f4fa"],
])
  await writeFile(
    path.join(root, `site/docs/src/assets/logo-${theme}.svg`),
    mark.replace("viewBox=", 'width="32" height="32" viewBox=').replace("currentColor", color),
  );
const escape = (s) =>
  s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
function lines(text, max) {
  const result = [];
  let line = "";
  for (const word of text.split(/\s+/)) {
    if (line.length + word.length + 1 > max && line) {
      result.push(line);
      line = "";
    }
    line += (line ? " " : "") + word;
  }
  if (line) result.push(line);
  return result;
}
async function card(dest, name, { label, title, description, domain }) {
  const headline = title.split("\n").flatMap((line) => lines(line, 24));
  const detail = lines(description, 62);
  const titleSize = headline.length > 2 ? 58 : 68;
  const table = `<g transform="translate(822 210)"><rect width="306" height="267" rx="12" fill="#1c1a25" stroke="#34303e"/><rect x="213" y="0" width="93" height="267" rx="12" fill="#a997ff" fill-opacity="0.13"/>${[0, 1, 2, 3].map((i) => `<path d="M0 ${54 + i * 53}H306" stroke="#34303e"/><rect x="20" y="${75 + i * 53}" width="${[132, 104, 146, 116][i]}" height="8" rx="4" fill="#777181"/><path d="M239 ${78 + i * 53}l7 7 14-16" stroke="#b9aaff" fill="none" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`).join("")}<text x="20" y="34" fill="#a39cae" font-family="Arial" font-size="15">row</text><text x="233" y="34" fill="#cbbfff" font-family="Arial" font-size="15">label</text></g>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630"><rect width="1200" height="630" fill="#121116"/><g transform="translate(64 50) scale(1.25)" color="#f5f4fa" fill="none">${stroke}</g><text x="120" y="83" fill="#f5f4fa" font-family="Arial" font-size="34" font-weight="600" letter-spacing="-1">rowlab</text><text x="64" y="171" fill="#b9aaff" font-family="Arial" font-size="16" letter-spacing="3">${escape(label.toUpperCase())}</text>${headline.map((line, i) => `<text x="60" y="${253 + i * 78}" fill="${i === headline.length - 1 ? "#b9aaff" : "#f5f4fa"}" font-family="Arial" font-size="${titleSize}" font-weight="600" letter-spacing="-2">${escape(line)}</text>`).join("")}${detail
    .slice(0, 2)
    .map(
      (line, i) =>
        `<text x="64" y="${headForDetail(headline.length) + i * 30}" fill="#a9a3b3" font-family="Arial" font-size="23">${escape(line)}</text>`,
    )
    .join(
      "",
    )}${table}<path d="M64 539H1136" stroke="#302c38"/><text x="64" y="580" fill="#a9a3b3" font-family="Arial" font-size="19">${domain}</text><text x="1136" y="580" text-anchor="end" fill="#827a8e" font-family="Arial" font-size="16">A Row &amp; Reason product</text></svg>`;
  await writeFile(
    path.join(root, dest, `brand/social/${name}.png`),
    await sharp(Buffer.from(svg)).png().toBuffer(),
  );
}
function headForDetail(n) {
  return Math.max(392, 253 + (n - 1) * 78 + 58);
}
await card("site/www/public", "home", {
  label: "AI for tabular data",
  title: "Ask a question\nof every row.",
  description: "Label, extract and rewrite data. Open source. API and MCP.",
  domain: "rowlab.dev",
});
await card("site/www/public", "pricing", {
  label: "Pricing",
  title: "Start small.\nRun on your terms.",
  description: "Run rowlab yourself, or use the hosted app. Bring your own model key.",
  domain: "rowlab.dev/pricing",
});
await card("web/public", "app", {
  label: "Workspace",
  title: "From rows\nto answers.",
  description: "Label data, compare models and inspect results in one workspace.",
  domain: "app.rowlab.dev",
});
await card("web/public", "settings", {
  label: "Workspace settings",
  title: "Your workspace.\nYour controls.",
  description: "Providers, storage, usage and team settings for rowlab.",
  domain: "app.rowlab.dev/settings",
});
await card("site/docs/public", "api", {
  label: "API reference",
  title: "Every row.\nEvery endpoint.",
  description: "Build labeling workflows with the rowlab API.",
  domain: "docs.rowlab.dev/api",
});
const docCards = {};
async function docs(dir, relative = "") {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const rel = path.join(relative, entry.name);
    if (entry.isDirectory()) await docs(path.join(dir, entry.name), rel);
    else if (/\.mdx?$/.test(entry.name)) {
      const source = await readFile(path.join(dir, entry.name), "utf8");
      const title = source.match(/^title: (.+)$/m)?.[1];
      const description = source.match(/^description: (.+)$/m)?.[1];
      if (!title) continue;
      const slug = rel
        .replace(/\.mdx?$/, "")
        .replace(/(^|\/)index$/, "")
        .replace(/\/$/, "");
      docCards[slug.replaceAll("/", "-") || "index"] =
        "docs-" + (slug.replaceAll("/", "-") || "index");
      await card("site/docs/public", "docs-" + (slug.replaceAll("/", "-") || "index"), {
        label: "Documentation",
        title: title.replace(/^['"]|['"]$/g, ""),
        description:
          description?.replace(/^['"]|['"]$/g, "") ?? "Learn to work with tabular data in rowlab.",
        domain: "docs.rowlab.dev" + (slug ? "/" + slug : ""),
      });
    }
  }
}
await docs(path.join(root, "site/docs/src/content/docs"));
await writeFile(
  path.join(root, "site/docs/src/brand-cards.json"),
  JSON.stringify(docCards, null, 2) + "\n",
);
console.log("Generated rowlab marks, favicon sets and social cards for all three sites.");
