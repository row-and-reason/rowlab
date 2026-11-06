"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { DatabaseIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";

import { AddDataset } from "@/components/add-dataset";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type Dataset } from "@/lib/api/client";
import { errorMessage, formatBytes, formatDate, formatNumber } from "@/lib/format";

export default function DatasetsPage() {
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

  async function remove(dataset: Dataset) {
    const { error } = await api.DELETE("/v1/datasets/{dataset_id}", {
      params: { path: { dataset_id: dataset.id } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`Deleted ${dataset.name}`);
    load();
  }

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 overflow-auto p-6">
      <h1 className="text-xl font-semibold">Datasets</h1>
      <AddDataset onAdded={load} />

      {datasets === null ? (
        <Spinner />
      ) : datasets.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <DatabaseIcon />
            </EmptyMedia>
            <EmptyTitle>No datasets yet</EmptyTitle>
            <EmptyDescription>
              Upload a CSV, TSV, JSON, JSONL or Parquet file, or load one from a path or a public
              URL.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead className="text-right">Rows</TableHead>
              <TableHead className="text-right">Columns</TableHead>
              <TableHead className="text-right">Size</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Added</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {datasets.map((dataset) => (
              <TableRow key={dataset.id}>
                <TableCell>
                  <Link
                    href={`/dataset/?id=${dataset.id}`}
                    className={buttonVariants({ variant: "link", className: "px-0" })}
                  >
                    {dataset.name}
                  </Link>
                </TableCell>
                <TableCell className="text-right">{formatNumber(dataset.row_count)}</TableCell>
                {/* Not counting the added __row_id column. */}
                <TableCell className="text-right">{dataset.columns.length - 1}</TableCell>
                <TableCell className="text-right">{formatBytes(dataset.size_bytes)}</TableCell>
                <TableCell className="max-w-64 truncate text-muted-foreground" title={dataset.source}>
                  {dataset.source}
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDate(dataset.created_at)}</TableCell>
                <TableCell className="text-right">
                  <AlertDialog>
                    <AlertDialogTrigger
                      render={
                        <Button variant="ghost" size="icon-sm" aria-label={`Delete ${dataset.name}`} />
                      }
                    >
                      <Trash2Icon />
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Delete {dataset.name}?</AlertDialogTitle>
                        <AlertDialogDescription>
                          This removes rowlab&apos;s copy of the data. The original file is not
                          touched.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction variant="destructive" onClick={() => remove(dataset)}>
                          Delete
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </main>
  );
}
