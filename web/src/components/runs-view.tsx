"use client";

import {
  ChevronDownIcon,
  ChevronRightIcon,
  CircleCheckIcon,
  CircleStopIcon,
  CircleXIcon,
  ClockIcon,
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
import { Spinner } from "@/components/ui/spinner";
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

/** Where the dataset came from, and its runs, newest first, one line each, opened on a click.
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
    <div className="text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b px-3 py-2 text-xs">
        <span className="text-muted-foreground">Imported from</span>
        <span className="break-all select-text">{dataset.source}</span>
        <span className="text-muted-foreground" title={formatDate(dataset.created_at)}>
          {formatAgo(dataset.created_at)} · {formatNumber(dataset.row_count)} rows
        </span>
      </div>
      {runs.length === 0 ? (
        <p className="p-3 text-xs text-muted-foreground">
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

function StatusIcon({ status }: { status: Run["status"] }) {
  if (status === "queued") return <ClockIcon className="size-4 text-muted-foreground" />;
  if (status === "running" || status === "stopping") return <Spinner className="size-4" />;
  if (status === "failed") return <CircleXIcon className="size-4 text-destructive" />;
  if (status === "stopped") return <CircleStopIcon className="size-4 text-muted-foreground" />;
  return <CircleCheckIcon className="size-4 text-muted-foreground" />;
}

/** What a run asked, in a few words: `6 tasks · gpt-6.1-sol · 50 rows`. */
function runSummary(run: Run): string {
  const tasks = run.config.tasks;
  const models = [...new Set(tasks.flatMap((t) => t.models))];
  return [
    tasks.length === 1 ? tasks[0].column : `${tasks.length} tasks`,
    models.length === 1 ? modelSlug(models[0]) : `${models.length} models`,
    `${formatNumber(run.row_count)} rows`,
  ].join(" · ");
}

/** A piece of work, one line: its latest attempt, with its earlier ones (`attempts`, latest
 * first). Opened, a row per task and model, with each task's setup behind its name. */
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
  const [openTasks, setOpenTasks] = useState<string[]>([]);
  const failed = run.costs.reduce((n, c) => n + c.failed, 0);
  const active = isActive(run);
  // From the run's own counts, not an estimate: that reads the whole dataset, too much to ask for
  // every ended run each time answers come in.
  const resumable = resumeLabel(run);
  const spent = attempts.reduce((n, a) => n + a.cost, 0);
  const unpriced = Object.values(run.models ?? {}).some((m) => m.prompt_price === null);
  const answerOf = (column: string, model: string) =>
    dataset.answers.find((a) => a.name === column && a.model === model);
  const deletable = run.config.tasks.flatMap((task) =>
    task.models.map((model) => answerOf(task.column, model)).filter((a) => !!a),
  );
  const comparable = run.config.tasks
    .map((task) => ({
      task,
      columns: task.models
        .map((m) => answerOf(task.column, m)?.columns[0])
        .filter((c) => c !== undefined),
    }))
    .filter((c) => c.columns.length > 1);

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

  function toggleTask(id: string) {
    setOpenTasks((open) => (open.includes(id) ? open.filter((t) => t !== id) : [...open, id]));
  }

  return (
    <Collapsible
      render={<section className="border-b" aria-label={`Run ${run.id}`} />}
    >
      <div className="flex items-center gap-2 px-1 py-1">
        <CollapsibleTrigger
          render={
            <Button
              variant="ghost"
              size="sm"
              className="group h-auto min-w-0 flex-1 justify-start gap-2 py-1.5 font-normal"
            />
          }
        >
          <ChevronRightIcon className="size-3.5 text-muted-foreground transition-transform group-data-[panel-open]:rotate-90" />
          <StatusIcon status={run.status} />
          <span className="w-20 shrink-0 text-left font-medium">{STATUS[run.status]}</span>
          <span className="min-w-0 truncate text-muted-foreground">
            {runSummary(run)}
            {earlier.length > 0 && ` · attempt ${attempts.length}`}
          </span>
          <span className="ml-auto flex shrink-0 items-center gap-4 text-xs tabular-nums">
            {active ? (
              <span className="flex items-center gap-2">
                <Progress
                  className="w-20"
                  value={run.total ? (100 * run.done) / run.total : 0}
                  aria-label="Progress"
                />
                <span className="w-16 text-muted-foreground">
                  {formatNumber(run.done)} / {formatNumber(run.total)}
                </span>
              </span>
            ) : (
              failed > 0 && <span className="text-destructive">{formatNumber(failed)} failed</span>
            )}
            <span
              className="w-14 text-right"
              title="By every attempt. Cached answers are free; models without prices aren't counted."
            >
              {formatUsd(spent)}
              {unpriced && "+"}
            </span>
            <span
              className="w-24 text-right text-muted-foreground"
              title={formatDate(run.created_at)}
            >
              {formatAgo(run.created_at)}
            </span>
          </span>
        </CollapsibleTrigger>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={<Button variant="ghost" size="icon-sm" aria-label="Run actions" />}
          >
            <EllipsisIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            {active && (
              <DropdownMenuItem
                disabled={!canEdit || busy || run.status === "stopping"}
                onClick={stop}
              >
                <SquareIcon />
                Stop
              </DropdownMenuItem>
            )}
            {canEdit && resumable && (
              <DropdownMenuItem
                disabled={busy}
                title="Asks only what is still missing; replies already paid for are free."
                onClick={resume}
              >
                <RotateCcwIcon />
                {resumable}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem disabled={!canEdit} onClick={onEdit}>
              <PencilIcon />
              Edit its tasks
            </DropdownMenuItem>
            {comparable.length > 0 && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  <DropdownMenuLabel>Compare models</DropdownMenuLabel>
                  {comparable.map(({ task, columns }) => (
                    <DropdownMenuItem key={task.id} onClick={() => compare(columns)}>
                      <GitCompareArrowsIcon />
                      <span className="truncate">{task.column}</span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuGroup>
              </>
            )}
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
      <CollapsibleContent className="space-y-2 pr-3 pb-3 pl-9">
        <p className="text-xs text-muted-foreground tabular-nums">
          {formatNumber(run.done)} / {formatNumber(run.total)} answers asked
          {run.reused > 0 && (
            <span title="Replies paid for by earlier attempts or runs: free, not asked again.">
              {" "}
              · {formatNumber(run.reused)} reused
            </span>
          )}
          {active &&
            speed &&
            ` · ${formatNumber(Math.round(speed.perSecond))} calls / second · about ${formatDuration(speed.secondsLeft)} left`}
        </p>
        {run.error && (
          <Alert variant="destructive">
            <AlertDescription>{run.error}</AlertDescription>
          </Alert>
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
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <TableHead>Task</TableHead>
              <TableHead>Model</TableHead>
              <TableHead className="text-right" title="Rows of the dataset with its answer">
                Answered
              </TableHead>
              <TableHead className="text-right">Failed</TableHead>
              <TableHead className="text-right">Cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {run.config.tasks.map((task) => {
              const open = openTasks.includes(task.id);
              return [
                ...task.models.map((model, i) => {
                  // Failed: those the latest attempt didn't get, as each asks all earlier failures
                  // again. Cost: every attempt's.
                  const cost = run.costs.find((c) => c.task_id === task.id && c.model === model);
                  const modelSpent = attempts
                    .flatMap((a) => a.costs.filter((c) => c.task_id === task.id && c.model === model))
                    .reduce((n, c) => n + c.cost, 0);
                  const answer = answerOf(task.column, model);
                  return (
                    <TableRow key={`${task.id}:${model}`} className={i > 0 ? "border-t-0" : ""}>
                      <TableCell>
                        {i === 0 && (
                          <Button
                            variant="ghost"
                            size="xs"
                            className="-ml-2"
                            aria-expanded={open}
                            onClick={() => toggleTask(task.id)}
                          >
                            <ChevronRightIcon
                              className={`size-3 transition-transform ${open ? "rotate-90" : ""}`}
                            />
                            {task.column}
                          </Button>
                        )}
                      </TableCell>
                      <TableCell title={model}>{modelSlug(model)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatNumber(answer?.answered ?? 0)}
                      </TableCell>
                      <TableCell
                        className={`text-right tabular-nums ${cost?.failed ? "text-destructive" : "text-muted-foreground"}`}
                      >
                        {formatNumber(cost?.failed ?? 0)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {run.models?.[model]?.prompt_price === null
                          ? "Not priced"
                          : formatUsd(modelSpent)}
                      </TableCell>
                    </TableRow>
                  );
                }),
                open && (
                  <TableRow key={`${task.id}:details`} className="hover:bg-transparent">
                    <TableCell colSpan={5} className="space-y-1.5 pb-3 pl-6 whitespace-normal">
                      <p className="text-muted-foreground">
                        {types?.types.find((t) => t.id === task.type)?.label ?? task.type}
                        {task.reason ? " · with explanation" : ""}
                      </p>
                      {task.options.length > 0 && (
                        <p className="text-muted-foreground">
                          {task.type === "scale" ? "Levels" : "Options"}:{" "}
                          {task.options.map((o) => o.name).join(", ")}
                        </p>
                      )}
                      {task.fields.length > 0 && (
                        <p className="text-muted-foreground">
                          Fields:{" "}
                          {task.fields
                            .map((f) => `${f.name} (${fieldLabel(f.type, types)})`)
                            .join(", ")}
                        </p>
                      )}
                      <p className="border-l-2 pl-3 text-sm whitespace-pre-wrap select-text">
                        {task.template}
                      </p>
                    </TableCell>
                  </TableRow>
                ),
              ];
            })}
          </TableBody>
        </Table>
        <Collapsible defaultOpen={run.config.sql !== ALL_ROWS}>
          <CollapsibleTrigger render={<Button variant="ghost" size="xs" className="px-0 text-xs" />}>
            <ChevronDownIcon className="size-3" />
            Rows asked about
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="pt-1 font-mono text-xs break-all whitespace-pre-wrap select-text">
              {run.config.sql}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      </CollapsibleContent>
    </Collapsible>
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
