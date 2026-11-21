import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { api, type DatasetSummary, type Settings, type Settling } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";
import { poll } from "@/lib/runs";

/** The datasets still in use, then those settled (left alone), each newest first: the order they are
 * listed and stepped through in. */
export function shelves(datasets: DatasetSummary[]): {
  active: DatasetSummary[];
  settled: DatasetSummary[];
} {
  return {
    active: datasets.filter((d) => !d.settled),
    settled: datasets.filter((d) => d.settled),
  };
}

// Whether the Settled section is open lives in this browser only.
const SHOW_SETTLED = "rowlab.showSettled";

/** Whether the Settled section of the datasets list is open, remembered in this browser. */
export function useShowSettled(): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(() => localStorage.getItem(SHOW_SETTLED) === "1");
  const update = useCallback((next: boolean) => {
    localStorage.setItem(SHOW_SETTLED, next ? "1" : "0");
    setOpen(next);
  }, []);
  return [open, update];
}

/** The workspace's datasets, newest first: loaded on mount, polled while a run is going, and deleted
 * and settled from here. */
export function useDatasets(selectedId: string | null) {
  const router = useRouter();
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null);

  // `quiet` for polls: a poll that fails says nothing, and the next tries again.
  const load = useCallback(async (quiet = false) => {
    const { data, error } = await api.GET("/v1/datasets");
    if (error && !quiet) toast.error(errorMessage(error));
    else if (data) setDatasets(data);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    load();
  }, [load]);

  // While a run is going, keep its run indicator current.
  const anyRunning = datasets?.some((d) => d.active_runs > 0) ?? false;
  useEffect(() => (anyRunning ? poll(() => load(true)) : undefined), [anyRunning, load]);

  async function remove(dataset: DatasetSummary) {
    const { error } = await api.DELETE("/v1/datasets/{dataset_id}", {
      params: { path: { dataset_id: dataset.id } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`Deleted ${dataset.name}`);
    if (dataset.id === selectedId) router.push("/");
    load();
  }

  // Settle a dataset or bring it back, or choose whether it settles by itself.
  async function settle(dataset: DatasetSummary, body: Settling) {
    const { error } = await api.PATCH("/v1/datasets/{dataset_id}/settling", {
      params: { path: { dataset_id: dataset.id } },
      body,
    });
    if (error) toast.error(errorMessage(error));
    load();
  }

  // Whether the organisation's datasets settle by themselves: the settings as they now are.
  async function setAutoSettle(on: boolean): Promise<Settings | undefined> {
    const { data, error } = await api.PATCH("/v1/settings", { body: { auto_settle: on } });
    if (error) toast.error(errorMessage(error));
    load();
    return data;
  }

  return { datasets, load, remove, settle, setAutoSettle };
}
