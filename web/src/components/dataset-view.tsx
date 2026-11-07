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
import { CompareView } from "@/components/compare-view";
import { DatasetExplorer } from "@/components/dataset-explorer";
import { TaskEditor } from "@/components/task-editor";
import { Lineage } from "@/components/lineage";
import { useCan } from "@/components/me";
import { PaneHeader } from "@/components/pane";
import { TooltipButton } from "@/components/tooltip-button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { api, type Dataset, type Estimate, type Preset, type Task } from "@/lib/api/client";
import type { ComparisonActions } from "@/lib/use-comparison";
import { useModels, useTaskTypes } from "@/lib/catalog";
import { errorMessage, formatBytes, formatNumber, formatUsd } from "@/lib/format";
import { useDraft } from "@/lib/draft";
import { isActive } from "@/lib/runs";
import { type View, viewSql, type WhereFilter } from "@/lib/sql";

export const TABS = ["rows", "columns", "compare", "lineage"] as const;
export type Tab = (typeof TABS)[number];

/** What the command palette and shortcuts can do with the selected dataset's next run. */
export type TaskActions = {
  run: () => void;
  /** Adds an empty task, or one started from a write preset. */
  addTask: (preset?: Preset) => void;
  clearTasks: () => void;
};

/**
 * The middle and right columns for the selected dataset.
 *
 * The middle shows its rows, which are also the rows the next run asks about (the view: search,
 * filters, sort and limit, or SQL), and its lineage. The right side holds the tasks to run. Both are
 * the dataset's draft, kept in this browser. A run makes a new dataset, which opens straight away and
 * fills in as the run goes.
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
  comparisonActionsRef,
  needsKey,
}: {
  dataset: Dataset;
  datasets: Dataset[];
  tab: Tab;
  onTabChange: (tab: Tab) => void;
  onExport: () => void;
  onDelete: () => void;
  onChanged: () => void;
  onOpenDataset: (datasetId: string) => void;
  actionsRef: React.RefObject<TaskActions | null>;
  comparisonActionsRef: React.RefObject<ComparisonActions | null>;
  needsKey: boolean;
}) {
  const { draft, update, isNew } = useDraft(dataset.id, () => ({
    // A first run on a few rows, so it's cheap.
    view: { search: "", filters: [], sort: [], limit: 20, sql: null },
    tasks: [{ ...emptyTask([]), column: "answer" }],
  }));
  const updateView = useCallback(
    (changes: Partial<View>) => update((draft) => ({ view: { ...draft.view, ...changes } })),
    [update],
  );
  const sql = viewSql(draft.view, dataset.columns);
  const run = dataset.run;

  // A new draft on a dataset a run made starts on the rows that run answered.
  useEffect(() => {
    if (!isNew || !run) return;
    api.GET("/v1/runs/{run_id}", { params: { path: { run_id: run.id } } }).then(({ data }) => {
      const answer = data?.columns[0];
      if (answer) {
        updateView({ filters: [{ column: answer, op: "is_not_null", value: null }], limit: null });
      }
    });
    // Only when the draft is first made.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [comparedColumns, setComparedColumns] = useState<string[]>([]);
  // Compare counts the whole dataset, so drill-through replaces any unrelated search/filter/limit.
  function showRows(filters: WhereFilter[], columns: string[]) {
    setComparedColumns(columns);
    update({ view: { search: "", filters, sort: [], limit: null, sql: null } });
    onTabChange("rows");
  }
  // A dataset still being made can't be run on yet: its answers aren't all in.
  const making = !!run && isActive(run);
  // Verifiers read; running, exporting and deleting need a member.
  const canEdit = useCan("member");

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
    if (!canEdit || starting || making) return;
    setStarting(true);
    setRunError(undefined);
    const { data, error } = await api.POST("/v1/datasets/{dataset_id}/runs", {
      params: { path: { dataset_id: dataset.id } },
      body: { sql, tasks: draft.tasks },
    });
    setStarting(false);
    if (error) {
      setRunError(errorMessage(error));
      return;
    }
    onChanged();
    onOpenDataset(data.dataset_id);
  }, [canEdit, sql, draft.tasks, dataset.id, starting, making, onChanged, onOpenDataset]);

  const types = useTaskTypes();
  const models = useModels();
  const addTask = useCallback(
    (from?: Task) => {
      const task: Task = from ? { ...from, id: newId() } : emptyTask(draft.tasks);
      update((draft) => ({ tasks: [...draft.tasks, task] }));
      setOpened(task.id);
    },
    [draft.tasks, update],
  );
  const addPresetTask = useCallback(
    (preset: Preset) => {
      if (!types) return;
      const task = withPreset(emptyTask(draft.tasks), preset);
      addTask(withFittingModels(task, types, models).task);
    },
    [draft.tasks, types, models, addTask],
  );
  const { estimate, problem } = useEstimate(dataset.id, sql, draft.tasks, canEdit);

  // Starts over with one empty task, on the rows you have picked.
  const clearTasks = useCallback(() => {
    update((draft) => ({ tasks: [{ ...emptyTask(draft.tasks), column: "answer" }] }));
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
      <ResizablePanel id="rows" defaultSize="54" minSize="30">
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
              {canEdit && run && (run.status === "queued" || run.status === "running") && (
                <Button size="sm" variant="ghost" onClick={() => changeRun("stop")}>
                  <SquareIcon data-icon="inline-start" />
                  Stop
                </Button>
              )}
              {canEdit && run && (run.status === "stopped" || run.status === "failed") && (
                <Button size="sm" variant="ghost" onClick={() => changeRun("resume")}>
                  <PlayIcon data-icon="inline-start" />
                  Resume
                </Button>
              )}
              {canEdit && run && run.status === "done" && run.failed > 0 && (
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
                <TabsTrigger className="dark:data-active:bg-popover" value="rows">
                  Rows
                </TabsTrigger>
                <TabsTrigger className="dark:data-active:bg-popover" value="columns">
                  Columns
                </TabsTrigger>
                <TabsTrigger className="dark:data-active:bg-popover" value="compare">
                  Compare
                </TabsTrigger>
                <TabsTrigger className="dark:data-active:bg-popover" value="lineage">
                  Lineage
                </TabsTrigger>
              </TabsList>
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={<Button variant="ghost" size="icon-sm" aria-label="Dataset actions" />}
                >
                  <EllipsisIcon />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem disabled={!canEdit || making} onClick={onExport}>
                    <DownloadIcon />
                    Export…
                    <DropdownMenuShortcut>E</DropdownMenuShortcut>
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" disabled={!canEdit} onClick={onDelete}>
                    <Trash2Icon />
                    Delete dataset
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </PaneHeader>
          {run?.status === "failed" && run.error && (
            <Alert variant="destructive" className="m-3 mb-0 w-auto">
              <AlertTitle>The run stopped</AlertTitle>
              <AlertDescription>{run.error}</AlertDescription>
            </Alert>
          )}
          <TabsContent value="rows" keepMounted className="min-h-0 flex-1">
            <DatasetExplorer
              dataset={dataset}
              view={draft.view}
              sql={sql}
              onViewChange={updateView}
              version={run?.done}
              priorityColumns={comparedColumns}
            />
          </TabsContent>
          <TabsContent value="columns" className="min-h-0 flex-1 overflow-auto p-3">
            <ColumnProfiles datasetId={dataset.id} />
          </TabsContent>
          {/* Kept mounted, so the columns picked stay picked while looking at their rows. */}
          <TabsContent value="compare" keepMounted className="min-h-0 flex-1 overflow-hidden">
            <CompareView dataset={dataset} onFilter={showRows} actionsRef={comparisonActionsRef} />
          </TabsContent>
          <TabsContent value="lineage" className="min-h-0 flex-1 overflow-auto">
            <Lineage dataset={dataset} datasets={datasets} onOpenDataset={onOpenDataset} />
          </TabsContent>
        </Tabs>
      </ResizablePanel>
      <ResizableHandle />
      <ResizablePanel id="job" defaultSize="30" minSize="20">
        <div className="flex h-full flex-col bg-card">
          <PaneHeader>
            <span className="font-medium">New run</span>
            <TooltipButton
              label={
                !canEdit
                  ? "Running tasks needs the member role"
                  : making
                    ? "This dataset is still being made"
                    : (problem ??
                      (estimate
                        ? `About ${formatUsd(estimate.cost)} for ${formatNumber(estimate.rows)} rows, making a new dataset`
                        : "Run every task on the rows in the table, making a new dataset"))
              }
              keys={["⌘", "↵"]}
              size="sm"
              className="ml-auto text-xs"
              disabled={!canEdit || starting || making}
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
            <TaskEditor
              dataset={dataset}
              tasks={draft.tasks}
              sql={sql}
              opened={opened}
              onTasksChange={(tasks) => update({ tasks })}
              onAddTask={addTask}
              runError={runError}
              problem={problem}
              needsKey={needsKey}
            />
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
    preset: null,
    extraction_mode: "structure",
    column: `answer_${existing.length + 1}`,
    options: [],
    fields: [],
    reason: false,
    models: existing.at(-1)?.models ?? ["typesafe/jev-1.14"],
  };
}

/** What running the draft would take and cost, or why it can't run: fetched again as it changes. */
function useEstimate(
  datasetId: string,
  sql: string,
  tasks: Task[],
  enabled: boolean,
): { estimate?: Estimate; problem?: string } {
  // What the API says the run would cost, and why it can't start, if it can't: its own answer, or
  // the request's error (e.g. OpenRouter can't be reached).
  const [estimate, setEstimate] = useState<{ key: string; estimate?: Estimate; problem?: string }>();
  const key = JSON.stringify([sql, tasks]);
  useEffect(() => {
    if (!enabled) return;
    let current = true;
    const timer = setTimeout(() => {
      api
        .POST("/v1/datasets/{dataset_id}/estimate", {
          params: { path: { dataset_id: datasetId } },
          body: { sql, tasks },
        })
        .then(({ data, error }) => {
          if (!current) return;
          if (data) setEstimate({ key, estimate: data, problem: data.problem ?? undefined });
          else setEstimate({ key, problem: errorMessage(error) });
        });
    }, 500);
    return () => {
      current = false;
      clearTimeout(timer);
    };
    // The key stands for the query and tasks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, key, enabled]);
  return { estimate: estimate?.estimate, problem: estimate?.problem };
}

function newId(): string {
  return crypto.randomUUID().replaceAll("-", "").slice(0, 8);
}
