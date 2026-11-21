import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { api, type DatasetSummary } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";
import { poll } from "@/lib/runs";

/** The workspace's datasets, newest first: loaded on mount, polled while a run is going, and deleted
 * from here. */
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

  return { datasets, load, remove };
}
