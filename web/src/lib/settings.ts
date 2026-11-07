import type { Me } from "@/lib/api/client";

const ALL = [
  { id: "providers", label: "Providers", hostedOnly: false },
  { id: "storage", label: "Storage", hostedOnly: false },
  { id: "members", label: "Members", hostedOnly: true },
  { id: "api-keys", label: "API keys", hostedOnly: true },
] as const;
export type Section = (typeof ALL)[number]["id"];

/** The settings sections there are: members and API keys only where people sign in. */
export function sections(me: Me) {
  return ALL.filter((s) => me.user || !s.hostedOnly);
}

/** The settings page. `from` is the workspace's query string, so Back returns to it. */
export function settingsUrl(from: URLSearchParams, section: Section = "providers"): string {
  return `/settings/?${new URLSearchParams({ section, from: from.toString() })}`;
}
