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
import { attempts, isActive, resumeLabel } from "@/lib/runs";
import { ALL_ROWS } from "@/lib/sql";
import { modelSlug } from "@/lib/tasks";
import { useEstimate } from "@/lib/use-estimate";

/** Where the dataset came from, and its runs, newest first: what each asked, how it went, its cost.
 * A run resumed is one piece of work with its resumes, shown once with its earlier attempts. */
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
        attempts(runs).map((chain) => (
          <RunSection
            key={chain[0].id}
            dataset={dataset}
            attempts={chain}
            onChanged={onChanged}
            onEdit={() => onEdit(chain[0])}
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
  // Ended by a problem every call would have (a key, a server down), not by failed answers.
  failed: "Interrupted",
  done: "Done",
};

/** A piece of work: its latest attempt, with its earlier ones (`attempts`, latest first). */
function RunSection({
  dataset,
  attempts,
  onChanged,
  onEdit,
  onDeleteAnswers,
}: {
  dataset: Dataset;
  attempts: Run[];
  onChanged: () => void;
  onEdit: () => void;
  onDeleteAnswers: (answer: AnswerColumn) => void;
}) {
  const types = useTaskTypes();
  const router = useRouter();
  const canEdit = useCan("member");
  const [run, ...earlier] = attempts;
  const speed = useSpeed(run);
  const [busy, setBusy] = useState(false);
  const failed = run.costs.reduce((n, c) => n + c.failed, 0);
  const active = isActive(run);
  // What resuming would ask: the answers not got to, and those that failed. Asked again when the
  // dataset's answers change (another run, a delete), as that changes what is missing.
  const resumeEnabled = canEdit && !active && (run.status !== "done" || failed > 0);
  const { estimate, problem } = useEstimate(
    dataset.id,
    run.config.sql,
    run.config.tasks,
    resumeEnabled,
    JSON.stringify(dataset.answers.map((a) => [a.name, a.model, a.answered])),
  );
  const resumable = !active && estimate ? resumeLabel(estimate) : null;
  const spent = attempts.reduce((n, a) => n + a.cost, 0);
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

  // The next attempt: asks only what is still missing, and takes replies already paid for free.
  async function resume() {
    setBusy(true);
    const { error } = await api.POST("/v1/runs/{run_id}/resume", {
      params: { path: { run_id: run.id } },
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
          {earlier.length > 0 && `attempt ${attempts.length} · `}
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
          {canEdit && resumable && (
            <Button
              size="sm"
              variant="ghost"
              title={
                problem ??
                `About ${formatUsd(estimate?.cost ?? 0)}${estimate?.unpriced.length ? " + not priced" : ""}; replies already paid for are free`
              }
              disabled={busy}
              onClick={resume}
            >
              <RotateCcwIcon data-icon="inline-start" />
              {resumable}
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
              <DropdownMenuItem disabled={!canEdit || !resumable || busy} onClick={resume}>
                <RotateCcwIcon />
                {resumable ?? "Continue"}
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
        {run.reused > 0 && (
          <span
            className="text-muted-foreground"
            title="Replies paid for by earlier attempts or runs: free, not asked again."
          >
            {formatNumber(run.reused)} reused
          </span>
        )}
        <span title="By every attempt. Cached answers are free; models without prices aren't counted.">
          {formatUsd(spent)} spent
          {Object.values(run.models ?? {}).some((m) => m.prompt_price === null) && " + not priced"}
        </span>
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
      {resumeEnabled && !resumable && problem && (
        <p className="text-xs text-muted-foreground">Can&apos;t resume it: {problem}</p>
      )}
      {earlier.length > 0 && (
        <ol className="space-y-0.5 text-xs text-muted-foreground" aria-label="Earlier attempts">
          {earlier.map((attempt, i) => (
            <li key={attempt.id} className="flex gap-x-2">
              <span className="shrink-0 tabular-nums" title={formatDate(attempt.created_at)}>
                Attempt {attempts.length - 1 - i} · {STATUS[attempt.status]}{" "}
                {formatAgo(attempt.created_at)} · {formatNumber(attempt.done)} /{" "}
                {formatNumber(attempt.total)} asked ·{" "}
                {formatNumber(attempt.costs.reduce((n, c) => n + c.failed, 0))} failed
              </span>
              {attempt.error && (
                <span className="truncate" title={attempt.error}>
                  · {attempt.error}
                </span>
              )}
            </li>
          ))}
        </ol>
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
                  // Failed: those the latest attempt didn't get, as each asks all earlier failures
                  // again. Cost: every attempt's.
                  const costs = attempts.flatMap((a) =>
                    a.costs.filter((c) => c.task_id === task.id && c.model === model),
                  );
                  const cost = run.costs.find((c) => c.task_id === task.id && c.model === model);
                  const modelSpent = costs.reduce((n, c) => n + c.cost, 0);
                  const answer = answerOf(task.column, model);
                  const unpriced = run.models?.[model]?.prompt_price === null;
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
                        {!costs.length ? "—" : unpriced ? "Not priced" : formatUsd(modelSpent)}
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

/** Calls a second and the time left, from the answers actually asked: replies reused come at
 * once and would make it look faster than it is. */
function useSpeed(
  run: Pick<Run, "id" | "done" | "reused" | "total">,
): { perSecond: number; secondsLeft: number } | undefined {
  const asked = run.done - run.reused;
  const first = useRef<{ runId: string; asked: number; at: number }>(undefined);
  const [speed, setSpeed] = useState<{ perSecond: number; secondsLeft: number }>();
  useEffect(() => {
    const start = first.current;
    if (!start || start.runId !== run.id || asked < start.asked) {
      first.current = { runId: run.id, asked, at: Date.now() };
      setSpeed(undefined);
      return;
    }
    const seconds = (Date.now() - start.at) / 1000;
    if (seconds < 2 || asked <= start.asked) return;
    const perSecond = (asked - start.asked) / seconds;
    setSpeed({ perSecond, secondsLeft: (run.total - run.done) / perSecond });
  }, [run.id, asked, run.done, run.total]);
  return speed;
}
