"use client";

import { ArrowLeftIcon, ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { PaneHeader } from "@/components/pane";
import { TooltipButton } from "@/components/tooltip-button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { api, type Dataset, type QueryResult, type Task } from "@/lib/api/client";
import { columnLabel, errorMessage, formatCell, formatNumber } from "@/lib/format";

export const reviewedColumn = (column: string) => `reviewed_${column.split("__")[0]}`;

export function RowReview({
  dataset,
  sql,
  index,
  version,
  tasks,
  onMove,
  onClose,
  onSaved,
  hidden,
  onHiddenChange,
}: {
  dataset: Dataset;
  sql: string;
  index: number;
  version: number;
  tasks: Task[];
  onMove: (index: number) => void;
  onClose: () => void;
  onSaved: () => void;
  hidden: boolean;
  onHiddenChange: (hidden: boolean) => void;
}) {
  const choices = dataset.columns.filter(
    (c) =>
      c.name !== "__row_id" && !c.name.startsWith("reviewed_") && !/_(proba|reason)$/.test(c.name),
  );
  const [picked, setPicked] = useState<string>();
  const column =
    choices.find((c) => c.name === picked) ??
    choices.find((c) => c.name.includes("__") || /^(model_|answer|prediction)/.test(c.name)) ??
    choices.find((c) => !c.name.endsWith("_id")) ??
    choices[0];
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const request = useMemo(() => ({ sql, index, version, retry }), [sql, index, version, retry]);
  const [result, setResult] = useState<{
    request: typeof request;
    data?: QueryResult;
    error?: string;
  }>();
  useEffect(() => {
    let current = true;
    api
      .POST("/v1/datasets/{dataset_id}/query", {
        params: { path: { dataset_id: dataset.id } },
        body: {
          sql: `SELECT * FROM data WHERE __row_id IN (SELECT __row_id FROM (${sql}) LIMIT 1 OFFSET ${index})`,
          offset: 0,
          limit: 1,
        },
      })
      .then(({ data, error }) => {
        if (current)
          setResult({
            request,
            data,
            error: error ? errorMessage(error) : undefined,
          });
      })
      .catch(() => {
        if (current)
          setResult({
            request,
            error: "Could not load this row. Check your connection and retry.",
          });
      });
    return () => {
      current = false;
    };
  }, [dataset.id, request, sql, index]);
  const row = result?.request === request ? result.data?.rows[0] : undefined;
  const [total, setTotal] = useState<{ sql: string; total: number }>();
  useEffect(() => {
    let current = true;
    api
      .POST("/v1/datasets/{dataset_id}/query", {
        params: { path: { dataset_id: dataset.id } },
        body: { sql, offset: 0, limit: 1 },
      })
      .then(({ data }) => {
        if (current && data) setTotal({ sql, total: data.total });
      })
      .catch(() => {
        if (current) setTotal({ sql, total: 0 });
      });
    return () => {
      current = false;
    };
  }, [dataset.id, sql, retry]);
  const count = total?.sql === sql ? total.total : 0;
  const task = tasks.find(
    (t) => column?.name.startsWith(`${t.column}__`) || column?.name.startsWith(`${t.column}_`),
  );
  const source = dataset.columns.filter(
    (c) => c.name !== "__row_id" && !c.name.includes("__") && !c.name.startsWith("reviewed_"),
  );
  const answers = dataset.columns.filter(
    (c) =>
      c.name !== "__row_id" &&
      c.name.includes("__") &&
      !c.name.startsWith("reviewed_") &&
      !/_(proba|reason)$/.test(c.name),
  );

  return (
    <section
      data-row-review
      className="flex h-full min-h-0 flex-col"
      onKeyDown={(e) => {
        if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
          e.preventDefault();
          if (!busy)
            onMove(Math.max(0, Math.min(count - 1, index + (e.key === "ArrowLeft" ? -1 : 1))));
        }
      }}
    >
      <PaneHeader>
        <TooltipButton
          label="Close row review"
          keys={["Esc"]}
          variant="ghost"
          size="icon-sm"
          onClick={onClose}
        >
          <ArrowLeftIcon />
        </TooltipButton>
        <span className="font-medium">
          Row {formatNumber(index + 1)}
          {count > 0 && ` of ${formatNumber(count)}`}
        </span>
        <div className="ml-auto flex gap-1">
          <TooltipButton
            label="Previous review row"
            keys={["Alt", "←"]}
            variant="ghost"
            size="icon-sm"
            disabled={busy || index === 0}
            onClick={() => onMove(index - 1)}
          >
            <ChevronLeftIcon />
          </TooltipButton>
          <TooltipButton
            label="Next review row"
            keys={["Alt", "→"]}
            variant="ghost"
            size="icon-sm"
            disabled={busy || index >= count - 1}
            onClick={() => onMove(index + 1)}
          >
            <ChevronRightIcon />
          </TooltipButton>
        </div>
      </PaneHeader>
      <div className="min-h-0 flex-1 overflow-auto p-4 select-text">
        {result?.request === request && result.error ? (
          <Alert variant="destructive">
            <AlertDescription>
              {result.error}
              <Button size="sm" variant="outline" onClick={() => setRetry((value) => value + 1)}>
                Retry loading row
              </Button>
            </AlertDescription>
          </Alert>
        ) : result?.request === request && result.data?.rows.length === 0 ? (
          <Alert>
            <AlertDescription>
              No rows to review in this scope.
              <Button size="sm" variant="outline" onClick={onClose}>
                Back to data
              </Button>
            </AlertDescription>
          </Alert>
        ) : !row ? (
          <Spinner />
        ) : (
          <FieldGroup className="gap-5">
            {source.map((c) => (
              <Field key={c.name}>
                <FieldLabel>{columnLabel(c.name)}</FieldLabel>
                <p className="text-sm whitespace-pre-wrap break-words">{formatCell(row[c.name])}</p>
              </Field>
            ))}
            {answers.length > 0 && (
              <>
                <Field orientation="horizontal">
                  <Checkbox
                    id="hide-model-answers"
                    checked={hidden}
                    onCheckedChange={(value) => onHiddenChange(value === true)}
                  />
                  <FieldLabel htmlFor="hide-model-answers">
                    Hide model answers while reviewing
                  </FieldLabel>
                </Field>
                {!hidden &&
                  answers.map((c) => (
                    <Field key={c.name}>
                      <FieldLabel>{c.name}</FieldLabel>
                      <p className="text-sm whitespace-pre-wrap break-words">
                        {formatCell(row[c.name])}
                      </p>
                      {row[`${c.name}_reason`] != null && (
                        <FieldDescription>{formatCell(row[`${c.name}_reason`])}</FieldDescription>
                      )}
                    </Field>
                  ))}
              </>
            )}
            {column && (
              <>
                <Field>
                  <FieldLabel htmlFor="review-answer-column">Answer to review</FieldLabel>
                  <Select
                    items={choices.map((c) => ({
                      value: c.name,
                      label: c.name,
                    }))}
                    value={column.name}
                    onValueChange={(value) => {
                      if (value && !busy) setPicked(value);
                    }}
                  >
                    <SelectTrigger id="review-answer-column" className="w-full" disabled={busy}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {choices.map((c) => (
                        <SelectItem key={c.name} value={c.name}>
                          {c.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <ReviewForm
                  key={`${row.__row_id}:${column.name}:${version}`}
                  dataset={dataset}
                  row={row}
                  column={column.name}
                  type={column.type}
                  task={task}
                  last={index >= count - 1}
                  onBusy={setBusy}
                  onSaved={(next) => {
                    onSaved();
                    if (next && index < count - 1) onMove(index + 1);
                  }}
                />
              </>
            )}
          </FieldGroup>
        )}
      </div>
    </section>
  );
}

function ReviewForm({
  dataset,
  row,
  column,
  type,
  task,
  last,
  onBusy,
  onSaved,
}: {
  dataset: Dataset;
  row: Record<string, unknown>;
  column: string;
  type: string;
  task?: Task;
  last: boolean;
  onBusy: (busy: boolean) => void;
  onSaved: (next: boolean) => void;
}) {
  const name = reviewedColumn(column);
  const initial = row[name];
  const draftKey = `rowlab.review.${dataset.id}.${row.__row_id}.${name}`;
  const [value, setValueState] = useState(
    () => localStorage.getItem(draftKey) ?? (initial == null ? "" : formatCell(initial)),
  );
  function setValue(value: string) {
    setValueState(value);
    localStorage.setItem(draftKey, value);
  }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => {
    document.getElementById("reviewed-value")?.focus({ preventScroll: true });
  }, []);
  const boolean = type === "BOOLEAN";
  const options = boolean
    ? ["true", "false"]
    : task && ["pick_one", "scale"].includes(task.type)
      ? task.options.map((o) => o.name)
      : [];
  async function save(next: boolean, clear = false) {
    let parsed: unknown = clear ? null : value;
    if (!clear && type !== "VARCHAR" && type !== "DATE") {
      try {
        parsed = JSON.parse(value);
      } catch {
        setError('Enter a valid value. Numbers and lists use JSON, for example 3 or ["a", "b"].');
        return;
      }
    }
    setBusy(true);
    onBusy(true);
    setError(undefined);
    try {
      const { error } = await api.PUT("/v1/datasets/{dataset_id}/reviews", {
        params: { path: { dataset_id: dataset.id } },
        body: { row_id: Number(row.__row_id), column, value: parsed },
      });
      if (error) setError(errorMessage(error));
      else {
        localStorage.removeItem(draftKey);
        toast.success("Reviewed label saved", { id: "review-saved" });
        onSaved(next);
      }
    } catch {
      setError(
        "Could not save the label. Your entry is still here; check the connection and retry.",
      );
    } finally {
      setBusy(false);
      onBusy(false);
    }
  }
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void save(!last);
      }}
      onKeyDown={(e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
          e.preventDefault();
          e.stopPropagation();
          if (!busy) void save(!last);
        }
      }}
    >
      <Field>
        <FieldLabel htmlFor="reviewed-value">Reviewed label</FieldLabel>
        {options.length ? (
          <Select
            items={options.map((v) => ({
              value: v,
              label: boolean ? (v === "true" ? "Yes" : "No") : v,
            }))}
            value={value || null}
            onValueChange={(v) => setValue(v ?? "")}
          >
            <SelectTrigger id="reviewed-value" className="w-full" disabled={busy}>
              <SelectValue placeholder="Choose your label" />
            </SelectTrigger>
            <SelectContent>
              {options.map((v) => (
                <SelectItem key={v} value={v}>
                  {boolean ? (v === "true" ? "Yes" : "No") : v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : type === "VARCHAR" || type.endsWith("[]") || type.startsWith("STRUCT") ? (
          <Textarea
            id="reviewed-value"
            value={value}
            disabled={busy}
            onChange={(e) => setValue(e.target.value)}
          />
        ) : (
          <Input
            id="reviewed-value"
            value={value}
            disabled={busy}
            onChange={(e) => setValue(e.target.value)}
          />
        )}
        <FieldDescription>
          Saved in {name}. Original answers stay unchanged. Use this column as the reference in
          Compare.
        </FieldDescription>
      </Field>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap gap-2">
        <TooltipButton
          label={last ? "Save reviewed label" : "Save and review next row"}
          keys={["⌘", "↵"]}
          type="submit"
          size="sm"
          disabled={busy || !value}
        >
          {busy && <Spinner />}
          {last ? "Save label" : "Save & next"}
        </TooltipButton>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy || !value}
          onClick={() => void save(false)}
        >
          Save & stay
        </Button>
        {initial != null && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => void save(false, true)}
          >
            Clear label
          </Button>
        )}
      </div>
    </form>
  );
}
