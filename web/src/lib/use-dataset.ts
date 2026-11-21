import { useCallback, useEffect, useRef, useState } from "react";

import { api, type Dataset, type Run } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";
import { isActive, poll } from "@/lib/runs";

/**
 * The selected dataset with its columns and answer columns, and its runs, newest first. Polled while
 * a run is going, so its columns fill in. `error` is set when the dataset can't be loaded at first.
 */
export function useDataset(datasetId: string | null) {
  const [loaded, setLoaded] = useState<{
    id: string;
    dataset?: Dataset;
    runs?: Run[];
    error?: string;
  }>();

  // The dataset now selected: an answer for one selected before is dropped.
  const selected = useRef(datasetId);
  useEffect(() => {
    selected.current = datasetId;
  }, [datasetId]);

  const load = useCallback(async () => {
    if (!datasetId) return;
    const path = { params: { path: { dataset_id: datasetId } } };
    const [dataset, runs] = await Promise.all([
      api.GET("/v1/datasets/{dataset_id}", path),
      api.GET("/v1/datasets/{dataset_id}/runs", path),
    ]);
    if (selected.current !== datasetId) return;
    setLoaded((previous) => {
      // A reload that fails keeps what was shown, so the panels stay as they are; the next tries again.
      if ((dataset.error || runs.error) && previous?.id === datasetId && previous.dataset)
        return previous;
      return {
        id: datasetId,
        dataset: dataset.data,
        runs: runs.data,
        error: dataset.error ? errorMessage(dataset.error) : undefined,
      };
    });
  }, [datasetId]);

  useEffect(() => {
    load();
  }, [load]);

  const current = loaded?.id === datasetId ? loaded : undefined;
  const running = current?.runs?.some(isActive) ?? false;
  useEffect(() => (running ? poll(load) : undefined), [running, load]);

  return { dataset: current?.dataset, runs: current?.runs, error: current?.error, load };
}
