"use client";

import { RepeatIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { modelSlug } from "@/components/answer-settings";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from "@/components/ui/item";
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
import { api, type Dataset, type Run, type Scope, type TaskTypes } from "@/lib/api/client";
import {
  columnLabel,
  describeComparison,
  errorMessage,
  formatAgo,
  formatDuration,
  formatNumber,
  formatUsd,
} from "@/lib/format";
import { isActive } from "@/lib/runs";
import { useTaskTypes } from "@/lib/catalog";
import { loadOrCreate } from "@/lib/use-job";

/**
 * The Lineage tab: what a dataset was made from and how. Every run makes a new dataset, so the datasets
 * form a tree, shown in the dataset list: each one added from a file at the root, and each run's
 * dataset under the one it ran on.
 */
export function Lineage({
  dataset,
  datasets,
  onOpenDataset,
}: {
  dataset: Dataset;
  datasets: Dataset[];
  onOpenDataset: (datasetId: string) => void;
}) {
  const parent = datasets.find((d) => d.id === dataset.parent_id);

  return (
    <FieldGroup className="gap-6 p-4">
      <FieldSet>
        <FieldLegend variant="label">Made from</FieldLegend>
        {dataset.parent_id ? (
          <DatasetList
            datasets={parent ? [parent] : []}
            empty="A dataset that has been deleted."
            onOpenDataset={onOpenDataset}
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            Added {formatAgo(dataset.created_at)} from{" "}
            <span className="break-all select-text">{dataset.source}</span>
          </p>
        )}
      </FieldSet>
      {dataset.run && <RunDetails dataset={dataset} onOpenDataset={onOpenDataset} />}
    </FieldGroup>
  );
}

function DatasetList({
  datasets,
  empty,
  onOpenDataset,
}: {
  datasets: Dataset[];
  empty: string;
  onOpenDataset: (datasetId: string) => void;
}) {
  if (!datasets.length) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ItemGroup className="gap-0.5">
      {datasets.map((d) => (
        <Item
          key={d.id}
          size="xs"
          variant="outline"
          render={
            <button type="button" className="text-left" onClick={() => onOpenDataset(d.id)} />
          }
        >
          <ItemContent className="min-w-0">
            <ItemTitle>{d.name}</ItemTitle>
            <ItemDescription className="truncate text-xs">
              {formatNumber(d.row_count)} rows · {formatAgo(d.created_at)}
            </ItemDescription>
          </ItemContent>
        </Item>
      ))}
    </ItemGroup>
  );
}

/** How a dataset was made: the run's progress, scope, tasks and costs. */
function RunDetails({
  dataset,
  onOpenDataset,
}: {
  dataset: Dataset;
  onOpenDataset: (datasetId: string) => void;
}) {
  const summary = dataset.run!;
  const types = useTaskTypes();
  // Fetched again as the run moves on; the dataset list carries its progress.
  const [run, setRun] = useState<Run>();
  useEffect(() => {
    let current = true;
    api
      .GET("/v1/runs/{run_id}", { params: { path: { run_id: summary.id } } })
      .then(({ data, error }) => {
        if (!current) return;
        if (error) toast.error(errorMessage(error));
        else setRun(data);
      });
    return () => {
      current = false;
    };
  }, [summary.id, summary.status, summary.done]);
  const speed = useSpeed(summary);

  // Puts this run's rows and tasks into the parent's job, to change and run again.
  async function runAgain(config: Run["config"]) {
    const job = await loadOrCreate(dataset.parent_id!);
    if (!job) return;
    const { error } = await api.PUT("/v1/jobs/{job_id}", {
      params: { path: { job_id: job.id } },
      body: config,
    });
    if (error) toast.error(errorMessage(error));
    else onOpenDataset(dataset.parent_id!);
  }

  if (!run) return <Spinner />;
  const parentExists = !!dataset.parent_id;
  return (
    <FieldSet>
      <FieldLegend variant="label">How it was made</FieldLegend>
      <p className="text-sm text-muted-foreground">
        {statusText(run)} · {formatAgo(run.created_at)}
        <br />
        {describeScope(run.config.scope)}
      </p>
      {isActive(run) && (
        <div className="flex flex-col gap-1.5">
          <Progress value={run.total ? (100 * run.done) / run.total : 0} aria-label="Progress" />
          {speed && (
            <p className="text-xs text-muted-foreground">
              {formatNumber(Math.round(speed.perSecond))} answers a second · about{" "}
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
      {run.config.tasks.map((task) => (
        <Field key={task.id}>
          <FieldLabel>
            {task.column}
            <span className="font-normal text-muted-foreground">
              {types?.types.find((t) => t.id === task.type)?.label} ·{" "}
              {task.models.map(modelSlug).join(", ")}
            </span>
          </FieldLabel>
          <p className="rounded-lg bg-muted p-3 text-sm whitespace-pre-wrap select-text">
            {task.template}
          </p>
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
          {task.reason && <p className="text-xs text-muted-foreground">With why</p>}
        </Field>
      ))}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Task</TableHead>
            <TableHead>Model</TableHead>
            <TableHead className="text-right">Failed</TableHead>
            <TableHead className="text-right">Cost</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {run.costs.map((c) => (
            <TableRow key={`${c.task_id} ${c.model}`}>
              <TableCell>{run.config.tasks.find((t) => t.id === c.task_id)?.column}</TableCell>
              <TableCell>{modelSlug(c.model)}</TableCell>
              <TableCell className="text-right">{c.failed || ""}</TableCell>
              <TableCell className="text-right">{formatUsd(c.cost)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {parentExists && (
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => runAgain(run.config)}
        >
          <RepeatIcon data-icon="inline-start" />
          Use these settings again
        </Button>
      )}
    </FieldSet>
  );
}

function fieldLabel(type: string, types: TaskTypes | undefined): string {
  return types?.field_types.find((t) => t.id === type)?.label.toLowerCase() ?? type;
}

/** Where a run stands, e.g. "Running, 120 of 400 answers · $0.01". */
function statusText(run: Run): string {
  const progress = `${formatNumber(run.done)} of ${formatNumber(run.total)} answers`;
  const label = {
    queued: "Queued",
    running: `Running, ${progress}`,
    stopping: "Stopping",
    stopped: `Stopped at ${progress}`,
    failed: "Failed",
    done: "Done",
  }[run.status];
  return run.cost ? `${label} · ${formatUsd(run.cost)}` : label;
}

/** Answers per second while this run has been on screen, and the time left at that pace. */
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

/** A scope in words, e.g. “city = Tokyo · spend, high to low · first 8 rows”. */
function describeScope(scope: Scope): string {
  const parts = [
    scope.search && `“${scope.search}”`,
    ...scope.filters.map((f) =>
      f.columns.length
        ? describeComparison(f)
        : [columnLabel(f.column), f.op.replaceAll("_", " "), f.value ?? ""].join(" ").trim(),
    ),
    ...scope.sort.map((s) => `${columnLabel(s.column)}, ${s.desc ? "high to low" : "low to high"}`),
    scope.limit && `first ${formatNumber(scope.limit)} rows`,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "All rows";
}
