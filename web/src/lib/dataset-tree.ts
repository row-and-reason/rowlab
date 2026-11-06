import type { Dataset } from "@/lib/api/client";
import { isActive } from "@/lib/runs";

export type TreeRow = { dataset: Dataset; depth: number; hasChildren: boolean; open: boolean };

/**
 * The datasets as a tree, flattened into the rows to show: each dataset a run made sits under the one
 * it was made from. Siblings, and the trees themselves, go by their latest activity (the newest dataset
 * in them), so a run brings its whole family to the top. A collapsed dataset hides what was made from
 * it, unless a run is still making one of those.
 */
export function datasetTree(datasets: Dataset[], collapsed: Set<string> = new Set()): TreeRow[] {
  const ids = new Set(datasets.map((d) => d.id));
  const children = new Map<string | null, Dataset[]>();
  for (const d of datasets) {
    // A dataset whose parent was deleted starts a tree of its own.
    const parent = d.parent_id && ids.has(d.parent_id) ? d.parent_id : null;
    children.set(parent, [...(children.get(parent) ?? []), d]);
  }

  const latest = new Map<string, string>();
  const running = new Map<string, boolean>();
  function measure(d: Dataset) {
    let last = d.created_at;
    let active = !!d.run && isActive(d.run);
    for (const child of children.get(d.id) ?? []) {
      measure(child);
      if (latest.get(child.id)! > last) last = latest.get(child.id)!;
      active ||= running.get(child.id)!;
    }
    latest.set(d.id, last);
    running.set(d.id, active);
  }
  const roots = children.get(null) ?? [];
  roots.forEach(measure);

  const byLatest = (a: Dataset, b: Dataset) => latest.get(b.id)!.localeCompare(latest.get(a.id)!);
  const rows: TreeRow[] = [];
  function add(d: Dataset, depth: number) {
    const below = [...(children.get(d.id) ?? [])].sort(byLatest);
    const open = !collapsed.has(d.id) || running.get(d.id)!;
    rows.push({ dataset: d, depth, hasChildren: below.length > 0, open });
    if (open) below.forEach((child) => add(child, depth + 1));
  }
  [...roots].sort(byLatest).forEach((root) => add(root, 0));
  return rows;
}
