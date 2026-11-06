"use client";

import { Trash2Icon } from "lucide-react";

import { ColumnProfiles } from "@/components/column-profiles";
import { DatasetExplorer } from "@/components/dataset-explorer";
import { PromptComposer } from "@/components/prompt-composer";
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
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Dataset } from "@/lib/api/client";
import { formatBytes, formatNumber } from "@/lib/format";

export const TABS = ["rows", "columns", "prompt"] as const;
export type Tab = (typeof TABS)[number];

/** The middle column: a dataset's rows, column profiles and prompt. */
export function DatasetView({
  dataset,
  tab,
  onTabChange,
  onDelete,
}: {
  dataset: Dataset;
  tab: Tab;
  onTabChange: (tab: Tab) => void;
  onDelete: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate font-semibold">{dataset.name}</h2>
          <p className="truncate text-sm text-muted-foreground" title={dataset.source}>
            {formatNumber(dataset.row_count)} rows · {dataset.columns.length - 1} columns ·{" "}
            {formatBytes(dataset.size_bytes)} · {dataset.source}
          </p>
        </div>
        <AlertDialog>
          <AlertDialogTrigger
            render={<Button variant="ghost" size="icon-sm" aria-label={`Delete ${dataset.name}`} />}
          >
            <Trash2Icon />
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete {dataset.name}?</AlertDialogTitle>
              <AlertDialogDescription>
                This removes rowlab&apos;s copy of the data. The original file is not touched.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction variant="destructive" onClick={onDelete}>
                Delete
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
      <Tabs value={tab} onValueChange={(value) => onTabChange(value as Tab)}>
        <TabsList>
          <TabsTrigger value="rows">Rows</TabsTrigger>
          <TabsTrigger value="columns">Columns</TabsTrigger>
          <TabsTrigger value="prompt">Prompt</TabsTrigger>
        </TabsList>
        <TabsContent value="rows" keepMounted>
          <DatasetExplorer dataset={dataset} />
        </TabsContent>
        <TabsContent value="columns">
          <ColumnProfiles datasetId={dataset.id} />
        </TabsContent>
        <TabsContent value="prompt" keepMounted>
          <PromptComposer dataset={dataset} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
