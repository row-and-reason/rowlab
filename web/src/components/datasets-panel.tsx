"use client";

import Link from "next/link";

import { AddDataset } from "@/components/add-dataset";
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from "@/components/ui/item";
import { Spinner } from "@/components/ui/spinner";
import type { Dataset } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";

/** The left column: every dataset, uploaded or produced by a run, and adding new ones. */
export function DatasetsPanel({
  datasets,
  selectedId,
  onAdded,
}: {
  datasets: Dataset[] | null;
  selectedId: string | null;
  onAdded: (dataset: Dataset) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-semibold">Datasets</h2>
      <AddDataset onAdded={onAdded} />
      {datasets === null ? (
        <Spinner />
      ) : (
        <ItemGroup className="gap-1">
          {datasets.map((dataset) => (
            <Item
              key={dataset.id}
              size="sm"
              variant={dataset.id === selectedId ? "muted" : "default"}
              render={<Link href={`/?dataset=${dataset.id}`} />}
            >
              <ItemContent className="min-w-0">
                <ItemTitle className="w-full truncate" title={dataset.name}>
                  {dataset.name}
                </ItemTitle>
                <ItemDescription>
                  {formatNumber(dataset.row_count)} rows · {dataset.columns.length - 1} columns
                </ItemDescription>
              </ItemContent>
            </Item>
          ))}
        </ItemGroup>
      )}
    </div>
  );
}
