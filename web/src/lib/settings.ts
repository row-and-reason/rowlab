export const SECTIONS = [
  { id: "providers", label: "Providers" },
  { id: "storage", label: "Storage" },
] as const;
export type Section = (typeof SECTIONS)[number]["id"];

/** The settings page. `from` is the workspace's query string, so Back returns to it. */
export function settingsUrl(from: URLSearchParams, section: Section = "providers"): string {
  return `/settings/?${new URLSearchParams({ section, from: from.toString() })}`;
}
