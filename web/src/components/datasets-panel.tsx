"use client";

import { Progress as ProgressPrimitive } from "@base-ui/react/progress";
import {
  ChevronRightIcon,
  ChevronUpIcon,
  CircleUserIcon,
  DownloadIcon,
  KeyRoundIcon,
  LogOutIcon,
  MoonIcon,
  PlugIcon,
  PlusIcon,
  SettingsIcon,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from "@/components/ui/item";
import { Spinner } from "@/components/ui/spinner";
import { ProgressIndicator, ProgressTrack } from "@/components/ui/progress";
import type { Dataset, Settings } from "@/lib/api/client";
import { datasetTree } from "@/lib/dataset-tree";
import type { Section } from "@/lib/settings";
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
  onExport,
  onDelete,
  onSettings,
}: {
  datasets: Dataset[] | null;
  selectedId: string | null;
  settings: Settings | undefined;
  onAdd: () => void;
  onExport: (dataset: Dataset) => void;
  onDelete: (dataset: Dataset) => void;
  onSettings: (section: Section) => void;
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
        ) : datasets.length === 0 ? (
          <p className="px-2 py-1 text-sm text-muted-foreground">No datasets yet.</p>
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
                    <ContextMenuItem
                      disabled={!!dataset.run && isActive(dataset.run)}
                      onClick={() => onExport(dataset)}
                    >
                      <DownloadIcon />
                      Export…
                    </ContextMenuItem>
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
        {/* Will show who is signed in, once there are accounts. */}
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="ghost" size="sm" />}>
            <CircleUserIcon data-icon="inline-start" />
            Your account
            <ChevronUpIcon data-icon="inline-end" />
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start" className="w-64">
            {settings && !settings.openrouter_key && (
              <DropdownMenuItem onClick={() => onSettings("providers")}>
                <KeyRoundIcon />
                Set your OpenRouter key…
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={() => onSettings("providers")}>
              <SettingsIcon />
              Settings…
              <DropdownMenuShortcut>⌘,</DropdownMenuShortcut>
            </DropdownMenuItem>
            <DropdownMenuItem disabled>
              <PlugIcon />
              API keys & MCP connections
              <DropdownMenuShortcut>Soon</DropdownMenuShortcut>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem disabled>
              <LogOutIcon />
              Log out
              <DropdownMenuShortcut>Soon</DropdownMenuShortcut>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
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

/** E.g. "600 rows · 12 columns", with how its run stands while that isn't done, e.g. "· stopped". */
function describe(dataset: Dataset): string {
  const size = `${formatNumber(dataset.row_count)} rows · ${dataset.columns.length - 1} columns`;
  return dataset.run && dataset.run.status !== "done" ? `${size} · ${dataset.run.status}` : size;
}

/** A thin bar along the top edge of a dataset a run is making: how many model calls are done. */
function RunProgress({ run }: { run: DatasetRun }) {
  const percent = run.total ? (100 * run.done) / run.total : 0;
  return (
    <ProgressPrimitive.Root
      value={percent}
      aria-label="Progress"
      title={`${formatNumber(run.done)} of ${formatNumber(run.total)} answers`}
      className="absolute inset-x-0 top-0"
    >
      <ProgressTrack className="h-0.5 rounded-none bg-transparent">
        <ProgressIndicator />
      </ProgressTrack>
    </ProgressPrimitive.Root>
  );
}
