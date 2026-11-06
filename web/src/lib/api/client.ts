import createClient from "openapi-fetch";

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

// Empty in production: the UI is served by the API server itself.
// In development, `make dev` points this at the separately running API.
const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

export const api = createClient<paths>({ baseUrl });

export type ExportFormat = components["schemas"]["ExportRequest"]["format"];

/** `GET /v1/datasets/{id}/export` is a file download, so the browser fetches it, not the client. */
export function downloadUrl(datasetId: string, format: ExportFormat, includeRowId: boolean) {
  const query = new URLSearchParams({ format, include_row_id: String(includeRowId) });
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
