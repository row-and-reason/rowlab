"use client";

import { DownloadIcon, EllipsisIcon, PlayIcon, Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ColumnProfiles } from "@/components/column-profiles";
import { CompareView } from "@/components/compare-view";
import { DatasetExplorer } from "@/components/dataset-explorer";
import { DeleteAnswers } from "@/components/delete-answers";
import { LabelPane } from "@/components/label-pane";
import { RunsView } from "@/components/runs-view";
import { TaskEditor } from "@/components/task-editor";
import { useCan } from "@/components/me";
import { PaneHeader } from "@/components/pane";
import { TooltipButton } from "@/components/tooltip-button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ResizableHandle, ResizablePanel } from "@/components/ui/resizable";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api,
  type AnswerColumn,
  type Dataset,
  type Estimate,
  type Preset,
  type Run,
  type Task,
} from "@/lib/api/client";
import type { ComparisonActions } from "@/lib/use-comparison";
import { useModels, useTaskTypes } from "@/lib/catalog";
import { errorMessage, formatBytes, formatNumber, formatUsd } from "@/lib/format";
import { useDraft } from "@/lib/draft";
import { useEstimate } from "@/lib/use-estimate";
import { isActive } from "@/lib/runs";
import { ALL_ROWS, type View, viewSql, type WhereFilter } from "@/lib/sql";
import { emptyTask, newId, withFittingModels, withPreset } from "@/lib/tasks";

export const TABS = ["rows", "columns", "compare", "runs"] as const;
export type Tab = (typeof TABS)[number];

/** What the command palette and shortcuts can do with the selected dataset. */
export type TaskActions = {
  run: () => void;
  /** Switch to labelling rows by hand. */
  label: () => void;
  /** Adds an empty task, or one started from a write preset. */
  addTask: (preset?: Preset) => void;
  clearTasks: () => void;
};

/**
 * The middle and right columns for the selected dataset.
 *
 * The middle shows its rows, which are also the rows the next run asks about, or that are labelled
 * by hand (the view: search, filters, sort and limit, or SQL), and its runs. The right side holds the
 * tasks to run, or the labelling. Both are the dataset's draft, kept in this browser. A run adds its
 * answers to this dataset as columns, which fill in as it goes.
 */
export function DatasetPanels({
  dataset,
  runs,
  tab,
  onTabChange,
  onExport,
  onRename,
  onDelete,
  onChanged,
  actionsRef,
  comparisonActionsRef,
  needsProvider,
}: {
  dataset: Dataset;
  runs: Run[];
  tab: Tab;
  onTabChange: (tab: Tab) => void;
  onExport: () => void;
  onRename: () => void;
  onDelete: () => void;
  onChanged: () => void;
  actionsRef: React.RefObject<TaskActions | null>;
  comparisonActionsRef: React.RefObject<ComparisonActions | null>;
  needsProvider: boolean;
}) {
  const { draft, update } = useDraft(dataset.id, () => ({
    // A first run on a few rows, so it's cheap.
    view: {
      search: "",
      filters: [],
      sort: [],
      limit: dataset.answers.length ? null : 20,
      sql: null,
    },
    tasks: [{ ...emptyTask([]), column: "answer" }],
  }));
  const updateView = useCallback(
    (changes: Partial<View>) => update((draft) => ({ view: { ...draft.view, ...changes } })),
    [update],
  );
  const sql = viewSql(draft.view, dataset.columns);
  const mode = draft.mode ?? "ask";
  const labelColumns = dataset.answers.filter((a) => a.model === null);
  // The label column being labelled: one the dataset has, or a new one, set up in the draft.
  const [fallbackLabel] = useState(() => newLabelTask(dataset));
  const label = draft.label ?? labelColumns[0]?.task ?? fallbackLabel;
  const existingLabels = labelColumns.find((a) => a.name === label.column);
  const labelTask = existingLabels?.task ?? label;

  const [labelPosition, setLabelPosition] = useState(0);
  const [labelQuery, setLabelQuery] = useState(sql);
  if (labelQuery !== sql) {
    setLabelQuery(sql);
    setLabelPosition(0);
  }
  // Changes whenever answers do: a run writing a chunk of them, or a label saved or changed. Not a
  // run's progress, which changes every second while its answers reach the dataset only a chunk at a
  // time: the rows and comparison would be fetched and redrawn each second for nothing.
  const [saved, setSaved] = useState(0);
  const version = dataset.answers.reduce((n, a) => n + a.answered, 0) + saved;
  const labelChanged = () => {
    setSaved((n) => n + 1);
    onChanged();
  };
  const [selectedCount, setSelectedCount] = useState(dataset.row_count);

  const [comparedColumns, setComparedColumns] = useState<string[]>([]);
  // Compare counts the whole dataset, so drill-through replaces any unrelated search/filter/limit.
  function showRows(filters: WhereFilter[], columns: string[]) {
    setComparedColumns(columns);
    update({ view: { search: "", filters, sort: [], limit: null, sql: null } });
    onTabChange("rows");
  }
  // Verifiers read; running, labelling, exporting and deleting need a member.
  const canEdit = useCan("member");
  const [deletingAnswers, setDeletingAnswers] = useState<AnswerColumn>();
  const active = runs.filter(isActive);
  const latest = runs[0];

  const [starting, setStarting] = useState(false);
  const [runError, setRunError] = useState<string>();
  // The task that was just added opens, so you can write it straight away.
  const [opened, setOpened] = useState<string>();

  const startRun = useCallback(async () => {
    if (!canEdit || starting) return;
    setStarting(true);
    setRunError(undefined);
    const { error } = await api.POST("/v1/datasets/{dataset_id}/runs", {
      params: { path: { dataset_id: dataset.id } },
      body: { sql, tasks: draft.tasks },
    });
    setStarting(false);
    if (error) {
      setRunError(errorMessage(error));
      return;
    }
    toast.success("Run started: its answers fill in as columns");
    onChanged();
  }, [canEdit, sql, draft.tasks, dataset.id, starting, onChanged]);

  const types = useTaskTypes();
  const models = useModels();
  const addTask = useCallback(
    (from?: Task) => {
      const task: Task = from ? { ...from, id: newId() } : emptyTask(draft.tasks);
      update((draft) => ({ mode: "ask", tasks: [...draft.tasks, task] }));
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
  const { estimate, problem } = useEstimate(dataset.id, sql, draft.tasks, canEdit && mode === "ask");

  // Starts over with one empty task, on the rows you have picked.
  const clearTasks = useCallback(() => {
    update((draft) => ({ mode: "ask", tasks: [{ ...emptyTask(draft.tasks), column: "answer" }] }));
  }, [update]);

  // A run's tasks and rows in the task editor, to change and start.
  function editRun(run: Run) {
    update({
      mode: "ask",
      tasks: run.config.tasks,
      view: {
        search: "",
        filters: [],
        sort: [],
        limit: null,
        sql: run.config.sql === ALL_ROWS ? null : run.config.sql,
      },
    });
    toast(`Loaded the run's ${run.config.tasks.length === 1 ? "task" : "tasks"} into the editor`);
  }

  useEffect(() => {
    actionsRef.current = {
      run: () => startRun(),
      label: () => update({ mode: "label" }),
      addTask: (preset) => (preset ? addPresetTask(preset) : addTask()),
      clearTasks,
    };
    return () => {
      actionsRef.current = null;
    };
  }, [actionsRef, startRun, addTask, addPresetTask, clearTasks, update]);

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
              {active.length > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-xs"
                  onClick={() => onTabChange("runs")}
                >
                  <Spinner data-icon="inline-start" />
                  {progress(active)}
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
                <TabsTrigger className="dark:data-active:bg-popover" value="runs">
                  Runs
                </TabsTrigger>
              </TabsList>
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={<Button variant="ghost" size="icon-sm" aria-label="Dataset actions" />}
                >
                  <EllipsisIcon />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => onTabChange("runs")}>View runs</DropdownMenuItem>
                  <DropdownMenuItem disabled={!canEdit} onClick={onExport}>
                    <DownloadIcon />
                    Export…
                    <DropdownMenuShortcut>E</DropdownMenuShortcut>
                  </DropdownMenuItem>
                  <DropdownMenuItem disabled={!canEdit} onClick={onRename}>
                    Rename dataset…
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive" disabled={!canEdit} onClick={onDelete}>
                    <Trash2Icon />
                    Delete dataset
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </PaneHeader>
          {tab === "rows" && latest?.status === "failed" && latest.error && (
            <Alert variant="destructive" className="m-3 mb-0 w-auto">
              <AlertTitle>The last run stopped</AlertTitle>
              <AlertDescription>{latest.error}</AlertDescription>
            </Alert>
          )}
          <TabsContent value="rows" keepMounted className="min-h-0 flex-1">
            <DatasetExplorer
              dataset={dataset}
              view={draft.view}
              sql={sql}
              onViewChange={updateView}
              version={version}
              onCount={setSelectedCount}
              onPickRow={mode === "label" ? setLabelPosition : undefined}
              selectedPosition={mode === "label" ? labelPosition : undefined}
              priorityColumns={comparedColumns}
              onDeleteAnswers={canEdit ? setDeletingAnswers : undefined}
            />
          </TabsContent>
          <TabsContent value="columns" className="min-h-0 flex-1 overflow-auto p-3">
            <ColumnProfiles datasetId={dataset.id} />
          </TabsContent>
          {/* Kept mounted, so the columns picked stay picked while looking at their rows. */}
          <TabsContent value="compare" keepMounted className="min-h-0 flex-1 overflow-hidden">
            <CompareView
              dataset={dataset}
              version={version}
              onFilter={showRows}
              actionsRef={comparisonActionsRef}
            />
          </TabsContent>
          <TabsContent value="runs" className="min-h-0 flex-1 overflow-auto">
            <RunsView
              dataset={dataset}
              runs={runs}
              onChanged={onChanged}
              onEdit={editRun}
              onDeleteAnswers={setDeletingAnswers}
            />
          </TabsContent>
        </Tabs>
      </ResizablePanel>
      <ResizableHandle />
      <ResizablePanel id="job" defaultSize="30" minSize="20">
        <div className="flex h-full flex-col bg-card">
          <PaneHeader>
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button size="sm" variant="outline" />}>
                {mode === "label" ? "Label by hand" : "Ask models"}
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuRadioGroup
                  value={mode}
                  onValueChange={(value) => update({ mode: value as "ask" | "label" })}
                >
                  <DropdownMenuRadioItem closeOnClick value="ask">
                    Ask models
                  </DropdownMenuRadioItem>
                  <DropdownMenuRadioItem closeOnClick value="label">
                    Label by hand
                  </DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
            {mode === "ask" && (
              <TooltipButton
                label={
                  !canEdit
                    ? "Running tasks needs the member role"
                    : (problem ??
                      (estimate
                        ? describeEstimate(estimate)
                        : "Run every task on the rows in the table, adding its answers as columns"))
                }
                aria-label={`Run on ${formatNumber(selectedCount)} rows`}
                keys={["⌘", "↵"]}
                size="sm"
                className="ml-auto text-xs"
                disabled={!canEdit || starting}
                onClick={() => startRun()}
              >
                {starting ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <PlayIcon data-icon="inline-start" />
                )}
                Run on {formatNumber(selectedCount)} rows
              </TooltipButton>
            )}
          </PaneHeader>
          {mode === "label" ? (
            <LabelPane
              dataset={dataset}
              task={labelTask}
              isNew={!existingLabels}
              editor={
                <TaskEditor
                  dataset={dataset}
                  tasks={[labelTask]}
                  sql={sql}
                  opened={labelTask.id}
                  onTasksChange={([task]) => update({ label: task })}
                  onAddTask={() => {}}
                  runError={undefined}
                  problem={undefined}
                  needsProvider={false}
                  labels
                />
              }
              onPickColumn={(answer) => update({ label: answer.task })}
              onNewColumn={() => update({ label: newLabelTask(dataset) })}
              sql={sql}
              position={labelPosition}
              onPosition={setLabelPosition}
              onChanged={labelChanged}
              canEdit={canEdit}
            />
          ) : (
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
                needsProvider={needsProvider}
              />
            </div>
          )}
        </div>
      </ResizablePanel>
      <DeleteAnswers
        datasetId={dataset.id}
        answer={deletingAnswers}
        onClose={() => setDeletingAnswers(undefined)}
        onDeleted={labelChanged}
      />
    </>
  );
}

/** E.g. "About $0.12 for 400 calls · kev-base not priced · 20 answered · 3 missing input". */
function describeEstimate(estimate: Estimate): string {
  return [
    `About ${formatUsd(estimate.cost)} for ${formatNumber(estimate.calls)} calls`,
    estimate.unpriced.length > 0 && `${estimate.unpriced.join(", ")} not priced`,
    estimate.answered > 0 && `${formatNumber(estimate.answered)} answered already`,
    estimate.missing_input > 0 && `${formatNumber(estimate.missing_input)} missing input`,
    estimate.failed_before > 0 && `${formatNumber(estimate.failed_before)} failed before`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** How far the active runs are, e.g. "Running 40%". */
function progress(active: Run[]): string {
  const total = active.reduce((n, r) => n + r.total, 0);
  const done = active.reduce((n, r) => n + r.done, 0);
  return total ? `Running ${Math.floor((100 * done) / total)}%` : "Queued";
}

/** A label column to start with: `label`, or `label_2` and so on when that is taken. */
function newLabelTask(dataset: Dataset): Task {
  const taken = new Set(dataset.columns.map((c) => c.name));
  let column = "label";
  for (let n = 2; taken.has(column); n++) column = `label_${n}`;
  return { ...emptyTask([]), column, template: "", models: [] };
}
