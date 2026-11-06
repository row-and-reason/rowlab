"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ColumnProfiles } from "@/components/column-profiles";
import { DatasetExplorer } from "@/components/dataset-explorer";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, type Dataset } from "@/lib/api/client";
import { errorMessage, formatBytes, formatNumber } from "@/lib/format";

// A query parameter rather than a `[id]` route, because the UI is a static export.
export default function DatasetPage() {
  return (
    <Suspense fallback={<Spinner className="m-6" />}>
      <DatasetView />
    </Suspense>
  );
}

function DatasetView() {
  const id = useSearchParams().get("id") ?? "";
  const [loaded, setLoaded] = useState<{ id: string; dataset?: Dataset; error?: string }>();

  useEffect(() => {
    api
      .GET("/v1/datasets/{dataset_id}", { params: { path: { dataset_id: id } } })
      .then(({ data, error }) =>
        setLoaded(error ? { id, error: errorMessage(error) } : { id, dataset: data }),
      );
  }, [id]);

  if (loaded?.id !== id) return <Spinner className="m-6" />;
  if (!loaded.dataset) {
    return (
      <Alert variant="destructive" className="m-6 w-auto">
        <AlertDescription>{loaded.error}</AlertDescription>
      </Alert>
    );
  }
  const dataset = loaded.dataset;

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-6">
      <div>
        <h1 className="text-xl font-semibold">{dataset.name}</h1>
        <p className="text-sm text-muted-foreground">
          {formatNumber(dataset.row_count)} rows · {dataset.columns.length - 1} columns ·{" "}
          {formatBytes(dataset.size_bytes)} · {dataset.source}
        </p>
      </div>
      <Tabs defaultValue="rows">
        <TabsList>
          <TabsTrigger value="rows">Rows</TabsTrigger>
          <TabsTrigger value="columns">Columns</TabsTrigger>
        </TabsList>
        <TabsContent value="rows" keepMounted>
          <DatasetExplorer dataset={dataset} />
        </TabsContent>
        <TabsContent value="columns">
          <ColumnProfiles datasetId={dataset.id} />
        </TabsContent>
      </Tabs>
    </main>
  );
}
