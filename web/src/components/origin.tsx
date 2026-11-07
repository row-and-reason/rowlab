"use client";

import { ChevronDownIcon, GitCompareArrowsIcon, RepeatIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { modelSlug } from "@/components/answer-settings";
import { useCan } from "@/components/me";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type Dataset, type Run, type TaskTypes } from "@/lib/api/client";
import {
  errorMessage,
  formatAgo,
  formatDate,
  formatDuration,
  formatNumber,
  formatUsd,
} from "@/lib/format";
import { isActive } from "@/lib/runs";
import { useTaskTypes } from "@/lib/catalog";
import { loadDraft, saveDraft } from "@/lib/draft";

export type OriginActions = { edit?: () => void };

/** Where this dataset came from, and the recorded outcome and recipe of its run. */
export function Origin({
  dataset,
  datasets,
  onOpenDataset,
  onInspect,
  actionsRef,
}: {
  dataset: Dataset;
  datasets: Dataset[];
  onOpenDataset: (id: string) => void;
  onInspect: (columns: string[]) => void;
  actionsRef: React.RefObject<OriginActions | null>;
}) {
  const parent = datasets.find((d) => d.id === dataset.parent_id);
  const source = (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      <span className="text-muted-foreground">
        {dataset.parent_id ? "Made from" : "Imported from"}
      </span>
      {parent ? (
        <Button
          variant="link"
          size="sm"
          className="h-auto px-0 text-xs"
          onClick={() => onOpenDataset(parent.id)}
        >
          {parent.name}
        </Button>
      ) : (
        <span className="break-all select-text">
          {dataset.source}
          {dataset.parent_id ? " (deleted)" : ""}
        </span>
      )}
      {parent && (
        <span className="text-muted-foreground">{formatNumber(parent.row_count)} rows</span>
      )}
    </div>
  );
  return (
    <div className="space-y-4 p-3 text-sm">
      {dataset.run ? (
        <RunDetails
          dataset={dataset}
          parent={parent}
          onOpenDataset={onOpenDataset}
          onInspect={onInspect}
          source={source}
          actionsRef={actionsRef}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="font-medium">Imported dataset</span>
            <span className="text-xs text-muted-foreground" title={formatDate(dataset.created_at)}>
              {formatAgo(dataset.created_at)}
            </span>
          </div>
          {source}
          <div className="text-xs text-muted-foreground">
            {formatNumber(dataset.row_count)} rows ·{" "}
            {dataset.columns.filter((c) => c.name !== "__row_id").length} columns
          </div>
          <Button variant="outline" size="sm" onClick={() => onInspect([])}>
            View rows
          </Button>
        </>
      )}
    </div>
  );
}

function RunDetails({
  dataset,
  parent,
  source,
  onOpenDataset,
  onInspect,
  actionsRef,
}: {
  dataset: Dataset;
  parent?: Dataset;
  source: React.ReactNode;
  onOpenDataset: (id: string) => void;
  onInspect: (columns: string[]) => void;
  actionsRef: React.RefObject<OriginActions | null>;
}) {
  const summary = dataset.run!;
  const types = useTaskTypes();
  const router = useRouter();
  const canEdit = useCan("member");
  const [result, setResult] = useState<{ id: string; run?: Run; error?: string }>();
  const [attempt, setAttempt] = useState(0);
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    let current = true;
    api
      .GET("/v1/runs/{run_id}", { params: { path: { run_id: summary.id } } })
      .then(({ data, error }) => {
        if (current)
          setResult({ id: summary.id, run: data, error: error ? errorMessage(error) : undefined });
      })
      .catch(() => {
        if (current)
          setResult({
            id: summary.id,
            error: "Could not load this run. Check your connection and try again.",
          });
      });
    return () => {
      current = false;
    };
  }, [summary.id, summary.status, summary.done, attempt]);
  const run = result?.id === summary.id ? result.run : undefined;
  const speed = useSpeed(summary);
  const applySettings = useCallback(() => {
    if (!run || !parent || !canEdit) return;
    saveDraft(parent.id, {
      view: { search: "", filters: [], sort: [], limit: null, sql: run.config.sql },
      tasks: run.config.tasks,
    });
    setConfirm(false);
    onOpenDataset(parent.id);
  }, [run, parent, canEdit, onOpenDataset]);
  const edit = useCallback(() => {
    if (!parent || !run || !canEdit) return;
    if (loadDraft(parent.id)) setConfirm(true);
    else applySettings();
  }, [parent, run, canEdit, applySettings]);
  useEffect(() => {
    actionsRef.current = { edit: run && parent && canEdit ? edit : undefined };
    return () => {
      actionsRef.current = null;
    };
  }, [actionsRef, run, parent, canEdit, edit]);
  if (result?.id === summary.id && result.error)
    return (
      <Alert variant="destructive">
        <AlertDescription>{result.error}</AlertDescription>
        <Button size="sm" variant="outline" onClick={() => setAttempt((n) => n + 1)}>
          Retry
        </Button>
      </Alert>
    );
  if (!run)
    return (
      <div role="status" className="flex items-center gap-2 text-muted-foreground">
        <Spinner />
        Loading origin…
      </div>
    );
  const failed = run.costs.reduce((n, c) => n + c.failed, 0);
  const status = {
    queued: "Queued",
    running: "Running",
    stopping: "Stopping",
    stopped: "Stopped",
    failed: "Run failed",
    done: failed ? "Completed with failures" : "Completed",
  }[run.status];
  function compare(columns: string[]) {
    const query = new URLSearchParams(window.location.search);
    for (const key of ["reference", "pair", "tolerance", "ignore_case", "trim_whitespace"])
      query.delete(key);
    query.set("tab", "compare");
    query.set("compare", JSON.stringify(columns));
    router.push(`/?${query}`);
  }
  return (
    <>
      <section className="space-y-2" aria-label="Run outcome">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="font-medium">{status}</span>
          <span className={failed ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
            {formatNumber(failed)} failed calls
          </span>
          <span
            className="text-xs text-muted-foreground"
            title={`Created ${formatDate(run.created_at)}`}
          >
            {formatAgo(run.created_at)}
          </span>
          {parent && canEdit && (
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              onClick={edit}
              title={`Load these settings on ${parent.name}; no run starts automatically`}
            >
              <RepeatIcon />
              Edit and run again
            </Button>
          )}
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums">
          <span>
            {formatNumber(run.row_count)} / {formatNumber(dataset.row_count)} rows selected
          </span>
          <span>
            {formatNumber(run.done)} / {formatNumber(run.total)} calls processed
          </span>
          <span title="Recorded spend. Cached answers incur no new charge.">
            {formatUsd(run.cost)} spent
          </span>
        </div>
        {isActive(run) && (
          <div className="space-y-1.5">
            <Progress
              value={run.total ? (100 * run.done) / run.total : 0}
              aria-label="Run progress"
            />
            {speed && (
              <p className="text-xs text-muted-foreground">
                {formatNumber(Math.round(speed.perSecond))} calls / second · about{" "}
                {formatDuration(speed.secondsLeft)} left
              </p>
            )}
          </div>
        )}
        {run.error && (
          <Alert variant="destructive">
            <AlertDescription>{run.error}</AlertDescription>
          </Alert>
        )}
      </section>
      {source}
      <div className="space-y-1" aria-label="Output columns">
        <span className="text-xs text-muted-foreground">Output columns</span>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {run.columns.map((column) => (
            <Button
              key={column}
              variant="link"
              size="sm"
              className="h-auto max-w-full whitespace-normal break-all px-0 text-left text-xs"
              onClick={() => onInspect([column])}
            >
              {column}
            </Button>
          ))}
        </div>
      </div>
      {run.config.tasks.map((task) => {
        const comparable = task.models
          .map((m) => `${task.column}__${modelSlug(m)}`)
          .filter((name) => run.columns.includes(name));
        return (
          <section
            key={task.id}
            className="space-y-2 border-t pt-3"
            aria-label={`Task ${task.column}`}
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <h3 className="font-medium">{task.column}</h3>
              <span className="text-xs text-muted-foreground">
                {types?.types.find((t) => t.id === task.type)?.label ?? task.type}
                {task.reason ? " · with explanation" : ""}
              </span>
              {comparable.length > 1 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto px-0 text-xs"
                  onClick={() => compare(comparable)}
                >
                  <GitCompareArrowsIcon />
                  Compare models
                </Button>
              )}
            </div>
            {task.options.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {task.type === "scale" ? "Levels" : "Options"}:{" "}
                {task.options.map((o) => o.name).join(", ")}
              </p>
            )}
            {task.fields.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Fields:{" "}
                {task.fields.map((f) => `${f.name} (${fieldLabel(f.type, types)})`).join(", ")}
              </p>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead className="text-right">Answered</TableHead>
                  <TableHead className="text-right">Failed</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {task.models.map((model) => {
                  const cost = run.costs.find((c) => c.task_id === task.id && c.model === model);
                  return (
                    <TableRow key={model}>
                      <TableCell title={model}>{modelSlug(model)}</TableCell>
                      <TableCell
                        className="text-right tabular-nums"
                        title={
                          run.status !== "done" ? "Available when the run completes" : undefined
                        }
                      >
                        {run.status === "done" && cost
                          ? formatNumber(run.row_count - cost.failed)
                          : "—"}
                      </TableCell>
                      <TableCell
                        className={`text-right tabular-nums ${cost?.failed ? "text-destructive" : "text-muted-foreground"}`}
                      >
                        {cost ? formatNumber(cost.failed) : "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {cost ? formatUsd(cost.cost) : "—"}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            <div className="space-y-1 pt-1">
              <span className="text-xs text-muted-foreground">Prompt</span>
              <p className="border-l-2 pl-3 text-sm whitespace-pre-wrap select-text">
                {task.template}
              </p>
            </div>
          </section>
        );
      })}
      <Collapsible className="border-t pt-2" defaultOpen={run.row_count < dataset.row_count}>
        <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="px-0 text-xs" />}>
          <ChevronDownIcon className="size-3" />
          Scope query ·{" "}
          {run.row_count === dataset.row_count ? "all rows" : `${formatNumber(run.row_count)} rows`}
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="pt-2 font-mono text-xs whitespace-pre-wrap break-all select-text">
            {run.config.sql}
          </pre>
        </CollapsibleContent>
      </Collapsible>
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Replace the draft on {parent?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This replaces its current tasks and row selection with this run’s settings. No run
              will start automatically.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep draft</AlertDialogCancel>
            <AlertDialogAction onClick={applySettings}>Replace draft and edit</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function fieldLabel(type: string, types: TaskTypes | undefined): string {
  return types?.field_types.find((t) => t.id === type)?.label.toLowerCase() ?? type;
}

function useSpeed(
  run: Pick<Run, "id" | "done" | "total">,
): { perSecond: number; secondsLeft: number } | undefined {
  const first = useRef<{ runId: string; done: number; at: number }>(undefined);
  const [speed, setSpeed] = useState<{ perSecond: number; secondsLeft: number }>();
  useEffect(() => {
    const start = first.current;
    if (!start || start.runId !== run.id || run.done < start.done) {
      first.current = { runId: run.id, done: run.done, at: Date.now() };
      setSpeed(undefined);
      return;
    }
    const seconds = (Date.now() - start.at) / 1000;
    if (seconds < 2 || run.done <= start.done) return;
    const perSecond = (run.done - start.done) / seconds;
    setSpeed({ perSecond, secondsLeft: (run.total - run.done) / perSecond });
  }, [run.id, run.done, run.total]);
  return speed;
}
