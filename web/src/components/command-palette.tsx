"use client";

import {
  DownloadIcon,
  GitCompareArrowsIcon,
  ListChecksIcon,
  ListRestartIcon,
  MoonIcon,
  PenLineIcon,
  PlayIcon,
  PlusIcon,
  SearchIcon,
  SettingsIcon,
  TableIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
import type { RefObject } from "react";

import type { Tab, TaskActions } from "@/components/dataset-view";
import { useMe } from "@/components/me";
import type { OriginActions } from "@/components/origin";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import type { Dataset } from "@/lib/api/client";
import { useTaskTypes } from "@/lib/catalog";
import { type Section, sections } from "@/lib/settings";
import type { ComparisonActions } from "@/lib/use-comparison";

/** The ⌘K palette: actions on the selected dataset and its open tab, settings, and every dataset. */
export function CommandPalette({
  open,
  onOpenChange,
  datasets,
  selected,
  tab,
  canEdit,
  exportable,
  comparisonReady,
  originActionsRef,
  taskActionsRef,
  comparisonActionsRef,
  onSelect,
  onRename,
  onExport,
  onAdd,
  onSettings,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  datasets: Dataset[] | null;
  selected: Dataset | undefined;
  tab: Tab;
  canEdit: boolean;
  exportable: boolean;
  comparisonReady: boolean;
  originActionsRef: RefObject<OriginActions | null>;
  taskActionsRef: RefObject<TaskActions | null>;
  comparisonActionsRef: RefObject<ComparisonActions | null>;
  onSelect: (id: string) => void;
  onRename: (dataset: Dataset) => void;
  onExport: (dataset: Dataset) => void;
  onAdd: () => void;
  onSettings: (section: Section) => void;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const { resolvedTheme, setTheme } = useTheme();
  const taskTypes = useTaskTypes();
  const me = useMe();

  // Runs a palette command after closing the palette.
  function command(action: () => void) {
    onOpenChange(false);
    action();
  }

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <Command>
        <CommandInput placeholder="Type a command or a dataset name" />
        <CommandList>
          <CommandEmpty>Nothing found.</CommandEmpty>
          <CommandGroup heading="Actions">
            {selected && (
              <>
                <CommandItem disabled={!canEdit} onSelect={() => command(() => onRename(selected))}>
                  Rename dataset…
                </CommandItem>
                <CommandItem
                  onSelect={() =>
                    command(() => {
                      const query = new URLSearchParams(params);
                      query.set("tab", "compare");
                      router.push(`/?${query}`);
                    })
                  }
                >
                  <GitCompareArrowsIcon />
                  Compare columns
                </CommandItem>
                <CommandItem
                  onSelect={() =>
                    command(() => {
                      const query = new URLSearchParams(window.location.search);
                      query.set("tab", "origin");
                      router.push(`/?${query}`);
                    })
                  }
                >
                  View origin
                </CommandItem>
                {tab === "origin" &&
                  canEdit &&
                  selected.run &&
                  datasets?.some((d) => d.id === selected.parent_id) && (
                    <CommandItem onSelect={() => command(() => originActionsRef.current?.edit?.())}>
                      Edit original run settings
                    </CommandItem>
                  )}
              </>
            )}
            {selected && tab === "compare" && (
              <>
                <CommandItem
                  disabled={!comparisonReady}
                  onSelect={() => command(() => comparisonActionsRef.current?.different?.())}
                >
                  <GitCompareArrowsIcon />
                  Inspect different rows<CommandShortcut>⌘↵</CommandShortcut>
                </CommandItem>
                <CommandItem
                  onSelect={() =>
                    command(() => setTimeout(() => comparisonActionsRef.current?.rules?.(), 50))
                  }
                >
                  <SettingsIcon />
                  Comparison match rules
                </CommandItem>
                <CommandItem
                  onSelect={() =>
                    command(() => setTimeout(() => comparisonActionsRef.current?.columns?.(), 50))
                  }
                >
                  <TableIcon />
                  Choose compared columns
                </CommandItem>
              </>
            )}
            {selected && canEdit && (
              <>
                {tab !== "compare" && (
                  <>
                    <CommandItem onSelect={() => command(() => taskActionsRef.current?.run())}>
                      <PlayIcon />
                      Label selected rows
                      <CommandShortcut>⌘↵</CommandShortcut>
                    </CommandItem>
                    <CommandItem onSelect={() => command(() => taskActionsRef.current?.manual())}>
                      Label manually
                    </CommandItem>
                    {selected.run?.status === "manual" && (
                      <CommandItem onSelect={() => command(() => taskActionsRef.current?.finish())}>
                        Finish labeling
                      </CommandItem>
                    )}
                    <CommandItem
                      onSelect={() => command(() => taskActionsRef.current?.clearTasks())}
                    >
                      <ListRestartIcon />
                      Clear tasks
                    </CommandItem>
                    <CommandItem onSelect={() => command(() => taskActionsRef.current?.addTask())}>
                      <ListChecksIcon />
                      Add task
                    </CommandItem>
                    {taskTypes?.presets.map((preset) => (
                      <CommandItem
                        key={preset.id}
                        value={`add ${preset.label} task`}
                        onSelect={() => command(() => taskActionsRef.current?.addTask(preset))}
                      >
                        <PenLineIcon />
                        {preset.label}…
                      </CommandItem>
                    ))}
                    <CommandItem
                      onSelect={() =>
                        command(() =>
                          // Once the palette has closed and handed focus back.
                          setTimeout(() => document.getElementById("rows-search")?.focus(), 50),
                        )
                      }
                    >
                      <SearchIcon />
                      Search rows
                      <CommandShortcut>/</CommandShortcut>
                    </CommandItem>
                  </>
                )}
                {exportable && (
                  <CommandItem onSelect={() => command(() => onExport(selected))}>
                    <DownloadIcon />
                    Export dataset…
                    <CommandShortcut>E</CommandShortcut>
                  </CommandItem>
                )}
              </>
            )}
            {canEdit && (
              <CommandItem onSelect={() => command(onAdd)}>
                <PlusIcon />
                Add data
              </CommandItem>
            )}
            {sections(me).map((section) => (
              <CommandItem
                key={section.id}
                value={`settings ${section.label} ${section.keywords}`}
                onSelect={() => command(() => onSettings(section.id))}
              >
                <SettingsIcon />
                Settings: {section.label}
                {section.id === "providers" && <CommandShortcut>⌘,</CommandShortcut>}
              </CommandItem>
            ))}
            <CommandItem
              onSelect={() => command(() => setTheme(resolvedTheme === "dark" ? "light" : "dark"))}
            >
              <MoonIcon />
              {resolvedTheme === "dark" ? "Light mode" : "Dark mode"}
            </CommandItem>
          </CommandGroup>
          <CommandGroup heading="Datasets">
            {datasets?.map((dataset) => (
              <CommandItem
                key={dataset.id}
                value={`dataset ${dataset.name} ${dataset.id}`}
                onSelect={() => command(() => onSelect(dataset.id))}
              >
                <TableIcon />
                {dataset.name}
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </Command>
    </CommandDialog>
  );
}
