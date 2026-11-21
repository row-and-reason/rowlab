"use client";

import { Progress as ProgressPrimitive } from "@base-ui/react/progress";
import {
  ArchiveIcon,
  ArchiveRestoreIcon,
  ChevronRightIcon,
  ChevronUpIcon,
  CircleAlertIcon,
  CirclePauseIcon,
  CircleUserIcon,
  DownloadIcon,
  KeyRoundIcon,
  LogOutIcon,
  MoonIcon,
  PlugIcon,
  PlusIcon,
  SettingsIcon,
  SlidersHorizontalIcon,
  SunIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useEffect } from "react";

import { PaneHeader } from "@/components/pane";
import { TooltipButton } from "@/components/tooltip-button";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuRadioGroup,
  ContextMenuRadioItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { useCan, useMe } from "@/components/me";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@/components/ui/item";
import { ProgressIndicator, ProgressTrack } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { type DatasetSummary, type Settings, type Settling, signOut } from "@/lib/api/client";
import type { Section } from "@/lib/settings";
import { formatNumber } from "@/lib/format";
import { shelves, useShowSettled } from "@/lib/use-datasets";

/** The left column: every dataset, one per file, newest first, those settled (left alone) in a
 * section of their own; and app-wide settings. */
export function DatasetsPanel({
  datasets,
  selectedId,
  settings,
  onAdd,
  onExport,
  onRename,
  onDelete,
  onSettle,
  onAutoSettle,
  onSettings,
}: {
  datasets: DatasetSummary[] | null;
  selectedId: string | null;
  settings: Settings | undefined;
  onAdd: () => void;
  onExport: (dataset: DatasetSummary) => void;
  onRename: (dataset: DatasetSummary) => void;
  onDelete: (dataset: DatasetSummary) => void;
  onSettle: (dataset: DatasetSummary, body: Settling) => void;
  onAutoSettle: (on: boolean) => void;
  onSettings: (section: Section) => void;
}) {
  const { resolvedTheme, setTheme } = useTheme();
  const me = useMe();
  const canEdit = useCan("member");
  const canAdmin = useCan("admin");
  const [showSettled, setShowSettled] = useShowSettled();
  const { active, settled } = shelves(datasets ?? []);
  // The dataset open is always in view: selecting a settled one opens the section.
  const selectedSettled = settled.some((d) => d.id === selectedId);
  useEffect(() => {
    if (selectedSettled) setShowSettled(true);
  }, [selectedSettled, setShowSettled]);
  const autoDefault = settings?.auto_settle ?? true;
  const row = (dataset: DatasetSummary) => (
    <DatasetRow
      key={dataset.id}
      dataset={dataset}
      selected={dataset.id === selectedId}
      autoDefault={autoDefault}
      canEdit={canEdit}
      canAdmin={canAdmin}
      onExport={onExport}
      onRename={onRename}
      onDelete={onDelete}
      onSettle={onSettle}
    />
  );

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <PaneHeader>
        <span className="inline-flex items-center gap-1.5 pl-1.5 text-sm font-semibold">
          <span
            aria-hidden="true"
            className="size-4 bg-current [mask:url('/brand/mark.svg')_center/contain_no-repeat]"
          />
          rowlab
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button variant="ghost" size="icon-sm" className="ml-auto" aria-label="Display" />
            }
          >
            <SlidersHorizontalIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            <DropdownMenuCheckboxItem
              checked={autoDefault}
              disabled={!canAdmin || !settings}
              onCheckedChange={onAutoSettle}
            >
              Settle datasets idle for 24 hours
            </DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {canEdit && (
          <TooltipButton label="Add data" variant="ghost" size="icon-sm" onClick={onAdd}>
            <PlusIcon />
          </TooltipButton>
        )}
      </PaneHeader>

      <div className="min-h-0 flex-1 overflow-auto p-2">
        {datasets === null ? (
          <Spinner className="m-2" />
        ) : datasets.length === 0 ? (
          <p className="px-2 py-1 text-sm text-muted-foreground">No datasets yet.</p>
        ) : (
          <>
            <ItemGroup className="gap-0.5">{active.map(row)}</ItemGroup>
            {settled.length > 0 && (
              <Collapsible open={showSettled} onOpenChange={setShowSettled} className="mt-2">
                <CollapsibleTrigger
                  render={
                    <Button
                      variant="ghost"
                      size="xs"
                      className="group w-full justify-start text-muted-foreground"
                    />
                  }
                >
                  <ChevronRightIcon className="transition-transform group-data-[panel-open]:rotate-90" />
                  Settled · {settled.length}
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <ItemGroup className="gap-0.5 pt-0.5">{settled.map(row)}</ItemGroup>
                </CollapsibleContent>
              </Collapsible>
            )}
          </>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1 border-t p-2">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={<Button variant="ghost" size="sm" className="min-w-0 text-xs" />}
          >
            <CircleUserIcon data-icon="inline-start" />
            <span className="truncate">{me.user?.name ?? "Your account"}</span>
            <ChevronUpIcon data-icon="inline-end" />
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start" className="w-64">
            {me.user && (
              <>
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="truncate">
                    {me.user.email} · {me.org.name} · {me.role}
                  </DropdownMenuLabel>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
              </>
            )}
            {canAdmin && settings && !settings.provider && (
              <DropdownMenuItem onClick={() => onSettings("providers")}>
                <KeyRoundIcon />
                Add a model provider…
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={() => onSettings("providers")}>
              <SettingsIcon />
              Settings…
              <DropdownMenuShortcut>⌘,</DropdownMenuShortcut>
            </DropdownMenuItem>
            {me.user && (
              <>
                <DropdownMenuItem onClick={() => onSettings("api-keys")}>
                  <PlugIcon />
                  API keys…
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={signOut}>
                  <LogOutIcon />
                  Log out
                </DropdownMenuItem>
              </>
            )}
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

/** A dataset in the list, with its menu (right-click): rename, export, settle, delete. */
function DatasetRow({
  dataset,
  selected,
  autoDefault,
  canEdit,
  canAdmin,
  onExport,
  onRename,
  onDelete,
  onSettle,
}: {
  dataset: DatasetSummary;
  selected: boolean;
  /** Whether datasets settle by themselves unless one says otherwise. */
  autoDefault: boolean;
  canEdit: boolean;
  canAdmin: boolean;
  onExport: (dataset: DatasetSummary) => void;
  onRename: (dataset: DatasetSummary) => void;
  onDelete: (dataset: DatasetSummary) => void;
  onSettle: (dataset: DatasetSummary, body: Settling) => void;
}) {
  const auto = dataset.auto_settle === null ? "organisation" : dataset.auto_settle ? "on" : "off";
  return (
    <ContextMenu>
      <ContextMenuTrigger
        render={
          <Item
            size="xs"
            variant={selected ? "muted" : "default"}
            aria-current={selected ? "page" : undefined}
            className="relative min-w-0 flex-nowrap overflow-hidden aria-[current=page]:bg-sidebar-accent aria-[current=page]:text-sidebar-accent-foreground"
            render={<Link href={`/?dataset=${dataset.id}`} />}
          />
        }
      >
        {dataset.active_runs > 0 && <RunProgress dataset={dataset} />}
        <ItemContent className="min-w-0">
          <ItemTitle className="w-full truncate" title={dataset.name}>
            {dataset.name}
          </ItemTitle>
          <ItemDescription className="truncate text-xs">{describe(dataset)}</ItemDescription>
        </ItemContent>
        <RunStatus dataset={dataset} />
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem disabled={!canEdit} onClick={() => onRename(dataset)}>
          Rename…
        </ContextMenuItem>
        <ContextMenuItem disabled={!canEdit} onClick={() => onExport(dataset)}>
          <DownloadIcon />
          Export…
        </ContextMenuItem>
        <ContextMenuSeparator />
        {dataset.settled ? (
          <ContextMenuItem
            disabled={!canAdmin}
            onClick={() => onSettle(dataset, { settled: false })}
          >
            <ArchiveRestoreIcon />
            Unsettle
          </ContextMenuItem>
        ) : (
          <ContextMenuItem
            disabled={!canAdmin || dataset.active_runs > 0}
            onClick={() => onSettle(dataset, { settled: true })}
          >
            <ArchiveIcon />
            Settle
          </ContextMenuItem>
        )}
        <ContextMenuSub>
          <ContextMenuSubTrigger disabled={!canAdmin}>Settle by itself</ContextMenuSubTrigger>
          <ContextMenuSubContent>
            <ContextMenuRadioGroup
              value={auto}
              onValueChange={(value) =>
                onSettle(dataset, { auto_settle: value as NonNullable<Settling["auto_settle"]> })
              }
            >
              <ContextMenuRadioItem value="organisation">
                As set for all ({autoDefault ? "on" : "off"})
              </ContextMenuRadioItem>
              <ContextMenuRadioItem value="on">After 24 hours left alone</ContextMenuRadioItem>
              <ContextMenuRadioItem value="off">Never</ContextMenuRadioItem>
            </ContextMenuRadioGroup>
          </ContextMenuSubContent>
        </ContextMenuSub>
        <ContextMenuSeparator />
        <ContextMenuItem variant="destructive" disabled={!canEdit} onClick={() => onDelete(dataset)}>
          <Trash2Icon />
          Delete
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/** E.g. "600 rows · 3 answer columns". */
function describe(dataset: DatasetSummary): string {
  const rows = `${formatNumber(dataset.row_count)} rows`;
  if (!dataset.answer_columns) return rows;
  return `${rows} · ${dataset.answer_columns} answer column${dataset.answer_columns === 1 ? "" : "s"}`;
}

/** How the dataset's runs stand, unless all is well: going, or the newest failed or was stopped. */
function RunStatus({ dataset }: { dataset: DatasetSummary }) {
  const [icon, label] =
    dataset.active_runs > 0
      ? [<Spinner key="running" />, `${dataset.active_runs} running`]
      : dataset.last_run_status === "failed"
        ? [<CircleAlertIcon key="failed" className="text-destructive" />, "Its last run failed"]
        : dataset.last_run_status === "stopped"
          ? [<CirclePauseIcon key="stopped" />, "Its last run was stopped"]
          : [null, null];
  if (!icon) return null;
  return (
    // Whole pixels: with the 14px root, size-3.5 is 12.25px, and Safari turns a spinner that size
    // about a point off its centre, so it wobbles.
    <ItemActions
      role="img"
      aria-label={label!}
      title={label!}
      className="text-muted-foreground [&_svg]:size-[12px]"
    >
      {icon}
    </ItemActions>
  );
}

/** A thin bar along the top edge of a dataset runs are adding to: how many of their answers are in. */
function RunProgress({ dataset }: { dataset: DatasetSummary }) {
  const percent = dataset.active_total ? (100 * dataset.active_done) / dataset.active_total : 0;
  return (
    <ProgressPrimitive.Root
      value={percent}
      aria-label="Progress"
      title={`${formatNumber(dataset.active_done)} of ${formatNumber(dataset.active_total)} answers`}
      className="absolute inset-x-0 top-0"
    >
      <ProgressTrack className="h-0.5 rounded-none bg-transparent">
        <ProgressIndicator />
      </ProgressTrack>
    </ProgressPrimitive.Root>
  );
}
