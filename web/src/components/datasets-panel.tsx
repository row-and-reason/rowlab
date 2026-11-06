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
import { useSlideReorder } from "@/lib/use-slide-reorder";

type RunProgressData = NonNullable<Dataset["running"]>;

/** The left column: every dataset, uploaded or produced by a run, and app-wide settings. */
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
  // The most recently active dataset comes first; a run moves its dataset to the top.
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
                    {dataset.running && <RunProgress progress={dataset.running} />}
                    <ItemContent className="min-w-0">
                      <ItemTitle className="w-full truncate" title={dataset.name}>
                        {dataset.name}
                      </ItemTitle>
                      <ItemDescription className="text-xs">
                        {formatNumber(dataset.row_count)} rows · {dataset.columns.length - 1}{" "}
                        columns
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

/** A thin bar along the top edge of a dataset whose run is going: how many model calls are done. */
function RunProgress({ progress }: { progress: RunProgressData }) {
  const percent = progress.total ? (100 * progress.done) / progress.total : 0;
  return (
    <ProgressPrimitive.Root
      value={percent}
      aria-label={`Run #${progress.number}`}
      title={`Run #${progress.number}: ${formatNumber(progress.done)} of ${formatNumber(progress.total)} answers`}
      className="absolute inset-x-0 top-0"
    >
      <ProgressTrack className="h-0.5 rounded-none bg-transparent">
        <ProgressIndicator />
      </ProgressTrack>
    </ProgressPrimitive.Root>
  );
}
