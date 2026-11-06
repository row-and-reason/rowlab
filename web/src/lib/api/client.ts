import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Dataset = components["schemas"]["Dataset"];
export type ColumnProfile = components["schemas"]["ColumnProfile"];
export type Filter = components["schemas"]["Filter"];
export type Sort = components["schemas"]["Sort"];
export type QueryResult = components["schemas"]["QueryResult"];

// Empty in production: the UI is served by the API server itself.
// In development, `make dev` points this at the separately running API.
const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

export const api = createClient<paths>({ baseUrl });

/** `POST /v1/datasets` takes multipart form data, which the generated types can't express. */
export function createDataset(input: { file: File } | { source: string }) {
  const form = new FormData();
  if ("file" in input) form.append("file", input.file);
  else form.append("source", input.source);
  return api.POST("/v1/datasets", { body: {}, bodySerializer: () => form });
}
