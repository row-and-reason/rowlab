"use client";

import {
  ArrowLeftIcon,
  DownloadIcon,
  EllipsisIcon,
  PencilIcon,
  PlayIcon,
  RotateCcwIcon,
  ScanTextIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { withFittingModels, withPreset } from "@/components/answer-settings";
import { ColumnProfiles } from "@/components/column-profiles";
import { CompareView } from "@/components/compare-view";
import { DatasetExplorer } from "@/components/dataset-explorer";
import { Lineage } from "@/components/lineage";
import { PaneHeader } from "@/components/pane";
import { RowReview } from "@/components/row-review";
import { RunScope } from "@/components/run-scope";
import { TaskEditor } from "@/components/task-editor";
import { TooltipButton } from "@/components/tooltip-button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { ResizableHandle, ResizablePanel } from "@/components/ui/resizable";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api,
  type Dataset,
  type Estimate,
  type Preset,
  type Run,
  type Task,
} from "@/lib/api/client";
import { useModels, useTaskTypes } from "@/lib/catalog";
import { saveDraft, useDraft } from "@/lib/draft";
import { errorMessage, formatBytes, formatNumber, formatUsd } from "@/lib/format";
import { isActive } from "@/lib/runs";
import { settingsUrl } from "@/lib/settings";
import { type View, viewSql, type WhereFilter } from "@/lib/sql";

export const TABS = ["rows", "columns", "compare", "lineage"] as const;
export type Tab = (typeof TABS)[number];
export type TaskActions = {
  run: () => void;
  addTask: (preset?: Preset) => void;
  clearTasks: () => void;
  review: () => void;
  configure: () => void;
  sql: string;
};

export function DatasetPanels({
  dataset,
  datasets,
  tab,
  onTabChange,
  onExport,
  onDelete,
  onRename,
  onChanged,
  onOpenDataset,
  actionsRef,
  compact = false,
  providerConnected,
}: {
  dataset: Dataset;
  datasets: Dataset[];
  tab: Tab;
  onTabChange: (tab: Tab) => void;
  onExport: () => void;
  onDelete: () => void;
  onRename: () => void;
  onChanged: () => void;
  onOpenDataset: (datasetId: string) => void;
  actionsRef: React.RefObject<TaskActions | null>;
  compact?: boolean;
  providerConnected?: boolean;
}) {
  const params = useSearchParams();
  const firstAnswer = dataset.run
    ? dataset.columns.find(
        (c) => c.name !== "__row_id" && c.name.includes("__") && !/_(proba|reason)$/.test(c.name),
      )
    : undefined;
  const { draft, update } = useDraft(dataset.id, () => ({
    view: {
      search: "",
      filters: firstAnswer ? [{ column: firstAnswer.name, op: "is_not_null", value: null }] : [],
      sort: [],
      limit: dataset.run ? null : 20,
      sample: !dataset.run,
      sql: null,
    },
    tasks: [{ ...emptyTask([]), column: "answer" }],
  }));
  const updateView = useCallback(
    (changes: Partial<View>) => update((draft) => ({ view: { ...draft.view, ...changes } })),
    [update],
  );
  const sql = viewSql(draft.view, dataset.columns);
  const run = dataset.run;
  const making = !!run && isActive(run);
  const [details, setDetails] = useState<Run>();
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState(!run);
  const [pane, setPane] = useState<"rows" | "task">("rows");
  const [review, setReview] = useState<{ sql: string; index: number }>();
  const [blind, setBlind] = useState(false);
  const reviewIndex = review?.sql === sql ? review.index : null;
  const [opened, setOpened] = useState<string>();
  const [starting, setStarting] = useState(false);
  const [runError, setRunError] = useState<string>();
  const types = useTaskTypes();
  const models = useModels();
  const estimate = useEstimate(dataset.id, sql, draft.tasks);
  const name =
    draft.name ??
    `${draft.tasks.map((t) => t.column || "Labels").join(", ")} · ${dataset.name}`.slice(0, 120);

  const nameProblem = !name.trim()
    ? "Name this result before running."
    : /[/\\\x00-\x1f]/.test(name)
      ? "Use a name without slashes or control characters."
      : undefined;

  useEffect(() => {
    if (!run) return;
    let current = true;
    api
      .GET("/v1/runs/{run_id}", { params: { path: { run_id: run.id } } })
      .then(({ data, error }) => {
        if (!current) return;
        if (data) setDetails(data);
        else if (error) toast.error(errorMessage(error));
      });
    return () => {
      current = false;
    };
  }, [run]);

  const configure = useCallback(() => {
    setReview(undefined);
    setEditing(true);
    setPane("task");
  }, []);
  const reviewRows = useCallback(() => {
    setReview({ sql, index: 0 });
    setPane("task");
    onTabChange("rows");
  }, [sql, onTabChange]);
  function reviewSample() {
    const answer = details?.columns[0];
    const view: View = {
      search: "",
      filters: answer ? [{ column: answer, op: "is_not_null", value: null }] : [],
      sort: [],
      limit: 20,
      sample: true,
      sql: null,
    };
    update({ view });
    setReview({ sql: viewSql(view, dataset.columns), index: 0 });
    setPane("task");
    onTabChange("rows");
  }
  function showRows(filters: WhereFilter[], comparedSql: string) {
    updateView({
      sql: `SELECT * FROM (${comparedSql}) WHERE ${filters.map((f) => `(${f.where})`).join(" AND ")}`,
    });
    setReview(undefined);
    setPane("rows");
    onTabChange("rows");
  }
  async function changeRun(action: "stop" | "resume") {
    if (!run) return;
    const path = { params: { path: { run_id: run.id } } };
    const { error } =
      action === "stop"
        ? await api.POST("/v1/runs/{run_id}/stop", path)
        : await api.POST("/v1/runs/{run_id}/resume", path);
    if (error) {
      toast.error(errorMessage(error));
      return;
    }
    onChanged();
  }
  function reuse() {
    if (!details || !dataset.parent_id) return;
    saveDraft(dataset.parent_id, {
      view: {
        search: "",
        filters: [],
        sort: [],
        limit: null,
        sql: details.config.sql,
      },
      tasks: details.config.tasks,
    });
    onOpenDataset(dataset.parent_id);
  }
  const startRun = useCallback(async () => {
    if (starting || making || reviewIndex !== null) return;
    if (!editing) {
      configure();
      return;
    }
    if (!estimate || estimate.problem || nameProblem) return;
    setStarting(true);
    setRunError(undefined);
    try {
      const { data, error } = await api.POST("/v1/datasets/{dataset_id}/runs", {
        params: { path: { dataset_id: dataset.id } },
        body: { sql, tasks: draft.tasks, name },
      });
      if (error) {
        setRunError(errorMessage(error));
        return;
      }
      onChanged();
      onOpenDataset(data.dataset_id);
    } catch {
      setRunError(
        "Could not reach rowlab. Your draft is saved; check the connection and try again.",
      );
    } finally {
      setStarting(false);
    }
  }, [
    starting,
    making,
    reviewIndex,
    editing,
    configure,
    estimate,
    dataset.id,
    sql,
    draft.tasks,
    name,
    nameProblem,
    onChanged,
    onOpenDataset,
  ]);
  const addTask = useCallback(
    (from?: Task) => {
      const task = from ? { ...from, id: newId() } : emptyTask(draft.tasks);
      update((draft) => ({ tasks: [...draft.tasks, task] }));
      setOpened(task.id);
      configure();
    },
    [draft.tasks, update, configure],
  );
  const addPresetTask = useCallback(
    (preset: Preset) => {
      if (!types) return;
      addTask(withFittingModels(withPreset(emptyTask(draft.tasks), preset), types, models).task);
    },
    [draft.tasks, types, models, addTask],
  );
  const clearTasks = useCallback(() => {
    update({ tasks: [{ ...emptyTask([]), column: "answer" }] });
    configure();
  }, [update, configure]);
  useEffect(() => {
    actionsRef.current = {
      run: startRun,
      addTask: (preset) => (preset ? addPresetTask(preset) : addTask()),
      clearTasks,
      review: reviewRows,
      configure,
      sql,
    };
    return () => {
      actionsRef.current = null;
    };
  }, [actionsRef, startRun, addTask, addPresetTask, clearTasks, reviewRows, configure, sql]);
  useEffect(() => {
    if (reviewIndex === null) return;
    function key(e: KeyboardEvent) {
      if (e.key === "Escape" && !e.defaultPrevented) {
        setReview(undefined);
        setPane("rows");
        e.preventDefault();
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [reviewIndex]);

  const rows = (
    <Tabs
      value={tab}
      onValueChange={(value) => onTabChange(value as Tab)}
      className="flex h-full flex-col gap-0"
    >
      <PaneHeader>
        <span className="min-w-0 truncate font-medium" title={dataset.source}>
          {dataset.name}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">
          {formatNumber(dataset.row_count)} rows · {formatBytes(dataset.size_bytes)}
        </span>
        <div className="ml-auto flex items-center gap-1">
          {run && ["queued", "running"].includes(run.status) && (
            <Button size="sm" variant="ghost" onClick={() => void changeRun("stop")}>
              <SquareIcon />
              Stop
            </Button>
          )}
          {run && ["stopped", "failed"].includes(run.status) && (
            <Button size="sm" variant="ghost" onClick={() => void changeRun("resume")}>
              <PlayIcon />
              Resume
            </Button>
          )}
          {run?.status === "done" && run.failed > 0 && (
            <Button size="sm" variant="ghost" onClick={() => void changeRun("resume")}>
              <RotateCcwIcon />
              Retry {formatNumber(run.failed)} failed
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="ghost" size="icon-sm" aria-label="Dataset actions" />}
            >
              <EllipsisIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={onRename}>
                <PencilIcon />
                Rename…
              </DropdownMenuItem>
              <DropdownMenuItem disabled={making} onClick={onExport}>
                <DownloadIcon />
                Export…<DropdownMenuShortcut>E</DropdownMenuShortcut>
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onClick={onDelete}>
                <Trash2Icon />
                Delete dataset
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </PaneHeader>
      <div className="flex shrink-0 items-center justify-between gap-1 border-b px-2 py-1">
        <TabsList>
          <TabsTrigger value="rows">Rows</TabsTrigger>
          <TabsTrigger value="columns">Columns</TabsTrigger>
          <TabsTrigger value="compare">Compare</TabsTrigger>
          <TabsTrigger value="lineage">Lineage</TabsTrigger>
        </TabsList>
        {compact && (
          <Button size="sm" variant="outline" onClick={() => setPane("task")}>
            {editing ? "Configure run" : "Run details"}
          </Button>
        )}
      </div>
      <TabsContent value="rows" keepMounted className="min-h-0 flex-1">
        <DatasetExplorer
          dataset={dataset}
          view={draft.view}
          sql={sql}
          onViewChange={updateView}
          version={`${run?.done}:${revision}`}
          onReview={(index) => {
            setReview({ sql, index });
            setPane("task");
          }}
          selectedRow={reviewIndex}
          hideAnswers={reviewIndex !== null && blind}
        />
      </TabsContent>
      <TabsContent value="columns" className="min-h-0 flex-1 overflow-auto p-3">
        <ColumnProfiles key={revision} datasetId={dataset.id} />
      </TabsContent>
      <TabsContent value="compare" keepMounted className="min-h-0 flex-1 overflow-auto">
        <CompareView
          dataset={dataset}
          sql={sql}
          version={`${run?.done}:${revision}`}
          onReview={reviewSample}
          onFilter={showRows}
        />
      </TabsContent>
      <TabsContent value="lineage" className="min-h-0 flex-1 overflow-auto">
        <Lineage dataset={dataset} datasets={datasets} onOpenDataset={onOpenDataset} />
      </TabsContent>
    </Tabs>
  );

  const taskPane =
    reviewIndex !== null ? (
      <RowReview
        dataset={dataset}
        sql={sql}
        index={reviewIndex}
        version={revision}
        tasks={details?.config.tasks ?? []}
        hidden={blind}
        onHiddenChange={setBlind}
        onMove={(index) => setReview({ sql, index })}
        onClose={() => {
          setReview(undefined);
          setPane("rows");
        }}
        onSaved={() => {
          setRevision((value) => value + 1);
          onChanged();
        }}
      />
    ) : (
      <div className="flex h-full flex-col">
        <PaneHeader>
          {compact && (
            <TooltipButton
              label="Back to data"
              variant="ghost"
              size="icon-sm"
              onClick={() => setPane("rows")}
            >
              <ArrowLeftIcon />
            </TooltipButton>
          )}
          <span className="font-medium">{editing ? "New run" : "Run results"}</span>
          {run && editing && (
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              Results
            </Button>
          )}
          {editing && (
            <TooltipButton
              label={estimate?.problem ?? `Run on ${formatNumber(estimate?.rows ?? 0)} rows`}
              keys={["⌘", "↵"]}
              size="sm"
              className="ml-auto"
              disabled={starting || making || !estimate || !!estimate.problem || !!nameProblem}
              onClick={() => void startRun()}
            >
              {starting ? <Spinner /> : <PlayIcon />}Run on{" "}
              {estimate ? formatNumber(estimate.rows) : "…"} rows
            </TooltipButton>
          )}
        </PaneHeader>
        {editing ? (
          <>
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-3 py-2">
              <RunScope view={draft.view} onChange={updateView} />
              <span className="text-xs text-muted-foreground">
                {estimate
                  ? `≈ ${formatUsd(estimate.cost)} · ${formatNumber(estimate.calls)} calls`
                  : "Checking scope and cost…"}
              </span>
            </div>
            <div className="@container min-h-0 flex-1 overflow-auto">
              <Field className="px-4 py-3">
                <FieldLabel htmlFor="result-name">Result name</FieldLabel>
                <Input
                  id="result-name"
                  maxLength={120}
                  value={name}
                  onChange={(e) => update({ name: e.target.value })}
                />
                {nameProblem && <FieldDescription>{nameProblem}</FieldDescription>}
              </Field>
              {(providerConnected === false ||
                estimate?.problem === "Set your OpenRouter API key first." ||
                runError === "Set your OpenRouter API key first.") && (
                <Alert className="mx-3 mb-3 w-auto">
                  <AlertDescription>
                    <p>
                      Connect OpenRouter to run your tasks. Your draft will be here when you return.
                    </p>
                    <Button
                      size="sm"
                      className="mt-2"
                      nativeButton={false}
                      render={<Link href={settingsUrl(params, "providers")} />}
                    >
                      Connect OpenRouter
                    </Button>
                  </AlertDescription>
                </Alert>
              )}
              <TaskEditor
                dataset={dataset}
                tasks={draft.tasks}
                sql={sql}
                opened={opened}
                onTasksChange={(tasks) => {
                  setRunError(undefined);
                  update({ tasks });
                }}
                onAddTask={addTask}
                runError={runError === "Set your OpenRouter API key first." ? undefined : runError}
                problem={
                  estimate?.problem === "Set your OpenRouter API key first."
                    ? undefined
                    : estimate?.problem?.startsWith("The SQL")
                      ? "Fix the query in Rows before running."
                      : (estimate?.problem ?? undefined)
                }
              />
            </div>
          </>
        ) : (
          <div className="min-h-0 flex-1 overflow-auto p-4">
            {!details ? (
              <Spinner />
            ) : (
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                  <span className="font-medium">
                    {run?.status === "done" ? "Run complete" : `Run ${run?.status}`}
                  </span>
                  <p className="text-sm text-muted-foreground">
                    {formatNumber(Math.max(0, details.done - (run?.failed ?? 0)))} successful
                    answers · {formatNumber(details.row_count)} rows in scope ·{" "}
                    {formatUsd(details.cost)}
                  </p>
                  {!!run?.failed && (
                    <p className="text-sm text-destructive">
                      {formatNumber(run.failed)} failed answers can be retried.
                    </p>
                  )}
                </div>
                <FieldDescription>
                  All {formatNumber(dataset.row_count)} original rows are retained. Rows outside
                  this run&apos;s scope have empty new answers.
                </FieldDescription>
                {making && (
                  <Progress
                    value={details.total ? (100 * details.done) / details.total : 0}
                    aria-label="Run progress"
                  />
                )}
                {details.error && (
                  <Alert variant="destructive">
                    <AlertDescription>{details.error}</AlertDescription>
                  </Alert>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" disabled={making} onClick={reviewSample}>
                    <ScanTextIcon />
                    Review a sample
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      onTabChange("compare");
                      setPane("rows");
                    }}
                  >
                    Compare answers
                  </Button>
                  <Button size="sm" variant="outline" disabled={making} onClick={onExport}>
                    <DownloadIcon />
                    Export results
                  </Button>
                  {!!run?.failed && (
                    <Button size="sm" variant="outline" onClick={() => void changeRun("resume")}>
                      Retry failed answers
                    </Button>
                  )}
                </div>
                <FieldDescription>
                  Review a fixed random sample, then compare the answers against your reviewed
                  labels. Model agreement alone does not establish accuracy.
                </FieldDescription>
                <FieldGroupSummary tasks={details.config.tasks} />
                <Button
                  size="sm"
                  variant="outline"
                  className="self-start"
                  disabled={!datasets.some((d) => d.id === dataset.parent_id)}
                  onClick={reuse}
                >
                  Edit prompt & run again
                </Button>
                <Button size="sm" variant="ghost" className="self-start" onClick={configure}>
                  New run on these rows
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="self-start"
                  onClick={() => {
                    onTabChange("lineage");
                    setPane("rows");
                  }}
                >
                  View lineage and costs
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    );

  return compact ? (
    <>
      <div className={pane === "rows" && reviewIndex === null ? "h-full min-h-0" : "hidden"}>
        {rows}
      </div>
      <div className={pane === "task" || reviewIndex !== null ? "h-full min-h-0" : "hidden"}>
        {taskPane}
      </div>
    </>
  ) : (
    <>
      <ResizableHandle />
      <ResizablePanel id="rows" defaultSize="50" minSize="30">
        {rows}
      </ResizablePanel>
      <ResizableHandle />
      <ResizablePanel id="job" defaultSize="34" minSize="25">
        {taskPane}
      </ResizablePanel>
    </>
  );
}

function FieldGroupSummary({ tasks }: { tasks: Task[] }) {
  return (
    <div className="flex flex-col gap-3">
      {tasks.map((task) => (
        <Field key={task.id}>
          <FieldLabel>{task.column}</FieldLabel>
          <p className="text-sm whitespace-pre-wrap break-words select-text">{task.template}</p>
        </Field>
      ))}
    </div>
  );
}
function emptyTask(existing: Task[]): Task {
  let column = "answer";
  for (let i = 2; existing.some((task) => task.column === column); i++) column = `answer${i}`;
  return {
    id: newId(),
    template: "",
    type: "yes_no",
    column,
    options: [],
    fields: [],
    reason: false,
    models: ["typesafe/jev-1.14"],
  };
}
function useEstimate(datasetId: string, sql: string, tasks: Task[]): Estimate | undefined {
  const [estimate, setEstimate] = useState<{
    key: string;
    estimate: Estimate;
  }>();
  const key = JSON.stringify([datasetId, sql, tasks]);
  useEffect(() => {
    let current = true;
    const timer = setTimeout(() => {
      api
        .POST("/v1/datasets/{dataset_id}/estimate", {
          params: { path: { dataset_id: datasetId } },
          body: { sql, tasks },
        })
        .then(({ data, error }) => {
          if (current)
            setEstimate({
              key,
              estimate: data ?? {
                rows: 0,
                calls: 0,
                cost: 0,
                problem: errorMessage(error),
              },
            });
        })
        .catch(() => {
          if (current)
            setEstimate({
              key,
              estimate: {
                rows: 0,
                calls: 0,
                cost: 0,
                problem: "Could not reach rowlab. Check your connection.",
              },
            });
        });
    }, 300);
    return () => {
      current = false;
      clearTimeout(timer);
    };
    // The key includes the dataset, query and tasks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return estimate?.key === key ? estimate.estimate : undefined;
}
function newId(): string {
  return crypto.randomUUID().replaceAll("-", "").slice(0, 8);
}
