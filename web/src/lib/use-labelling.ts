"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Row, type Task } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

type Answer = { row_id: number; value: unknown };

function rowSql(rowId: unknown) {
  return `SELECT * FROM data WHERE __row_id = ${rowId}`;
}

function positionSql(query: string, rowId: unknown) {
  return `SELECT position FROM (SELECT __row_id, row_number() OVER () - 1 AS position FROM (${query}) selected) numbered WHERE __row_id = ${rowId}`;
}

/**
 * Loads one row of the view at a time and saves its label in the label column `task.column`, with
 * the task itself while the column is `isNew`. Of the row, only the label's own `columns` are
 * read: the prompt shows the rest. `busy` guards against overlapping saves; `pending` holds an
 * answer whose response was lost, so it can be retried as-is.
 */
export function useLabelling({
  datasetId,
  task,
  columns,
  isNew,
  sql,
  position,
  onPosition,
  onChanged,
  canEdit,
}: {
  datasetId: string;
  task: Task;
  columns: string[];
  isNew: boolean;
  sql: string;
  position: number;
  onPosition: (position: number) => void;
  onChanged: () => void;
  canEdit: boolean;
}) {
  const [item, setItem] = useState<{ row: Row; prompt: string; total: number }>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [pending, setPending] = useState<Answer>();
  const busy = useRef(false);
  // Bumped whenever another row is loaded, e.g. one picked in the table while a save or move is
  // under way: their late responses then no longer apply.
  const loads = useRef(0);
  const query = sql.trim().replace(/;\s*$/, "");
  // By value: the dataset is fetched anew as labels are saved, with the same columns.
  const names = JSON.stringify(columns);
  const labelColumns = useMemo(() => JSON.parse(names) as string[], [names]);
  // The prompt shows the row; the rest of the task (options, fields) doesn't change what is loaded.
  const template = task.template;

  useEffect(() => {
    let current = true;
    loads.current += 1;
    async function load() {
      setLoading(true);
      setError(undefined);
      setSaved(false);
      try {
        const { data, error } = await api.POST("/v1/datasets/{dataset_id}/query", {
          params: { path: { dataset_id: datasetId } },
          body: { sql: query, columns: labelColumns, offset: position, limit: 1 },
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
          params: { path: { dataset_id: datasetId } },
          body: { template, sql: rowSql(row.__row_id), offset: 0, limit: 1 },
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
  }, [datasetId, template, query, labelColumns, position, refresh]);

  const move = useCallback(
    async (direction: number, afterSave = false) => {
      if (!afterSave && (busy.current || saving || pending)) return;
      if (!item) {
        onPosition(Math.max(0, position + direction));
        setRefresh((n) => n + 1);
        return;
      }
      // Filters can remove a row after it is labeled. Locate it again before advancing.
      const started = loads.current;
      setLoading(true);
      try {
        const found = await api.POST("/v1/datasets/{dataset_id}/query", {
          params: { path: { dataset_id: datasetId } },
          body: { sql: positionSql(query, item.row.__row_id), offset: 0, limit: 1 },
        });
        if (loads.current !== started) return;
        if (!found.data) throw new Error(errorMessage(found.error));
        const current = found.data.rows[0]?.position;
        const next =
          typeof current === "number" ? current + direction : position + (direction < 0 ? -1 : 0);
        onPosition(Math.max(0, next));
        setRefresh((n) => n + 1);
      } catch (e) {
        if (loads.current === started) setError(errorMessage(e));
      } finally {
        if (loads.current === started) setLoading(false);
      }
    },
    [item, saving, pending, datasetId, query, position, onPosition],
  );

  /** Saves `value` for the current row (null clears it), or resends `retry` exactly. */
  const save = useCallback(
    async (value: unknown, retry?: Answer) => {
      if (!item || busy.current || !canEdit || (pending && !retry)) return;
      const answer = retry ?? { row_id: Number(item.row.__row_id), value };
      const started = loads.current;
      busy.current = true;
      setSaving(true);
      setSaved(false);
      setError(undefined);
      try {
        const result = await api.PUT("/v1/datasets/{dataset_id}/labels/{column}", {
          params: { path: { dataset_id: datasetId, column: task.column } },
          body: { task: isNew ? task : undefined, labels: [answer] },
        });
        if (!result.data) {
          setPending(undefined);
          setError(errorMessage(result.error));
          return;
        }
        setPending(undefined);
        onChanged();
        // Another row was picked meanwhile (or before a retry): the label is saved, that row stays.
        if (loads.current !== started || answer.row_id !== Number(item.row.__row_id)) return;
        setSaved(true);
        if (answer.value !== null) {
          await move(1, true);
          return;
        }
        const updated = await api.POST("/v1/datasets/{dataset_id}/query", {
          params: { path: { dataset_id: datasetId } },
          body: {
            sql: rowSql(answer.row_id),
            columns: labelColumns,
            offset: 0,
            limit: 1,
          },
        });
        if (updated.data?.rows[0] && loads.current === started)
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
    [canEdit, datasetId, isNew, item, labelColumns, move, onChanged, pending, task],
  );

  const disabled = !canEdit || loading || saving || !!pending;
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (
        disabled ||
        e.repeat ||
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

  return {
    item,
    loading,
    error,
    saving,
    saved,
    pending,
    disabled,
    move,
    save,
  };
}
