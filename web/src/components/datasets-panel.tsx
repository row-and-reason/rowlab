"use client";

import { Progress as ProgressPrimitive } from "@base-ui/react/progress";
import { KeyRoundIcon, MoonIcon, PlusIcon, SunIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";

import { PaneHeader } from "@/components/pane";
import { TooltipButton } from "@/components/tooltip-button";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from "@/components/ui/item";
import { Spinner } from "@/components/ui/spinner";
import { ProgressIndicator, ProgressTrack } from "@/components/ui/progress";
import type { Dataset, Settings } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";
import { isActive } from "@/lib/runs";
import { useSlideReorder } from "@/lib/use-slide-reorder";

type DatasetRun = NonNullable<Dataset["run"]>;

/** The left column: every dataset, added from a file or made by a run, and app-wide settings. */
export function DatasetsPanel({
  datasets,
  selectedId,
  settings,
  onAdd,
  onDelete,
  onKey,
}: {
  datasets: Dataset[] | null;
  selectedId: string | null;
  settings: Settings | undefined;
  onAdd: () => void;
  onDelete: (dataset: Dataset) => void;
  onKey: () => void;
}) {
  const { resolvedTheme, setTheme } = useTheme();
  // The newest dataset comes first; a run's dataset slides in at the top.
  const slideRef = useSlideReorder(datasets?.map((d) => d.id) ?? []);

  return (
    <div className="flex h-full flex-col">
      <PaneHeader>
        <span className="font-semibold">rowlab</span>
        <TooltipButton
          label="Add data"
          variant="ghost"
          size="icon-sm"
          className="ml-auto"
          onClick={onAdd}
        >
          <PlusIcon />
        </TooltipButton>
      </PaneHeader>

      <div className="min-h-0 flex-1 overflow-auto p-2">
        {datasets === null ? (
          <Spinner className="m-2" />
        ) : (
          <ItemGroup className="relative gap-0.5">
            {datasets.map((dataset) => (
              <div key={dataset.id} ref={slideRef(dataset.id)}>
                <ContextMenu>
                  <ContextMenuTrigger
                    render={
                      <Item
                        size="xs"
                        variant={dataset.id === selectedId ? "muted" : "default"}
                        className="relative overflow-hidden"
                        render={<Link href={`/?dataset=${dataset.id}`} />}
                      />
                    }
                  >
                    {dataset.run && isActive(dataset.run) && <RunProgress run={dataset.run} />}
                    <ItemContent className="min-w-0">
                      <ItemTitle className="w-full truncate" title={dataset.name}>
                        {dataset.name}
                      </ItemTitle>
                      <ItemDescription className="truncate text-xs">
                        {describe(dataset, datasets)}
                      </ItemDescription>
                    </ItemContent>
                  </ContextMenuTrigger>
                  <ContextMenuContent>
                    <ContextMenuItem variant="destructive" onClick={() => onDelete(dataset)}>
                      <Trash2Icon />
                      Delete
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>
              </div>
            ))}
          </ItemGroup>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1 border-t p-2">
        {settings?.openrouter_key === "environment" ? (
          <span className="px-2 text-xs text-muted-foreground">Key from environment</span>
        ) : (
          <Button
            variant={settings?.openrouter_key ? "ghost" : "default"}
            size="sm"
            onClick={onKey}
          >
            <KeyRoundIcon data-icon="inline-start" />
            {settings?.openrouter_key ? "OpenRouter key" : "Set OpenRouter key"}
          </Button>
        )}
        <TooltipButton
          label={resolvedTheme === "dark" ? "Light mode" : "Dark mode"}
          variant="ghost"
          size="icon-sm"
          className="ml-auto"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          {resolvedTheme === "dark" ? <SunIcon /> : <MoonIcon />}
        </TooltipButton>
      </div>
    </div>
  );
}

/** E.g. "600 rows · 12 columns", or "Run #1 of titanic · stopped" for one a run made. */
function describe(dataset: Dataset, datasets: Dataset[]): string {
  if (!dataset.run) {
    return `${formatNumber(dataset.row_count)} rows · ${dataset.columns.length - 1} columns`;
  }
  const parent = datasets.find((d) => d.id === dataset.parent_id)?.name ?? "a deleted dataset";
  const status =
    dataset.run.status === "done" ? `${formatNumber(dataset.row_count)} rows` : dataset.run.status;
  return `Run #${dataset.run.number} of ${parent} · ${status}`;
}

/** A thin bar along the top edge of a dataset a run is making: how many model calls are done. */
function RunProgress({ run }: { run: DatasetRun }) {
  const percent = run.total ? (100 * run.done) / run.total : 0;
  return (
    <ProgressPrimitive.Root
      value={percent}
      aria-label={`Run #${run.number}`}
      title={`Run #${run.number}: ${formatNumber(run.done)} of ${formatNumber(run.total)} answers`}
      className="absolute inset-x-0 top-0"
    >
      <ProgressTrack className="h-0.5 rounded-none bg-transparent">
        <ProgressIndicator />
      </ProgressTrack>
    </ProgressPrimitive.Root>
  );
}
