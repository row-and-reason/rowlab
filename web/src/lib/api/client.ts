import createClient from "openapi-fetch";

import type { paths } from "./schema";

// Empty in production: the UI is served by the API server itself.
// In development, `make dev` points this at the separately running API.
const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

export const api = createClient<paths>({ baseUrl });
