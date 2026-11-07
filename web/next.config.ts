import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  // Pure static build, served by the Python server (see Makefile `build`).
  output: "export",
  // Emit `/dataset/index.html` instead of `/dataset.html`, which is what FastAPI's StaticFiles serves.
  trailingSlash: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
