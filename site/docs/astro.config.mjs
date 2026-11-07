// @ts-check
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import starlightOpenAPI, { openAPISidebarGroups } from "starlight-openapi";

export default defineConfig({
  site: "https://docs.rowlab.dev",
  integrations: [
    starlight({
      title: "rowlab",
      description: "rowlab labels, extracts and rewrites tabular data with AI.",
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
