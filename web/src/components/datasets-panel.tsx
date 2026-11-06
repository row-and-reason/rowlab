"use client";

import { Progress as ProgressPrimitive } from "@base-ui/react/progress";
import {
  ChevronRightIcon,
  KeyRoundIcon,
  MoonIcon,
  PlusIcon,
  SunIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useMemo, useState } from "react";

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
import { datasetTree } from "@/lib/dataset-tree";
import { formatNumber } from "@/lib/format";
import { isActive } from "@/lib/runs";
import { useSlideReorder } from "@/lib/use-slide-reorder";

type DatasetRun = NonNullable<Dataset["run"]>;

const MAX_INDENT = 3;

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
  const [collapsed, setCollapsed] = useState(new Set<string>());
  const rows = useMemo(() => datasetTree(datasets ?? [], collapsed), [datasets, collapsed]);
  // A run brings its dataset's family to the top: it slides there.
  const slideRef = useSlideReorder(rows.map((r) => r.dataset.id));

  function toggle(id: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

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
            {rows.map(({ dataset, depth, hasChildren, open }) => (
              <div
                key={dataset.id}
                ref={slideRef(dataset.id)}
                className="flex items-center gap-0.5"
                // Deep chains stop indenting, so names stay readable in a narrow column.
                style={{ paddingLeft: Math.min(depth, MAX_INDENT) * 12 }}
              >
                {hasChildren ? (
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={open ? "Hide what was made from it" : "Show what was made from it"}
                    aria-expanded={open}
                    onClick={() => toggle(dataset.id)}
                  >
                    <ChevronRightIcon
                      className={open ? "rotate-90 transition-transform" : "transition-transform"}
                    />
                  </Button>
                ) : (
                  <span className="w-6 shrink-0" />
                )}
                <ContextMenu>
                  <ContextMenuTrigger
                    render={
                      <Item
                        size="xs"
                        variant={dataset.id === selectedId ? "muted" : "default"}
                        className="relative min-w-0 flex-1 overflow-hidden"
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
                        {describe(dataset)}
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

/** E.g. "600 rows · 12 columns", or "Run #1 · stopped" for one a run made. */
function describe(dataset: Dataset): string {
  if (!dataset.run) {
    return `${formatNumber(dataset.row_count)} rows · ${dataset.columns.length - 1} columns`;
  }
  const status =
    dataset.run.status === "done" ? `${formatNumber(dataset.row_count)} rows` : dataset.run.status;
  return `Run #${dataset.run.number} · ${status}`;
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
