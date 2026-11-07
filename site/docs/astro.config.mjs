// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import starlightOpenAPI, { openAPISidebarGroups } from "starlight-openapi";

export default defineConfig({
  site: "https://docs.rowlab.dev",
  // Keep the Markdown renderer beside its platform-specific native binding.
  vite: { environments: { prerender: { resolve: { external: ["satteri"] } } } },
  integrations: [
    starlight({
      title: "rowlab Docs",
      description:
        "Learn to label, extract and rewrite tabular data with rowlab. Guides, self-hosting, API reference and MCP tools.",
      logo: { light: "./src/assets/logo-light.svg", dark: "./src/assets/logo-dark.svg", alt: "" },
      customCss: ["./src/brand.css"],
      head: [{ tag: "meta", attrs: { name: "twitter:card", content: "summary_large_image" } }],
      favicon: "/favicon.svg",
      social: [
        { icon: "github", label: "GitHub", href: "https://github.com/row-and-reason/rowlab" },
      ],
      editLink: { baseUrl: "https://github.com/row-and-reason/rowlab/edit/main/site/docs/" },
      components: { Head: "./src/components/Head.astro" },
      plugins: [
        starlightOpenAPI([{ base: "api", label: "API reference", schema: "../../openapi.json" }]),
      ],
      sidebar: [
        { label: "Get started", slug: "get-started" },
        {
          label: "How it works",
          items: [
            { label: "Datasets", slug: "how-it-works/datasets" },
            { label: "Runs", slug: "how-it-works/runs" },
            { label: "SQL", slug: "how-it-works/sql" },
            { label: "Answer types", slug: "how-it-works/answer-types" },
          ],
        },
        {
          label: "Guides",
          items: [
            { label: "Labeling", slug: "guides/labeling" },
            { label: "Comparing models", slug: "guides/comparing-models" },
            { label: "Labeling at scale", slug: "guides/at-scale" },
            { label: "Exporting", slug: "guides/exporting" },
          ],
        },
        {
          label: "Agents",
          items: [
            { label: "MCP", slug: "agents/mcp" },
            { label: "Skills", slug: "agents/skills" },
          ],
        },
        {
          label: "Self-host",
          items: [
            { label: "Running rowlab", slug: "self-host" },
            { label: "Configuration", slug: "self-host/configuration" },
            { label: "A shared server", slug: "self-host/hosted" },
          ],
        },
        ...openAPISidebarGroups,
        { label: "Changelog", slug: "changelog" },
      ],
    }),
  ],
});
