"use client";

import {
  ChevronDownIcon,
  EllipsisIcon,
  GitCompareArrowsIcon,
  PencilIcon,
  RotateCcwIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { answerLabel } from "@/components/delete-answers";
import { useCan } from "@/components/me";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type AnswerColumn, type Dataset, type Run, type TaskTypes } from "@/lib/api/client";
import { useTaskTypes } from "@/lib/catalog";
import {
  errorMessage,
  formatAgo,
  formatDate,
  formatDuration,
  formatNumber,
  formatUsd,
} from "@/lib/format";
import { isActive } from "@/lib/runs";
import { ALL_ROWS } from "@/lib/sql";
import { modelSlug } from "@/lib/tasks";

/** Where the dataset came from, and its runs, newest first: what each asked, how it went, its cost. */
export function RunsView({
  dataset,
  runs,
  onChanged,
  onEdit,
  onDeleteAnswers,
}: {
  dataset: Dataset;
  runs: Run[];
  onChanged: () => void;
  /** Load a run's tasks and rows into the task editor. */
  onEdit: (run: Run) => void;
  onDeleteAnswers: (answer: AnswerColumn) => void;
}) {
  return (
    <div className="space-y-4 p-3 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs">
        <span className="text-muted-foreground">Imported from</span>
        <span className="break-all select-text">{dataset.source}</span>
        <span className="text-muted-foreground" title={formatDate(dataset.created_at)}>
          {formatAgo(dataset.created_at)} · {formatNumber(dataset.row_count)} rows
        </span>
      </div>
      {runs.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No runs yet. The tasks on the right ask models about the rows in the table, adding their
          answers as columns.
        </p>
      ) : (
        runs.map((run) => (
          <RunSection
            key={run.id}
            dataset={dataset}
            run={run}
            onChanged={onChanged}
            onEdit={() => onEdit(run)}
            onDeleteAnswers={onDeleteAnswers}
          />
        ))
      )}
    </div>
  );
}

const STATUS = {
  queued: "Queued",
  running: "Running",
  stopping: "Stopping",
  stopped: "Stopped",
  failed: "Failed",
  done: "Done",
};

function RunSection({
  dataset,
  run,
  onChanged,
  onEdit,
  onDeleteAnswers,
}: {
  dataset: Dataset;
  run: Run;
  onChanged: () => void;
  onEdit: () => void;
  onDeleteAnswers: (answer: AnswerColumn) => void;
}) {
  const types = useTaskTypes();
  const router = useRouter();
  const canEdit = useCan("member");
  const speed = useSpeed(run);
  const [busy, setBusy] = useState(false);
  const failed = run.costs.reduce((n, c) => n + c.failed, 0);
  const active = isActive(run);
  const answerOf = (column: string, model: string) =>
    dataset.answers.find((a) => a.name === column && a.model === model);
  const deletable = run.config.tasks.flatMap((task) =>
    task.models.map((model) => answerOf(task.column, model)).filter((a) => !!a),
  );

  async function stop() {
    setBusy(true);
    const { error } = await api.POST("/v1/runs/{run_id}/stop", {
      params: { path: { run_id: run.id } },
    });
    setBusy(false);
    if (error) toast.error(errorMessage(error));
    onChanged();
  }

  // Asks the same tasks on the same rows again: only what is still missing is asked.
  async function startAgain() {
    setBusy(true);
    const { error } = await api.POST("/v1/datasets/{dataset_id}/runs", {
      params: { path: { dataset_id: dataset.id } },
      body: run.config,
    });
    setBusy(false);
    if (error) toast.error(errorMessage(error));
    onChanged();
  }

  function compare(columns: string[]) {
    const query = new URLSearchParams(window.location.search);
    for (const key of ["reference", "pair", "tolerance", "ignore_case", "trim_whitespace"])
      query.delete(key);
    query.set("tab", "compare");
    query.set("compare", JSON.stringify(columns));
    router.push(`/?${query}`);
  }

  return (
    <section className="space-y-2 border-t pt-3" aria-label={`Run ${run.id}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">{STATUS[run.status]}</span>
        <span className="text-xs text-muted-foreground" title={formatDate(run.created_at)}>
          {formatAgo(run.created_at)}
        </span>
        <div className="ml-auto flex items-center gap-1">
          {canEdit && active && (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy || run.status === "stopping"}
              onClick={stop}
            >
              <SquareIcon data-icon="inline-start" />
              Stop
            </Button>
          )}
          {canEdit && !active && (run.status !== "done" || failed > 0) && (
            <Button
              size="sm"
              variant="ghost"
              title="Ask what is still missing; answers it has are free"
              disabled={busy}
              onClick={startAgain}
            >
              <RotateCcwIcon data-icon="inline-start" />
              Start again
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="ghost" size="icon-sm" aria-label="Run actions" />}
            >
              <EllipsisIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              <DropdownMenuItem disabled={!canEdit || !active || busy} onClick={stop}>
                <SquareIcon />
                Stop
              </DropdownMenuItem>
              <DropdownMenuItem disabled={!canEdit || active || busy} onClick={startAgain}>
                <RotateCcwIcon />
                Start again
              </DropdownMenuItem>
              <DropdownMenuItem disabled={!canEdit} onClick={onEdit}>
                <PencilIcon />
                Edit its tasks
              </DropdownMenuItem>
              {deletable.length > 0 && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>Delete answers</DropdownMenuLabel>
                    {deletable.map((answer) => (
                      <DropdownMenuItem
                        key={`${answer.name}:${answer.model}`}
                        variant="destructive"
                        disabled={!canEdit}
                        onClick={() => onDeleteAnswers(answer)}
                      >
                        <Trash2Icon />
                        <span className="truncate">{answerLabel(answer)}…</span>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuGroup>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums">
        <span>{formatNumber(run.row_count)} rows</span>
        <span>
          {formatNumber(run.done)} / {formatNumber(run.total)} answers asked
        </span>
        <span className={failed ? "text-destructive" : "text-muted-foreground"}>
          {formatNumber(failed)} failed
        </span>
        <span title="Cached answers are free.">{formatUsd(run.cost)} spent</span>
      </div>
      {active && (
        <div className="space-y-1.5">
          <Progress value={run.total ? (100 * run.done) / run.total : 0} aria-label="Progress" />
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
      {run.config.tasks.map((task) => {
        const comparable = task.models
          .map((m) => answerOf(task.column, m)?.columns[0])
          .filter((c) => c !== undefined);
        return (
          <div key={task.id} className="space-y-1.5 pt-1" aria-label={`Task ${task.column}`}>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <h3 className="font-medium">{task.column}</h3>
              <span className="text-xs text-muted-foreground">
                {types?.types.find((t) => t.id === task.type)?.label ?? task.type}
                {task.reason ? " · with explanation" : ""}
              </span>
              {comparable.length > 1 && (
                <Button
                  variant="ghost"
                  size="xs"
                  className="ml-auto text-xs"
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
                  <TableHead className="text-right" title="Rows of the dataset with its answer">
                    Answered
                  </TableHead>
                  <TableHead className="text-right">Failed</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {task.models.map((model) => {
                  const cost = run.costs.find((c) => c.task_id === task.id && c.model === model);
                  const answer = answerOf(task.column, model);
                  return (
                    <TableRow key={model}>
                      <TableCell title={model}>{modelSlug(model)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {answer ? formatNumber(answer.answered) : "—"}
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
            <Collapsible>
              <CollapsibleTrigger
                render={<Button variant="ghost" size="xs" className="px-0 text-xs" />}
              >
                <ChevronDownIcon className="size-3" />
                Prompt
              </CollapsibleTrigger>
              <CollapsibleContent>
                <p className="border-l-2 pl-3 text-sm whitespace-pre-wrap select-text">
                  {task.template}
                </p>
              </CollapsibleContent>
            </Collapsible>
          </div>
        );
      })}
      <Collapsible defaultOpen={run.config.sql !== ALL_ROWS}>
        <CollapsibleTrigger render={<Button variant="ghost" size="xs" className="px-0 text-xs" />}>
          <ChevronDownIcon className="size-3" />
          Rows asked about
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="pt-1 font-mono text-xs whitespace-pre-wrap break-all select-text">
            {run.config.sql}
          </pre>
        </CollapsibleContent>
      </Collapsible>
    </section>
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
