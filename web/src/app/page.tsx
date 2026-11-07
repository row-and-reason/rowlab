"use client";

import {
  CloudIcon,
  DatabaseIcon,
  DownloadIcon,
  GlobeIcon,
  ListChecksIcon,
  ListRestartIcon,
  MoonIcon,
  PenLineIcon,
  PlayIcon,
  PlusIcon,
  SearchIcon,
  SettingsIcon,
  TableIcon,
  UploadIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
import { Suspense, use, useCallback, useEffect, useRef, useState } from "react";
import { browser } from "react-dom";
import { useDefaultLayout } from "react-resizable-panels";
import { toast } from "sonner";

import { AddDataset, type SourceKind } from "@/components/add-dataset";
import { DatasetPanels, TABS, type TaskActions, type Tab } from "@/components/dataset-view";
import { DatasetsPanel } from "@/components/datasets-panel";
import { ExportDataset } from "@/components/export-dataset";
import { useCan, useMe } from "@/components/me";
import { PaneHeader } from "@/components/pane";
import { Keys } from "@/components/tooltip-button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Spinner } from "@/components/ui/spinner";
import { api, type Dataset, type Settings } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";
import { useTaskTypes } from "@/lib/catalog";
import { datasetTree } from "@/lib/dataset-tree";
import { loadDraft } from "@/lib/draft";
import { isActive } from "@/lib/runs";
import { viewSql } from "@/lib/sql";
import { type Section, sections, settingsUrl } from "@/lib/settings";

// The whole app is this one page: datasets | rows | job, in resizable columns. What is selected lives
// in the query string (`/?dataset=<id>&tab=rows`), because a static export can't have routes for
// ids that only exist at runtime. Changing it is a client-side navigation, so the columns stay mounted.
export default function Home() {
  return (
    <Suspense fallback={<Spinner className="m-6" />}>
      <Workspace />
    </Suspense>
  );
}

function Workspace() {
  use(browser("Column widths are stored in localStorage."));
  const router = useRouter();
  const params = useSearchParams();
  const { resolvedTheme, setTheme } = useTheme();
  const selectedId = params.get("dataset");
  const tab: Tab = TABS.find((t) => t === params.get("tab")) ?? "rows";
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [settings, setSettings] = useState<Settings>();
  // Open with "add data" at its first step, or at a source's step when that's already picked.
  const [adding, setAdding] = useState<SourceKind | "choose">();
  const openSettings = useCallback(
    (section: Section) => router.push(settingsUrl(params, section)),
    [router, params],
  );
  const [deleting, setDeleting] = useState<Dataset>();
  const [exporting, setExporting] = useState<Dataset>();
  const [palette, setPalette] = useState(false);
  const taskActionsRef = useRef<TaskActions | null>(null);
  const taskTypes = useTaskTypes();
  const me = useMe();
  // Verifiers read; adding, running and exporting need a member.
  const canEdit = useCan("member");
  // Remembers the column widths you drag to, in localStorage.
  const layout = useDefaultLayout({ id: "rowlab.workspace" });

  const load = useCallback(async () => {
    const { data, error } = await api.GET("/v1/datasets");
    if (error) toast.error(errorMessage(error));
    else setDatasets(data);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    load();
    api.GET("/v1/settings").then(({ data }) => setSettings(data));
  }, [load]);

  // While a run is going, keep its progress and its dataset's rows current.
  const anyRunning = datasets?.some((d) => d.run && isActive(d.run)) ?? false;
  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(load, 1000);
    return () => clearInterval(timer);
  }, [anyRunning, load]);

  const selected = datasets?.find((d) => d.id === selectedId);
  // A dataset a run is still making can't be exported yet.
  const exportable = canEdit && !!selected && !(selected.run && isActive(selected.run));
  const select = useCallback((id: string) => router.push(`/?dataset=${id}`), [router]);

  // Keyboard shortcuts. ⌘K and ⌘↵ work everywhere; single keys only when not typing.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === ",") {
        e.preventDefault();
        openSettings("providers");
      } else if (mod && e.key === "k") {
        e.preventDefault();
        setPalette((open) => !open);
      } else if (mod && e.key === "Enter") {
        e.preventDefault();
        taskActionsRef.current?.run();
      } else if (!mod && !e.altKey && !isTyping(e.target)) {
        if ((e.key === "j" || e.key === "k") && datasets?.length) {
          // In the list's order, made datasets under the one they were made from.
          const order = datasetTree(datasets).map((r) => r.dataset.id);
          const index = order.indexOf(selectedId ?? "");
          const next = e.key === "j" ? index + 1 : index - 1;
          select(order[Math.min(order.length - 1, Math.max(0, next))]);
        } else if (e.key === "/") {
          e.preventDefault();
          document.getElementById("rows-search")?.focus();
        } else if (e.key === "e" && exportable) {
          e.preventDefault();
          setExporting(selected);
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [datasets, selectedId, select, selected, exportable, openSettings]);

  async function remove(dataset: Dataset) {
    const { error } = await api.DELETE("/v1/datasets/{dataset_id}", {
      params: { path: { dataset_id: dataset.id } },
    });
    if (error) toast.error(errorMessage(error));
    else toast.success(`Deleted ${dataset.name}`);
    if (dataset.id === selectedId) router.push("/");
    load();
  }

  // Runs a palette command after closing the palette.
  function command(action: () => void) {
    setPalette(false);
    action();
  }

  return (
    <main className="min-h-0 flex-1">
      <ResizablePanelGroup
        defaultLayout={layout.defaultLayout}
        onLayoutChanged={layout.onLayoutChanged}
      >
        <ResizablePanel id="datasets" defaultSize="16" minSize="10">
          <DatasetsPanel
            datasets={datasets}
            selectedId={selectedId}
            settings={settings}
            onAdd={() => setAdding("choose")}
            onExport={setExporting}
            onDelete={setDeleting}
            onSettings={openSettings}
          />
        </ResizablePanel>
        {selected ? (
          <DatasetPanels
            key={selected.id}
            dataset={selected}
            datasets={datasets ?? []}
            tab={tab}
            onTabChange={(t) => router.push(`/?dataset=${selected.id}&tab=${t}`)}
            onExport={() => setExporting(selected)}
            onDelete={() => setDeleting(selected)}
            onChanged={load}
            onOpenDataset={select}
            actionsRef={taskActionsRef}
          />
        ) : (
          <>
            <ResizableHandle />
            <ResizablePanel id="rows" defaultSize="50" minSize="30">
              <div className="flex h-full flex-col">
                <PaneHeader>
                  <span className="font-medium">Rows</span>
                </PaneHeader>
                {datasets === null ? (
                  <Spinner className="m-3" />
                ) : datasets.length === 0 ? (
                  <Empty className="flex-1">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <DatabaseIcon />
                      </EmptyMedia>
                      <EmptyTitle>
                        {canEdit ? "Add your first dataset" : "No datasets yet"}
                      </EmptyTitle>
                      <EmptyDescription>
                        {canEdit
                          ? "A CSV, TSV, JSON, JSONL or Parquet file, from this computer, S3 or the web. Then ask questions about each of its rows."
                          : "A member of your organisation adds them."}
                      </EmptyDescription>
                    </EmptyHeader>
                    {canEdit && (
                      <EmptyContent className="flex-row justify-center">
                        <Button size="sm" onClick={() => setAdding("file")}>
                          <UploadIcon data-icon="inline-start" />
                          Upload a file
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setAdding("s3")}>
                          <CloudIcon data-icon="inline-start" />
                          From S3
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setAdding("web")}>
                          <GlobeIcon data-icon="inline-start" />
                          From the web
                        </Button>
                      </EmptyContent>
                    )}
                  </Empty>
                ) : (
                  <Empty className="flex-1">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <DatabaseIcon />
                      </EmptyMedia>
                      <EmptyTitle>{selectedId ? "Dataset not found" : "Pick a dataset"}</EmptyTitle>
                      <EmptyDescription>
                        Choose one on the left, or press <Keys keys={["⌘", "K"]} />.
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                )}
              </div>
            </ResizablePanel>
            <ResizableHandle />
            <ResizablePanel id="job" defaultSize="34" minSize="20">
              <div className="flex h-full flex-col">
                <PaneHeader>
                  <span className="font-medium">Job</span>
                </PaneHeader>
                <Empty className="flex-1">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <ListChecksIcon />
                    </EmptyMedia>
                    <EmptyDescription>
                      {datasets?.length === 0
                        ? "Once there's a dataset, its tasks go here."
                        : "Pick a dataset to ask questions about each of its rows."}
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              </div>
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>

      <CommandDialog open={palette} onOpenChange={setPalette}>
        <Command>
          <CommandInput placeholder="Type a command or a dataset name" />
          <CommandList>
            <CommandEmpty>Nothing found.</CommandEmpty>
            <CommandGroup heading="Actions">
              {selected && canEdit && (
                <>
                  <CommandItem onSelect={() => command(() => taskActionsRef.current?.run())}>
                    <PlayIcon />
                    Run
                    <CommandShortcut>⌘↵</CommandShortcut>
                  </CommandItem>
                  <CommandItem onSelect={() => command(() => taskActionsRef.current?.clearTasks())}>
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
                  {exportable && (
                    <CommandItem onSelect={() => command(() => setExporting(selected))}>
                      <DownloadIcon />
                      Export dataset…
                      <CommandShortcut>E</CommandShortcut>
                    </CommandItem>
                  )}
                </>
              )}
              {canEdit && (
                <CommandItem onSelect={() => command(() => setAdding("choose"))}>
                  <PlusIcon />
                  Add data
                </CommandItem>
              )}
              {sections(me).map((section) => (
                <CommandItem
                  key={section.id}
                  value={`settings ${section.label} ${section.keywords}`}
                  onSelect={() => command(() => openSettings(section.id))}
                >
                  <SettingsIcon />
                  Settings: {section.label}
                  {section.id === "providers" && <CommandShortcut>⌘,</CommandShortcut>}
                </CommandItem>
              ))}
              <CommandItem
                onSelect={() =>
                  command(() => setTheme(resolvedTheme === "dark" ? "light" : "dark"))
                }
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
                  onSelect={() => command(() => select(dataset.id))}
                >
                  <TableIcon />
                  {dataset.name}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </CommandDialog>

      <AddDataset
        // A new start each time it opens, at the step it was opened for.
        key={adding ?? "closed"}
        open={!!adding}
        startAt={adding === "choose" ? undefined : adding}
        onOpenChange={(open) => !open && setAdding(undefined)}
        onAdded={(dataset) => {
          load();
          select(dataset.id);
        }}
      />
      {exporting && (
        <ExportDataset
          key={exporting.id}
          dataset={exporting}
          tableSql={tableSql(exporting)}
          open
          onOpenChange={(open) => !open && setExporting(undefined)}
        />
      )}
      <AlertDialog open={!!deleting} onOpenChange={(open) => !open && setDeleting(undefined)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleting?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes rowlab&apos;s copy of the data and its job. The original file is not
              touched.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (deleting) remove(deleting);
                setDeleting(undefined);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}

/** The query behind the rows a dataset's table shows, if its draft has one. */
function tableSql(dataset: Dataset): string | null {
  const draft = loadDraft(dataset.id);
  return draft ? viewSql(draft.view, dataset.columns) : null;
}

/** Whether a key press is going into a text field, where single-key shortcuts must not fire. */
function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}
