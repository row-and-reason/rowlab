"use client";

import {
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

import { PaneHeader } from "@/components/pane";
import { TooltipButton } from "@/components/tooltip-button";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { useCan, useMe } from "@/components/me";
import {
  DropdownMenu,
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
import { Spinner } from "@/components/ui/spinner";
import { type DatasetSummary, type Settings, signOut } from "@/lib/api/client";
import type { Section } from "@/lib/settings";
import { formatNumber } from "@/lib/format";

/** The left column: every dataset, one per file, newest first, and app-wide settings. */
export function DatasetsPanel({
  datasets,
  selectedId,
  settings,
  onAdd,
  onExport,
  onRename,
  onDelete,
  onSettings,
}: {
  datasets: DatasetSummary[] | null;
  selectedId: string | null;
  settings: Settings | undefined;
  onAdd: () => void;
  onExport: (dataset: DatasetSummary) => void;
  onRename: (dataset: DatasetSummary) => void;
  onDelete: (dataset: DatasetSummary) => void;
  onSettings: (section: Section) => void;
}) {
  const { resolvedTheme, setTheme } = useTheme();
  const me = useMe();
  const canEdit = useCan("member");
  const canAdmin = useCan("admin");

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
        {canEdit && (
          <TooltipButton
            label="Add data"
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            onClick={onAdd}
          >
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
          <ItemGroup className="gap-0.5">
            {datasets.map((dataset) => (
              <ContextMenu key={dataset.id}>
                <ContextMenuTrigger
                  render={
                    <Item
                      size="xs"
                      variant={dataset.id === selectedId ? "muted" : "default"}
                      aria-current={dataset.id === selectedId ? "page" : undefined}
                      className="min-w-0 flex-nowrap aria-[current=page]:bg-sidebar-accent aria-[current=page]:text-sidebar-accent-foreground"
                      render={<Link href={`/?dataset=${dataset.id}`} />}
                    />
                  }
                >
                  <ItemContent className="min-w-0">
                    <ItemTitle className="w-full truncate" title={dataset.name}>
                      {dataset.name}
                    </ItemTitle>
                    <ItemDescription className="truncate text-xs">
                      {describe(dataset)}
                    </ItemDescription>
                  </ItemContent>
                  {dataset.active_runs > 0 && (
                    <ItemActions title={`${dataset.active_runs} running`}>
                      <Spinner className="size-3" />
                    </ItemActions>
                  )}
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem disabled={!canEdit} onClick={() => onRename(dataset)}>
                    Rename…
                  </ContextMenuItem>
                  <ContextMenuItem disabled={!canEdit} onClick={() => onExport(dataset)}>
                    <DownloadIcon />
                    Export…
                  </ContextMenuItem>
                  <ContextMenuItem
                    variant="destructive"
                    disabled={!canEdit}
                    onClick={() => onDelete(dataset)}
                  >
                    <Trash2Icon />
                    Delete
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
          </ItemGroup>
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

/** E.g. "600 rows · 3 answer columns". */
function describe(dataset: DatasetSummary): string {
  const rows = `${formatNumber(dataset.row_count)} rows`;
  if (!dataset.answer_columns) return rows;
  return `${rows} · ${dataset.answer_columns} answer column${dataset.answer_columns === 1 ? "" : "s"}`;
}
