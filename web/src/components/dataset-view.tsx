"use client";

import {
  DownloadIcon,
  EllipsisIcon,
  PlayIcon,
  RotateCcwIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { withFittingModels, withPreset } from "@/components/answer-settings";
import { ColumnProfiles } from "@/components/column-profiles";
import { DatasetExplorer } from "@/components/dataset-explorer";
import { JobEditor } from "@/components/job-editor";
import { Lineage } from "@/components/lineage";
import { PaneHeader } from "@/components/pane";
import { TooltipButton } from "@/components/tooltip-button";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ResizableHandle, ResizablePanel } from "@/components/ui/resizable";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api,
  type Dataset,
  type Estimate,
  type Job,
  type Preset,
  type Scope,
  type Task,
} from "@/lib/api/client";
import { useModels, useTaskTypes } from "@/lib/catalog";
import { errorMessage, formatBytes, formatNumber, formatUsd } from "@/lib/format";
import { isActive } from "@/lib/runs";
import { useJob } from "@/lib/use-job";

export const TABS = ["rows", "columns", "lineage"] as const;
export type Tab = (typeof TABS)[number];

/** What the command palette and shortcuts can do with the selected dataset's job. */
export type JobActions = {
  run: () => void;
  /** Adds an empty task, or one started from a write preset. */
  addTask: (preset?: Preset) => void;
  clearTasks: () => void;
};

/**
 * The middle and right columns for the selected dataset.
 *
 * The middle shows its rows, which are also the rows a run works on (its scope: search, filters, sort
 * and limit), and its lineage. The right side holds the tasks to run. A run makes a new dataset, which
 * opens straight away and fills in as the run goes.
 */
export function DatasetPanels({
  dataset,
  datasets,
  tab,
  onTabChange,
  onExport,
  onDelete,
  onChanged,
  onOpenDataset,
  actionsRef,
}: {
  dataset: Dataset;
  datasets: Dataset[];
  tab: Tab;
  onTabChange: (tab: Tab) => void;
  onExport: () => void;
  onDelete: () => void;
  onChanged: () => void;
  onOpenDataset: (datasetId: string) => void;
  actionsRef: React.RefObject<JobActions | null>;
}) {
  const { job, update, flush } = useJob(dataset.id);
  const updateScope = useCallback(
    (changes: Partial<Scope>) => update((job) => ({ scope: { ...job.scope, ...changes } })),
    [update],
  );
  const run = dataset.run;
  // A dataset still being made can't be run on yet: its answers aren't all in.
  const making = !!run && isActive(run);

  async function changeRun(action: "stop" | "resume") {
    if (!run) return;
    const path = { params: { path: { run_id: run.id } } };
    const { error } =
      action === "stop"
        ? await api.POST("/v1/runs/{run_id}/stop", path)
        : await api.POST("/v1/runs/{run_id}/resume", path);
    if (error) toast.error(errorMessage(error));
    onChanged();
  }

  const [starting, setStarting] = useState(false);
  const [runError, setRunError] = useState<string>();
  // The task that was just added opens, so you can write it straight away.
  const [opened, setOpened] = useState<string>();

  const startRun = useCallback(async () => {
    if (!job || starting || making) return;
    setStarting(true);
    setRunError(undefined);
    await flush();
    const { data, error } = await api.POST("/v1/datasets/{dataset_id}/runs", {
      params: { path: { dataset_id: dataset.id } },
      body: { scope: job.scope, tasks: job.tasks },
    });
    setStarting(false);
    if (error) {
      setRunError(errorMessage(error));
      return;
    }
    onChanged();
    onOpenDataset(data.dataset_id);
  }, [job, dataset.id, starting, making, flush, onChanged, onOpenDataset]);

  const types = useTaskTypes();
  const models = useModels();
  const addTask = useCallback(
    (from?: Task) => {
      if (!job) return;
      const task: Task = from ? { ...from, id: newId() } : emptyTask(job.tasks);
      update((job) => ({ tasks: [...job.tasks, task] }));
      setOpened(task.id);
    },
    [job, update],
  );
  const addPresetTask = useCallback(
    (preset: Preset) => {
      if (!job || !types) return;
      const task = withPreset(emptyTask(job.tasks), preset);
      addTask(withFittingModels(task, types, models).task);
    },
    [job, types, models, addTask],
  );
  const estimate = useEstimate(dataset.id, job);

  // Starts over with one empty task, on the rows you have picked.
  const clearTasks = useCallback(() => {
    update((job) => ({ tasks: [{ ...emptyTask(job.tasks), column: "answer" }] }));
  }, [update]);

  useEffect(() => {
    actionsRef.current = {
      run: startRun,
      addTask: (preset) => (preset ? addPresetTask(preset) : addTask()),
      clearTasks,
    };
    return () => {
      actionsRef.current = null;
    };
  }, [actionsRef, startRun, addTask, addPresetTask, clearTasks]);

  return (
    <>
      <ResizableHandle />
      <ResizablePanel id="rows" defaultSize="50" minSize="30">
        <Tabs
          value={tab}
          onValueChange={(value) => onTabChange(value as Tab)}
          className="flex h-full flex-col gap-0"
        >
          <PaneHeader>
            <span className="truncate font-medium" title={dataset.source}>
              {dataset.name}
            </span>
            <span className="truncate text-xs text-muted-foreground">
              {formatNumber(dataset.row_count)} rows · {formatBytes(dataset.size_bytes)}
            </span>
            <div className="ml-auto flex items-center gap-1">
              {run && (run.status === "queued" || run.status === "running") && (
                <Button size="sm" variant="ghost" onClick={() => changeRun("stop")}>
                  <SquareIcon data-icon="inline-start" />
                  Stop
                </Button>
              )}
              {run && (run.status === "stopped" || run.status === "failed") && (
                <Button size="sm" variant="ghost" onClick={() => changeRun("resume")}>
                  <PlayIcon data-icon="inline-start" />
                  Resume
                </Button>
              )}
              {run && run.status === "done" && run.failed > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  title="Ask the failed answers again"
                  onClick={() => changeRun("resume")}
                >
                  <RotateCcwIcon data-icon="inline-start" />
                  Retry {formatNumber(run.failed)} failed
                </Button>
              )}
              <TabsList>
                <TabsTrigger value="rows">Rows</TabsTrigger>
                <TabsTrigger value="columns">Columns</TabsTrigger>
                <TabsTrigger value="lineage">Lineage</TabsTrigger>
              </TabsList>
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={<Button variant="ghost" size="icon-sm" aria-label="Dataset actions" />}
                >
                  <EllipsisIcon />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem disabled={making} onClick={onExport}>
                    <DownloadIcon />
                    Export…
                    <DropdownMenuShortcut>E</DropdownMenuShortcut>
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" onClick={onDelete}>
                    <Trash2Icon />
                    Delete dataset
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </PaneHeader>
          <TabsContent value="rows" keepMounted className="min-h-0 flex-1">
            {job ? (
              <DatasetExplorer
                dataset={dataset}
                scope={job.scope}
                onScopeChange={updateScope}
                version={run?.done}
              />
            ) : (
              <Spinner className="m-3" />
            )}
          </TabsContent>
          <TabsContent value="columns" className="min-h-0 flex-1 overflow-auto p-3">
            <ColumnProfiles datasetId={dataset.id} />
          </TabsContent>
          <TabsContent value="lineage" className="min-h-0 flex-1 overflow-auto">
            <Lineage dataset={dataset} datasets={datasets} onOpenDataset={onOpenDataset} />
          </TabsContent>
        </Tabs>
      </ResizablePanel>
      <ResizableHandle />
      <ResizablePanel id="job" defaultSize="34" minSize="20">
        <div className="flex h-full flex-col">
          <PaneHeader>
            <span className="font-medium">New run</span>
            <TooltipButton
              label={
                making
                  ? "This dataset is still being made"
                  : (estimate?.problem ??
                    (estimate
                      ? `About ${formatUsd(estimate.cost)} for ${formatNumber(estimate.rows)} rows, making a new dataset`
                      : "Run every task on the rows in the table, making a new dataset"))
              }
              keys={["⌘", "↵"]}
              size="sm"
              className="ml-auto"
              disabled={!job || starting || making}
              onClick={startRun}
            >
              {starting ? (
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
                problem={estimate?.problem ?? undefined}
              />
            ) : (
              <Spinner className="m-3" />
            )}
          </div>
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
    fields: [],
    reason: false,
    models: existing.at(-1)?.models ?? ["typesafe/jev-1.14"],
  };
}

/** What running the job would take and cost, or why it can't run: fetched again as it changes. */
function useEstimate(datasetId: string, job: Job | undefined): Estimate | undefined {
  const [estimate, setEstimate] = useState<{ key: string; estimate: Estimate }>();
  const key = job ? JSON.stringify([job.scope, job.tasks]) : "";
  useEffect(() => {
    if (!job) return;
    let current = true;
    const timer = setTimeout(() => {
      api
        .POST("/v1/datasets/{dataset_id}/estimate", {
          params: { path: { dataset_id: datasetId } },
          body: { scope: job.scope, tasks: job.tasks },
        })
        .then(({ data }) => {
          if (current && data) setEstimate({ key, estimate: data });
        });
    }, 500);
    return () => {
      current = false;
      clearTimeout(timer);
    };
    // The key stands for the job's scope and tasks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, key]);
  return estimate?.estimate;
}

function newId(): string {
  return crypto.randomUUID().replaceAll("-", "").slice(0, 8);
}
