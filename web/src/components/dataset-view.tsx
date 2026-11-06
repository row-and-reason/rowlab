"use client";

import { EllipsisIcon, PencilIcon, PlayIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ColumnProfiles } from "@/components/column-profiles";
import { DatasetExplorer, type RunRows } from "@/components/dataset-explorer";
import { JobEditor } from "@/components/job-editor";
import { PaneHeader } from "@/components/pane";
import { RunDetails, RunsList } from "@/components/runs";
import { TooltipButton } from "@/components/tooltip-button";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ResizableHandle, ResizablePanel } from "@/components/ui/resizable";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api,
  type Dataset,
  type Run,
  type RunSummary,
  type Scope,
  type Task,
} from "@/lib/api/client";
import { errorMessage, formatBytes, formatNumber } from "@/lib/format";
import { useJob } from "@/lib/use-job";

export const TABS = ["rows", "columns", "runs"] as const;
export type Tab = (typeof TABS)[number];

/** What the command palette and shortcuts can do with the selected dataset's job. */
export type JobActions = {
  run: () => void;
  addTask: () => void;
  newRun: () => void;
};

/**
 * The middle and right columns for the selected dataset.
 *
 * Composing a new run, the middle shows the rows it will run on (its scope: search, filters, sort and
 * limit) and the right side its tasks. Viewing a past run (`?run=<id>`), the middle shows that run's
 * rows with its answers, read-only, and the right side its settings and costs.
 */
export function DatasetPanels({
  dataset,
  tab,
  runId,
  onOpen,
  onDelete,
  onRunStarted,
  actionsRef,
}: {
  dataset: Dataset;
  tab: Tab;
  runId: string | null;
  onOpen: (tab: Tab, runId: string | null) => void;
  onDelete: () => void;
  onRunStarted: () => void;
  actionsRef: React.RefObject<JobActions | null>;
}) {
  const { job, update, flush } = useJob(dataset.id);
  const updateScope = useCallback(
    (changes: Partial<Scope>) => update((job) => ({ scope: { ...job.scope, ...changes } })),
    [update],
  );

  const [runs, setRuns] = useState<RunSummary[]>();
  const loadRuns = useCallback(async () => {
    const { data } = await api.GET("/v1/datasets/{dataset_id}/runs", {
      params: { path: { dataset_id: dataset.id } },
    });
    if (data) setRuns(data);
  }, [dataset.id]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    loadRuns();
  }, [loadRuns]);

  // The run being viewed, fetched with its answers, and again every second while it is running.
  const [viewed, setViewed] = useState<Run>();
  const viewedRunning = viewed?.id === runId && viewed?.status === "running";
  useEffect(() => {
    if (!runId || (viewed?.id === runId && !viewedRunning)) return;
    let current = true;
    const fetchRun = () =>
      api
        .GET("/v1/runs/{run_id}", { params: { path: { run_id: runId } } })
        .then(({ data, error }) => {
          if (!current) return;
          if (error) toast.error(errorMessage(error));
          else setViewed(data);
        });
    const timer = viewedRunning ? setInterval(fetchRun, 1000) : undefined;
    if (!viewedRunning) fetchRun();
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [runId, viewed?.id, viewedRunning]);

  // A run that finishes changes the list's statuses and costs.
  const viewedStatus = viewed?.status;
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- refetch when a run finishes
    if (viewedStatus && viewedStatus !== "running") loadRuns();
  }, [viewedStatus, loadRuns]);
  const run = runId && viewed?.id === runId ? viewed : undefined;
  const runRows = useMemo<RunRows | undefined>(
    () => run && { columns: run.columns, rows: new Map(run.rows.map((r) => [r.row_id, r])) },
    [run],
  );

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string>();
  // The task that was just added opens, so you can write it straight away.
  const [opened, setOpened] = useState<string>();

  const startRun = useCallback(async () => {
    if (!job || running || runId) return;
    setRunning(true);
    setRunError(undefined);
    await flush();
    const { data, error } = await api.POST("/v1/jobs/{job_id}/runs", {
      params: { path: { job_id: job.id } },
    });
    setRunning(false);
    if (error) {
      setRunError(errorMessage(error));
      return;
    }
    setViewed(data);
    loadRuns();
    onRunStarted();
    onOpen("rows", data.id);
  }, [job, running, runId, flush, loadRuns, onRunStarted, onOpen]);

  const addTask = useCallback(
    (from?: Task) => {
      if (!job) return;
      const task: Task = from ? { ...from, id: newId() } : emptyTask(job.tasks);
      update((job) => ({ tasks: [...job.tasks, task] }));
      setOpened(task.id);
    },
    [job, update],
  );

  // A new run starts with one empty task, on the rows you have picked.
  const newRun = useCallback(() => {
    update((job) => ({ tasks: [{ ...emptyTask(job.tasks), column: "answer" }] }));
    onOpen("rows", null);
  }, [update, onOpen]);

  // Starts from the run being viewed: its rows and its tasks.
  const editAsNewRun = useCallback(() => {
    if (run) update({ scope: run.config.scope, tasks: run.config.tasks });
    onOpen("rows", null);
  }, [run, update, onOpen]);

  useEffect(() => {
    actionsRef.current = { run: startRun, addTask: () => addTask(), newRun };
    return () => {
      actionsRef.current = null;
    };
  }, [actionsRef, startRun, addTask, newRun]);

  return (
    <>
      <ResizableHandle />
      <ResizablePanel id="rows" defaultSize="50" minSize="30">
        <Tabs
          value={tab}
          onValueChange={(value) => onOpen(value as Tab, runId)}
          className="flex h-full flex-col gap-0"
        >
          <PaneHeader>
            <span className="truncate font-medium" title={dataset.source}>
              {dataset.name}
            </span>
            <span className="truncate text-xs text-muted-foreground">
              {formatNumber(dataset.row_count)} rows · {formatBytes(dataset.size_bytes)}
            </span>
            <TabsList className="ml-auto">
              <TabsTrigger value="rows">Rows</TabsTrigger>
              <TabsTrigger value="columns">Columns</TabsTrigger>
              <TabsTrigger value="runs">Runs</TabsTrigger>
            </TabsList>
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<Button variant="ghost" size="icon-sm" aria-label="Dataset actions" />}
              >
                <EllipsisIcon />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem variant="destructive" onClick={onDelete}>
                  <Trash2Icon />
                  Delete dataset
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </PaneHeader>
          {job && (!runId || run) ? (
            <>
              <TabsContent value="rows" keepMounted className="min-h-0 flex-1">
                {run ? (
                  <DatasetExplorer
                    key={run.id}
                    dataset={dataset}
                    scope={run.config.scope}
                    onScopeChange={() => {}}
                    results={runRows}
                    viewing={{ label: `Run #${run.number}`, onClose: () => onOpen(tab, null) }}
                  />
                ) : (
                  <DatasetExplorer
                    key="new"
                    dataset={dataset}
                    scope={job.scope}
                    onScopeChange={updateScope}
                  />
                )}
              </TabsContent>
              <TabsContent value="columns" className="min-h-0 flex-1 overflow-auto p-3">
                <ColumnProfiles datasetId={dataset.id} />
              </TabsContent>
              <TabsContent value="runs" className="min-h-0 flex-1">
                {runs ? (
                  <RunsList
                    runs={runs}
                    selectedId={runId}
                    onOpen={(r) => onOpen("rows", r.id)}
                    onNew={newRun}
                  />
                ) : (
                  <Spinner className="m-3" />
                )}
              </TabsContent>
            </>
          ) : (
            <Spinner className="m-3" />
          )}
        </Tabs>
      </ResizablePanel>
      <ResizableHandle />
      <ResizablePanel id="job" defaultSize="34" minSize="20">
        <div className="flex h-full flex-col">
          {runId ? (
            <>
              <PaneHeader>
                <span className="font-medium">{run ? `Run #${run.number}` : "Run"}</span>
                <Button size="sm" variant="ghost" className="ml-auto" onClick={editAsNewRun}>
                  <PencilIcon data-icon="inline-start" />
                  Edit as new run
                </Button>
              </PaneHeader>
              <div className="min-h-0 flex-1 overflow-auto">
                {run ? <RunDetails run={run} /> : <Spinner className="m-3" />}
              </div>
            </>
          ) : (
            <>
              <PaneHeader>
                <span className="font-medium">New run</span>
                <TooltipButton
                  label="Run every task on the rows in the table"
                  keys={["⌘", "↵"]}
                  size="sm"
                  className="ml-auto"
                  disabled={!job || running}
                  onClick={startRun}
                >
                  {running ? (
                    <Spinner data-icon="inline-start" />
                  ) : (
                    <PlayIcon data-icon="inline-start" />
                  )}
                  Run
                </TooltipButton>
              </PaneHeader>
              <div className="@container min-h-0 flex-1 overflow-auto">
                {job ? (
                  <JobEditor
                    dataset={dataset}
                    job={job}
                    opened={opened}
                    onTasksChange={(tasks) => update({ tasks })}
                    onAddTask={addTask}
                    runError={runError}
                  />
                ) : (
                  <Spinner className="m-3" />
                )}
              </div>
            </>
          )}
        </div>
      </ResizablePanel>
    </>
  );
}

function emptyTask(existing: Task[]): Task {
  return {
    id: newId(),
    template: "",
    type: "yes_no",
    column: `answer_${existing.length + 1}`,
    options: [],
    models: existing.at(-1)?.models ?? ["typesafe/jev-1.14"],
  };
}

function newId(): string {
  return crypto.randomUUID().replaceAll("-", "").slice(0, 8);
}
