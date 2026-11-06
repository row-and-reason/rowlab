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
  ScanTextIcon,
  PencilIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
import {
  Suspense,
  use,
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { browser } from "react-dom";
import { useDefaultLayout } from "react-resizable-panels";
import { toast } from "sonner";

import { AddDataset, type SourceKind } from "@/components/add-dataset";
import { DatasetPanels, TABS, type TaskActions, type Tab } from "@/components/dataset-view";
import { DatasetsPanel } from "@/components/datasets-panel";
import { ExportDataset } from "@/components/export-dataset";
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel, FieldError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
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
import { isActive } from "@/lib/runs";
import { type Section, settingsUrl } from "@/lib/settings";

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
  const [exportSql, setExportSql] = useState<string>();
  const [palette, setPalette] = useState(false);
  const [renaming, setRenaming] = useState<Dataset>();
  const [browse, setBrowse] = useState(false);
  const compact = useSyncExternalStore(subscribeWidth, narrowWidth, () => false);
  const taskActionsRef = useRef<TaskActions | null>(null);
  const taskTypes = useTaskTypes();
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
  const exportable = !!selected && !(selected.run && isActive(selected.run));
  const select = useCallback((id: string) => router.push(`/?dataset=${id}`), [router]);

  const openExport = useCallback(
    (dataset: Dataset) => {
      setExportSql(dataset.id === selectedId ? taskActionsRef.current?.sql : undefined);
      setExporting(dataset);
    },
    [selectedId],
  );

  // Keyboard shortcuts. ⌘K and ⌘↵ work everywhere; single keys only when not typing.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (
        e.defaultPrevented ||
        document.querySelector('[role="dialog"][data-open], [role="alertdialog"][data-open]')
      )
        return;
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
      } else if (
        !mod &&
        !e.altKey &&
        !isTyping(e.target) &&
        !document.querySelector("[data-row-review]")
      ) {
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
          openExport(selected);
        } else if (e.key === "r" && selected) {
          e.preventDefault();
          taskActionsRef.current?.review();
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [datasets, selectedId, select, selected, exportable, openSettings, openExport]);

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

  const sidebar = (
    <DatasetsPanel
      datasets={datasets}
      selectedId={selectedId}
      settings={settings}
      onAdd={() => {
        setBrowse(false);
        setAdding("choose");
      }}
      onExport={(dataset) => {
        setBrowse(false);
        openExport(dataset);
      }}
      onDelete={(dataset) => {
        setBrowse(false);
        setDeleting(dataset);
      }}
      onSettings={(section) => {
        setBrowse(false);
        openSettings(section);
      }}
      onRename={(dataset) => {
        setBrowse(false);
        setRenaming(dataset);
      }}
      onSelected={() => setBrowse(false)}
    />
  );
  const panels = selected ? (
    <DatasetPanels
      key={selected.id}
      dataset={selected}
      datasets={datasets ?? []}
      tab={tab}
      onTabChange={(t) => router.push(`/?dataset=${selected.id}&tab=${t}`)}
      onExport={() => openExport(selected)}
      onDelete={() => setDeleting(selected)}
      onRename={() => setRenaming(selected)}
      onChanged={load}
      onOpenDataset={select}
      actionsRef={taskActionsRef}
      compact={compact}
      providerConnected={settings ? !!settings.openrouter_key : undefined}
    />
  ) : null;

  return (
    <main className="min-h-0 flex-1">
      {compact ? (
        <div className="flex h-full min-h-0 flex-col">
          <PaneHeader>
            <Button size="sm" variant="outline" onClick={() => setBrowse(true)}>
              <DatabaseIcon />
              Datasets
            </Button>
            <span className="font-semibold">rowlab</span>
            <Button
              className="ml-auto"
              size="sm"
              variant="ghost"
              onClick={() => openSettings("providers")}
            >
              <SettingsIcon />
              Settings
            </Button>
          </PaneHeader>
          <div className="min-h-0 flex-1">
            {panels ?? (
              <Empty>
                <EmptyHeader>
                  <EmptyTitle>
                    {datasets?.length ? "Choose a dataset" : "Add your first dataset"}
                  </EmptyTitle>
                  <EmptyDescription>
                    Load a file, review a sample, and run tasks on its rows.
                  </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                  <Button
                    size="sm"
                    onClick={() => (datasets?.length ? setBrowse(true) : setAdding("choose"))}
                  >
                    {datasets?.length ? "Choose dataset" : "Add data"}
                  </Button>
                </EmptyContent>
              </Empty>
            )}
          </div>
          <Dialog open={browse} onOpenChange={setBrowse}>
            <DialogContent className="flex h-[75dvh] flex-col gap-0 p-0">
              <DialogHeader className="p-4">
                <DialogTitle>Datasets</DialogTitle>
                <DialogDescription>Choose a dataset or add data.</DialogDescription>
              </DialogHeader>
              <div className="min-h-0 flex-1">{sidebar}</div>
            </DialogContent>
          </Dialog>
        </div>
      ) : (
        <ResizablePanelGroup
          defaultLayout={layout.defaultLayout}
          onLayoutChanged={layout.onLayoutChanged}
        >
          <ResizablePanel id="datasets" defaultSize="16" minSize="10">
            {sidebar}
          </ResizablePanel>
          {selected ? (
            panels
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
                        <EmptyTitle>Add your first dataset</EmptyTitle>
                        <EmptyDescription>
                          A CSV, TSV, JSON, JSONL or Parquet file, from this computer, S3 or the
                          web. Then ask questions about each of its rows.
                        </EmptyDescription>
                      </EmptyHeader>
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
                    </Empty>
                  ) : (
                    <Empty className="flex-1">
                      <EmptyHeader>
                        <EmptyMedia variant="icon">
                          <DatabaseIcon />
                        </EmptyMedia>
                        <EmptyTitle>
                          {selectedId ? "Dataset not found" : "Pick a dataset"}
                        </EmptyTitle>
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
      )}

      <CommandDialog open={palette} onOpenChange={setPalette}>
        <Command>
          <CommandInput placeholder="Type a command or a dataset name" />
          <CommandList>
            <CommandEmpty>Nothing found.</CommandEmpty>
            <CommandGroup heading="Actions">
              {selected && (
                <>
                  <CommandItem onSelect={() => command(() => taskActionsRef.current?.review())}>
                    <ScanTextIcon />
                    Review rows<CommandShortcut>R</CommandShortcut>
                  </CommandItem>
                  <CommandItem onSelect={() => command(() => taskActionsRef.current?.configure())}>
                    <PenLineIcon />
                    Configure run
                  </CommandItem>
                  <CommandItem onSelect={() => command(() => setRenaming(selected))}>
                    <PencilIcon />
                    Rename dataset…
                  </CommandItem>
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
                    <CommandItem onSelect={() => command(() => openExport(selected))}>
                      <DownloadIcon />
                      Export dataset…
                      <CommandShortcut>E</CommandShortcut>
                    </CommandItem>
                  )}
                </>
              )}
              <CommandItem onSelect={() => command(() => setAdding("choose"))}>
                <PlusIcon />
                Add data
              </CommandItem>
              <CommandItem
                value="settings providers openrouter key storage s3 connections"
                onSelect={() => command(() => openSettings("providers"))}
              >
                <SettingsIcon />
                Settings
                <CommandShortcut>⌘,</CommandShortcut>
              </CommandItem>
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
          sql={exportSql}
          open
          onOpenChange={(open) => !open && setExporting(undefined)}
        />
      )}
      {renaming && (
        <RenameDataset
          key={renaming.id}
          dataset={renaming}
          onClose={() => setRenaming(undefined)}
          onSaved={load}
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

/** Whether a key press is going into a text field, where single-key shortcuts must not fire. */
function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

function subscribeWidth(callback: () => void) {
  const query = window.matchMedia("(max-width: 900px)");
  query.addEventListener("change", callback);
  return () => query.removeEventListener("change", callback);
}
function narrowWidth() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function RenameDataset({
  dataset,
  onClose,
  onSaved,
}: {
  dataset: Dataset;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(dataset.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  async function save() {
    setBusy(true);
    setError(undefined);
    try {
      const { error } = await api.PATCH("/v1/datasets/{dataset_id}", {
        params: { path: { dataset_id: dataset.id } },
        body: { name: name.trim() },
      });
      if (error) setError(errorMessage(error));
      else {
        onSaved();
        onClose();
      }
    } catch {
      setError("Could not save the name. Check the connection and try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename dataset</DialogTitle>
          <DialogDescription>
            Give this dataset a name that describes its purpose. Its rows and lineage stay the same.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <Field>
            <FieldLabel htmlFor="dataset-name">Name</FieldLabel>
            <Input
              id="dataset-name"
              autoFocus
              maxLength={120}
              value={name}
              disabled={busy}
              onChange={(e) => setName(e.target.value)}
            />
            {error && <FieldError>{error}</FieldError>}
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={busy || !name.trim()}>
              {busy && <Spinner />}Save name
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
