import type { Me } from "@/lib/api/client";

const ALL = [
  { id: "providers", label: "Providers", keywords: "openrouter model key", hostedOnly: false },
  { id: "storage", label: "Storage", keywords: "s3 connections bucket", hostedOnly: false },
  { id: "usage", label: "Usage", keywords: "spend cost answers tokens", hostedOnly: false },
  { id: "members", label: "Members", keywords: "people invite roles", hostedOnly: true },
  { id: "api-keys", label: "API keys", keywords: "tokens scripts", hostedOnly: true },
  { id: "plans", label: "Plans", keywords: "pricing billing", hostedOnly: true },
] as const;
export type Section = (typeof ALL)[number]["id"];

/** The settings sections there are: members, API keys and plans only where people sign in. */
export function sections(me: Me) {
  return ALL.filter((s) => me.user || !s.hostedOnly);
}

/** The settings page. `from` is the workspace's query string, so Back returns to it. */
export function settingsUrl(from: URLSearchParams, section: Section = "providers"): string {
  return `/settings/?${new URLSearchParams({ section, from: from.toString() })}`;
}
