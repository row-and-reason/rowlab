"use client";

import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import { TooltipButton } from "@/components/tooltip-button";
import { api, type Dataset, type Run, type Task } from "@/lib/api/client";
import { errorMessage, formatNumber } from "@/lib/format";

type Row = Record<string, unknown>;

export function ManualPane({
  runId,
  dataset,
  sql,
  position,
  onPosition,
  onChanged,
  canEdit,
  finishOpen,
  onFinishOpen,
}: {
  runId: string;
  dataset: Dataset;
  sql: string;
  position: number;
  onPosition: (position: number) => void;
  onChanged: () => void;
  canEdit: boolean;
  finishOpen: boolean;
  onFinishOpen: (open: boolean) => void;
}) {
  const [run, setRun] = useState<Run>();
  const [taskId, setTaskId] = useState<string>();
  const [item, setItem] = useState<{ row: Row; prompt: string; total: number }>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [pending, setPending] = useState<{ row_id: number; value: unknown }>();
  const busy = useRef(false);
  const task = run?.config.tasks.find((t) => t.id === taskId) ?? run?.config.tasks[0];
  const query = sql.trim().replace(/;\s*$/, "");

  useEffect(() => {
    let current = true;
    api
      .GET("/v1/runs/{run_id}", { params: { path: { run_id: runId } } })
      .then(({ data, error }) => {
        if (!current) return;
        if (data) setRun(data);
        else setError(errorMessage(error));
      })
      .catch((e) => {
        if (current) setError(errorMessage(e));
      });
    return () => {
      current = false;
    };
  }, [runId]);

  useEffect(() => {
    if (!task) return;
    let current = true;
    async function load() {
      setLoading(true);
      setError(undefined);
      setSaved(false);
      try {
        const { data, error } = await api.POST("/v1/datasets/{dataset_id}/query", {
          params: { path: { dataset_id: dataset.id } },
          body: { sql: query, offset: position, limit: 1 },
        });
        if (!current) return;
        if (!data) throw new Error(errorMessage(error));
        const row = data.rows[0];
        if (!row) {
          setItem(undefined);
          return;
        }
        if (!Number.isSafeInteger(row.__row_id))
          throw new Error("Include __row_id in the query to label these rows.");
        const rendered = await api.POST("/v1/datasets/{dataset_id}/render", {
          params: { path: { dataset_id: dataset.id } },
          body: {
            template: task!.template,
            sql: `SELECT * FROM data WHERE __row_id = ${row.__row_id}`,
            offset: 0,
            limit: 1,
          },
        });
        if (!current) return;
        if (!rendered.data) throw new Error(errorMessage(rendered.error));
        setItem({ row, prompt: rendered.data.rows[0]?.prompt ?? "", total: data.total });
      } catch (e) {
        if (current) {
          setItem(undefined);
          setError(errorMessage(e));
        }
      } finally {
        if (current) setLoading(false);
      }
    }
    void load();
    return () => {
      current = false;
    };
  }, [dataset.id, task, query, position, refresh]);

  const move = useCallback(
    async (direction: number, afterSave = false) => {
      if (!afterSave && (busy.current || saving || pending)) return;
      if (!item) {
        onPosition(Math.max(0, position + direction));
        setRefresh((n) => n + 1);
        return;
      }
      // Filters can remove a row after it is labeled. Locate it again before advancing.
      setLoading(true);
      try {
        const found = await api.POST("/v1/datasets/{dataset_id}/query", {
          params: { path: { dataset_id: dataset.id } },
          body: {
            sql: `SELECT position FROM (SELECT __row_id, row_number() OVER () - 1 AS position FROM (${query}) selected) numbered WHERE __row_id = ${item.row.__row_id}`,
            offset: 0,
            limit: 1,
          },
        });
        if (!found.data) throw new Error(errorMessage(found.error));
        const current = found.data.rows[0]?.position;
        const next =
          typeof current === "number" ? current + direction : position + (direction < 0 ? -1 : 0);
        onPosition(Math.max(0, next));
        setRefresh((n) => n + 1);
      } catch (e) {
        setError(errorMessage(e));
      } finally {
        setLoading(false);
      }
    },
    [item, saving, pending, dataset.id, query, position, onPosition],
  );

  const save = useCallback(
    async (value: unknown, retry?: { row_id: number; value: unknown }) => {
      if (!task || !item || busy.current || !canEdit || (pending && !retry)) return;
      const answer = retry ?? { row_id: Number(item.row.__row_id), value };
      busy.current = true;
      setSaving(true);
      setSaved(false);
      setError(undefined);
      try {
        const result = await api.PUT("/v1/runs/{run_id}/tasks/{task_id}/answers", {
          params: { path: { run_id: runId, task_id: task.id } },
          body: { answers: [answer] },
        });
        if (!result.data) {
          setPending(undefined);
          setError(errorMessage(result.error));
          return;
        }
        setRun((current) => ({ ...result.data!, config: current?.config ?? result.data!.config }));
        setPending(undefined);
        setSaved(true);
        onChanged();
        if (answer.value !== null) {
          await move(1, true);
          return;
        }
        const updated = await api.POST("/v1/datasets/{dataset_id}/query", {
          params: { path: { dataset_id: dataset.id } },
          body: {
            sql: `SELECT * FROM data WHERE __row_id = ${answer.row_id}`,
            offset: 0,
            limit: 1,
          },
        });
        if (updated.data?.rows[0])
          setItem((current) => (current ? { ...current, row: updated.data!.rows[0] } : current));
      } catch (e) {
        // A lost response may have saved the label. Retry the same value before continuing.
        setPending(answer);
        setError(errorMessage(e));
      } finally {
        busy.current = false;
        setSaving(false);
      }
    },
    [canEdit, dataset.id, item, move, onChanged, pending, runId, task],
  );

  async function finish() {
    if (busy.current || pending) return;
    busy.current = true;
    setSaving(true);
    setError(undefined);
    try {
      const result = await api.POST("/v1/runs/{run_id}/finish", {
        params: { path: { run_id: runId } },
      });
      if (!result.data) throw new Error(errorMessage(result.error));
      onFinishOpen(false);
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
      onFinishOpen(false);
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }

  const disabled = !canEdit || loading || saving || !!pending || finishOpen;
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (
        disabled ||
        e.repeat ||
        !task ||
        (e.target instanceof HTMLElement &&
          e.target.closest("input, textarea, [contenteditable=true], [role=combobox]")) ||
        e.metaKey ||
        e.ctrlKey ||
        e.altKey
      )
        return;
      if (e.key === "ArrowRight" && item && position < item.total - 1) {
        e.preventDefault();
        void move(1);
      } else if (e.key === "ArrowLeft" && position > 0) {
        e.preventDefault();
        void move(-1);
      } else if (task.type === "yes_no" && ["y", "n"].includes(e.key.toLowerCase())) {
        e.preventDefault();
        void save(e.key.toLowerCase() === "y");
      } else if (
        ["pick_one", "scale"].includes(task.type) &&
        /^[1-9]$/.test(e.key) &&
        task.options[Number(e.key) - 1]
      ) {
        e.preventDefault();
        void save(task.options[Number(e.key) - 1].name);
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [disabled, save, task, move, item, position]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b p-2">
        {run && run.config.tasks.length > 1 && (
          <Select
            value={task?.id}
            items={run.config.tasks.map((t) => ({ value: t.id, label: t.column }))}
            onValueChange={(id) => {
              if (id) setTaskId(id);
            }}
            disabled={saving || !!pending}
          >
            <SelectTrigger size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {run.config.tasks.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.column}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <span className="text-xs text-muted-foreground">
          {formatNumber(run?.done ?? 0)} / {formatNumber(run?.total ?? 0)} labeled
        </span>
        <Button
          size="sm"
          className="ml-auto"
          disabled={!canEdit || saving || !!pending}
          onClick={() => onFinishOpen(true)}
        >
          Finish labeling
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {pending && (
          <Button
            size="sm"
            variant="outline"
            disabled={saving}
            onClick={() => save(pending.value, pending)}
          >
            Retry save
          </Button>
        )}
        {loading ? (
          <Spinner />
        ) : item && task ? (
          <>
            <span className="text-xs text-muted-foreground">
              Row {String(item.row.__row_id)} · {task.column}
            </span>
            <div className="whitespace-pre-wrap text-sm select-text">{item.prompt}</div>
            <ManualAnswer
              key={`${task.id}:${item.row.__row_id}:${JSON.stringify(item.row)}`}
              task={task}
              row={item.row}
              disabled={disabled}
              onSave={save}
            />
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" disabled={disabled} onClick={() => save(null)}>
                Clear label
              </Button>
              <span className="text-xs text-muted-foreground">
                {saving
                  ? "Saving…"
                  : saved
                    ? "Saved"
                    : ["yes_no", "pick_one", "scale"].includes(task.type)
                      ? "Answer to save and move to the next row"
                      : "Submit to save and move to the next row"}
              </span>
            </div>
          </>
        ) : (
          !error && (
            <p className="text-sm text-muted-foreground">
              No more rows in this selection. You can change the filter or finish labeling.
            </p>
          )
        )}
      </div>
      <div className="flex items-center gap-2 border-t p-2">
        <TooltipButton
          label="Previous row"
          keys={["←"]}
          size="sm"
          variant="ghost"
          disabled={disabled || position === 0}
          onClick={() => move(-1)}
        >
          <ChevronLeftIcon />
          Previous
        </TooltipButton>
        <span className="text-xs text-muted-foreground">
          {item ? `${position + 1} / ${formatNumber(item.total)}` : ""}
        </span>
        <TooltipButton
          label="Next row"
          keys={["→"]}
          size="sm"
          variant="outline"
          className="ml-auto"
          disabled={disabled || !item || position >= item.total - 1}
          onClick={() => move(1)}
        >
          Next
          <ChevronRightIcon />
        </TooltipButton>
      </div>
      <AlertDialog
        open={finishOpen}
        onOpenChange={(open) => {
          if (!saving) onFinishOpen(open);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Finish labeling?</AlertDialogTitle>
            <AlertDialogDescription>
              {formatNumber(Math.max(0, (run?.total ?? 0) - (run?.done ?? 0)))} unanswered labels
              will stay empty. The output dataset will be locked, ready to compare, export or use in
              another run.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={saving}>Keep labeling</AlertDialogCancel>
            <AlertDialogAction disabled={saving || !!pending} onClick={finish}>
              {saving && <Spinner />}Finish labeling
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function ManualAnswer({
  task,
  row,
  disabled,
  onSave,
}: {
  task: Task;
  row: Row;
  disabled: boolean;
  onSave: (value: unknown) => void;
}) {
  const current =
    task.type === "extract"
      ? Object.fromEntries(
          task.fields.map((f) => [
            f.name,
            row[task.fields.length === 1 ? task.column : `${task.column}_${f.name}`] ?? null,
          ]),
        )
      : row[task.column];
  const [text, setText] = useState(
    task.type === "extract" ? JSON.stringify(current, null, 2) : String(current ?? ""),
  );
  const [picked, setPicked] = useState(
    task.options.filter((o) => row[`${task.column}_${o.name}`] === true).map((o) => o.name),
  );
  const [error, setError] = useState<string>();
  function submitText() {
    if (disabled) return;
    try {
      const value = task.type === "extract" ? JSON.parse(text) : text;
      setError(undefined);
      onSave(value);
    } catch {
      setError("Enter valid JSON for the task's fields.");
    }
  }
  if (task.type === "yes_no")
    return (
      <div className="flex gap-2">
        {[true, false].map((value) => (
          <TooltipButton
            key={String(value)}
            label={`Label ${value ? "Yes" : "No"}`}
            keys={[value ? "Y" : "N"]}
            size="sm"
            variant={current === value ? "default" : "outline"}
            disabled={disabled}
            onClick={() => onSave(value)}
          >
            {value ? "Yes" : "No"}
          </TooltipButton>
        ))}
      </div>
    );
  if (task.type === "pick_one" || task.type === "scale")
    return (
      <div className="flex flex-col gap-2">
        {task.options.map((o, i) => (
          <TooltipButton
            key={o.name}
            label={o.description || o.name}
            keys={i < 9 ? [String(i + 1)] : undefined}
            size="sm"
            variant={current === o.name ? "default" : "outline"}
            disabled={disabled}
            onClick={() => onSave(o.name)}
          >
            {o.name}
            {o.description && ` · ${o.description}`}
          </TooltipButton>
        ))}
      </div>
    );
  if (task.type === "pick_any")
    return (
      <div className="flex flex-col gap-2">
        {task.options.map((o) => (
          <label key={o.name} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={picked.includes(o.name)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                setPicked(checked ? [...picked, o.name] : picked.filter((p) => p !== o.name))
              }
            />
            {o.name}
            {o.description && ` · ${o.description}`}
          </label>
        ))}
        <Button size="sm" disabled={disabled} onClick={() => onSave(picked)}>
          Save & next
        </Button>
      </div>
    );
  return (
    <div className="flex flex-col gap-2">
      {task.type === "extract" && (
        <p className="text-xs text-muted-foreground">
          Enter JSON:{" "}
          {task.fields
            .map((f) => `${f.name} (${f.type})${f.description ? ": " + f.description : ""}`)
            .join(", ")}
        </p>
      )}
      <Textarea
        aria-label="Label value"
        aria-describedby="manual-submit-hint"
        autoFocus
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && !e.repeat) {
            e.preventDefault();
            e.stopPropagation();
            submitText();
          }
        }}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
      <p id="manual-submit-hint" className="text-xs text-muted-foreground">
        Enter to save & next · Shift+Enter for a new line
      </p>
      <TooltipButton
        label="Save and move to the next row"
        keys={["↵"]}
        size="sm"
        disabled={disabled}
        onClick={submitText}
      >
        Save & next
      </TooltipButton>
    </div>
  );
}
