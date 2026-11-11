import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { api, type Dataset } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";
import { isActive } from "@/lib/runs";

/** The workspace's datasets: loaded on mount, polled while a run is going, and deleted from here. */
export function useDatasets(selectedId: string | null) {
  const router = useRouter();
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);

  const load = useCallback(async () => {
    const { data, error } = await api.GET("/v1/datasets");
    if (error) toast.error(errorMessage(error));
    else setDatasets(data);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    load();
  }, [load]);

  // While a run is going, keep its progress and its dataset's rows current.
  const anyRunning = datasets?.some((d) => d.run && isActive(d.run)) ?? false;
  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(load, 1000);
    return () => clearInterval(timer);
  }, [anyRunning, load]);

  async function remove(dataset: Dataset) {
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
