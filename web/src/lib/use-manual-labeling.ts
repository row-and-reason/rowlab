"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Row, type Run } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

type Answer = { row_id: number; value: unknown };

function rowSql(rowId: unknown) {
  return `SELECT * FROM data WHERE __row_id = ${rowId}`;
}

function positionSql(query: string, rowId: unknown) {
  return `SELECT position FROM (SELECT __row_id, row_number() OVER () - 1 AS position FROM (${query}) selected) numbered WHERE __row_id = ${rowId}`;
}

/**
 * Loads one row of a manual run at a time and saves its label. `busy` guards against overlapping
 * saves and finishes; `pending` holds an answer whose response was lost, so it can be retried as-is.
 */
export function useManualLabeling({
  runId,
  datasetId,
  sql,
  position,
  onPosition,
  onChanged,
  canEdit,
  finishOpen,
  onFinishOpen,
}: {
  runId: string;
  datasetId: string;
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
  const [pending, setPending] = useState<Answer>();
  const busy = useRef(false);
  // Bumped whenever another row is loaded, e.g. one picked in the table while a save or move is
  // under way: their late responses then no longer apply.
  const loads = useRef(0);
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
    loads.current += 1;
    async function load() {
      setLoading(true);
      setError(undefined);
      setSaved(false);
      try {
        const { data, error } = await api.POST("/v1/datasets/{dataset_id}/query", {
          params: { path: { dataset_id: datasetId } },
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
          params: { path: { dataset_id: datasetId } },
          body: { template: task!.template, sql: rowSql(row.__row_id), offset: 0, limit: 1 },
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
  }, [datasetId, task, query, position, refresh]);

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
      if (!task || !item || busy.current || !canEdit || (pending && !retry)) return;
      const answer = retry ?? { row_id: Number(item.row.__row_id), value };
      const started = loads.current;
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
          body: { sql: rowSql(answer.row_id), offset: 0, limit: 1 },
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
    [canEdit, datasetId, item, move, onChanged, pending, runId, task],
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

  return {
    run,
    task,
    setTaskId,
    item,
    loading,
    error,
    saving,
    saved,
    pending,
    disabled,
    move,
    save,
    finish,
  };
}
