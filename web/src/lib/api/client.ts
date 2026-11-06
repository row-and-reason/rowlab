import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Dataset = components["schemas"]["Dataset"];
export type ColumnProfile = components["schemas"]["ColumnProfile"];
export type Filter = components["schemas"]["Filter"];
export type Sort = components["schemas"]["Sort"];
export type QueryResult = components["schemas"]["QueryResult"];
export type RenderResult = components["schemas"]["RenderResult"];
export type Scope = components["schemas"]["Scope"];
export type Job = components["schemas"]["Job"];
// What the editor changes: the job as returned, which always has every field.
export type JobConfig = Pick<Job, "scope" | "tasks">;
export type Run = components["schemas"]["Run"];
export type RunSummary = components["schemas"]["RunSummary"];
export type RunRow = components["schemas"]["RunRow"];
export type Model = components["schemas"]["Model"];
export type Settings = components["schemas"]["Settings"];
export type Task = Job["tasks"][number];
export type AnswerType = Task["type"];
export type Option = components["schemas"]["Option"];

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
