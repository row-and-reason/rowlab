import { useCallback, useEffect, useState } from "react";

import { api, type Dataset, type Run } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";
import { isActive } from "@/lib/runs";

/**
 * The selected dataset with its columns and answer columns, and its runs, newest first. Polled while
 * a run is going, so its columns fill in. `error` is set when the dataset can't be loaded.
 */
export function useDataset(datasetId: string | null) {
  const [loaded, setLoaded] = useState<{
    id: string;
    dataset?: Dataset;
    runs?: Run[];
    error?: string;
  }>();

  const load = useCallback(async () => {
    if (!datasetId) return;
    const path = { params: { path: { dataset_id: datasetId } } };
    const [dataset, runs] = await Promise.all([
      api.GET("/v1/datasets/{dataset_id}", path),
      api.GET("/v1/datasets/{dataset_id}/runs", path),
    ]);
    setLoaded({
      id: datasetId,
      dataset: dataset.data,
      runs: runs.data,
      error: dataset.error ? errorMessage(dataset.error) : undefined,
    });
  }, [datasetId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on selection
    load();
  }, [load]);

  const current = loaded?.id === datasetId ? loaded : undefined;
  const running = current?.runs?.some(isActive) ?? false;
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(load, 1000);
    return () => clearInterval(timer);
  }, [running, load]);

  return { dataset: current?.dataset, runs: current?.runs, error: current?.error, load };
}
