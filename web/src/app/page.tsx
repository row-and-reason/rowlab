"use client";

import { DatabaseIcon } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { DatasetsPanel } from "@/components/datasets-panel";
import { DatasetView, TABS, type Tab } from "@/components/dataset-view";
import { OutputPanel } from "@/components/output-panel";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { api, type Dataset } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

// The whole app is this one page: datasets | contents | output. What is selected lives in the query
// string (`/?dataset=<id>&tab=prompt`), because a static export can't have routes for ids that only
// exist at runtime. Changing it is a client-side navigation, so the columns stay mounted.
export default function Home() {
  return (
    <Suspense fallback={<Spinner className="m-6" />}>
      <Workspace />
    </Suspense>
  );
}

function Workspace() {
  const router = useRouter();
  const params = useSearchParams();
  const selectedId = params.get("dataset");
  const tab: Tab = TABS.find((t) => t === params.get("tab")) ?? "rows";
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

  const selected = datasets?.find((d) => d.id === selectedId);

  async function remove(dataset: Dataset) {
    const { error } = await api.DELETE("/v1/datasets/{dataset_id}", {
      params: { path: { dataset_id: dataset.id } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`Deleted ${dataset.name}`);
    router.push("/");
    load();
  }

  return (
    <main className="grid min-h-0 flex-1 grid-cols-1 overflow-auto lg:grid-cols-[16rem_minmax(0,1fr)_18rem] lg:overflow-hidden">
      <section className="overflow-auto border-b p-4 lg:border-r lg:border-b-0">
        <DatasetsPanel
          datasets={datasets}
          selectedId={selectedId}
          onAdded={(dataset) => {
            load();
            router.push(`/?dataset=${dataset.id}`);
          }}
        />
      </section>
      <section className="@container overflow-auto p-4">
        {selected ? (
          <DatasetView
            key={selected.id}
            dataset={selected}
            tab={tab}
            onTabChange={(t) => router.replace(`/?dataset=${selected.id}&tab=${t}`)}
            onDelete={() => remove(selected)}
          />
        ) : datasets === null ? (
          <Spinner />
        ) : (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <DatabaseIcon />
              </EmptyMedia>
              <EmptyTitle>{selectedId ? "Dataset not found" : "Pick a dataset"}</EmptyTitle>
              <EmptyDescription>
                {datasets.length
                  ? "Choose one on the left to explore its rows and write a prompt."
                  : "Add a CSV, TSV, JSON, JSONL or Parquet file to get started."}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </section>
      <section className="overflow-auto border-t p-4 lg:border-t-0 lg:border-l">
        <OutputPanel />
      </section>
    </main>
  );
}
