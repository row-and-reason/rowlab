import createClient from "openapi-fetch";

import { resetAnalytics } from "@/lib/analytics";

import type { components, paths } from "./schema";

export type Dataset = components["schemas"]["Dataset"];
export type ColumnProfile = components["schemas"]["ColumnProfile"];
export type QueryResult = components["schemas"]["QueryResult"];
export type RenderResult = components["schemas"]["RenderResult"];
export type Run = components["schemas"]["Run"];
export type Model = components["schemas"]["Model"];
export type Settings = components["schemas"]["Settings"];
// As a run returns it, with every field; the API accepts the same shape.
export type Task = Run["config"]["tasks"][number];
export type Column = Dataset["columns"][number];
export type AnswerType = Task["type"];
export type Option = components["schemas"]["Option"];
export type ExtractField = Task["fields"][number];
export type FieldType = ExtractField["type"];
export type TaskTypes = components["schemas"]["TaskTypes"];
export type Preset = TaskTypes["presets"][number];
export type Estimate = components["schemas"]["Estimate"];
export type Connection = components["schemas"]["Connection"];
export type Comparison = components["schemas"]["Comparison"];
export type Me = components["schemas"]["WhoAmI"];
export type Role = Me["role"];
export type Members = components["schemas"]["Members"];
export type ApiKey = components["schemas"]["ApiKey"];
export type Usage = components["schemas"]["Usage"];

// Empty in production: the UI is served by the API server itself.
// In development, `make dev` points this at the separately running API.
const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

export const api = createClient<paths>({ baseUrl });

// Signed out (hosted only): to the sign-in page, which comes back here signed in.
api.use({
  onResponse({ response }) {
    // A page of the API server, not of this app.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    if (response.status === 401) window.location.href = `${baseUrl}/auth/sign-in`;
  },
});

/** Sign out: a form post, since it ends at WorkOS's sign-out page. */
export function signOut() {
  resetAnalytics();
  const form = document.createElement("form");
  form.method = "post";
  form.action = `${baseUrl}/auth/sign-out`;
  document.body.append(form);
  form.submit();
}

export type ExportFormat = components["schemas"]["ExportRequest"]["format"];

/** `GET /v1/datasets/{id}/export` is a file download, so the browser fetches it, not the client. */
export function downloadUrl(
  datasetId: string,
  format: ExportFormat,
  includeRowId: boolean,
  sql: string | null,
) {
  const query = new URLSearchParams({ format, include_row_id: String(includeRowId) });
  if (sql) query.set("sql", sql);
  return `${baseUrl}/v1/datasets/${datasetId}/export?${query}`;
}

/** `POST /v1/datasets` takes multipart form data, which the generated types can't express. */
export function createDataset(
  input: { file: File } | { source: string; connectionId?: string | null },
) {
  const form = new FormData();
  if ("file" in input) form.append("file", input.file);
  else {
    form.append("source", input.source);
    if (input.connectionId) form.append("connection_id", input.connectionId);
  }
  return api.POST("/v1/datasets", { body: {}, bodySerializer: () => form });
}
