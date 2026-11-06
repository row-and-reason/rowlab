"use client";

import { useCallback, useState } from "react";

import type { Task } from "@/lib/api/client";
import type { View } from "@/lib/sql";

/** What the next run of a dataset will be: which rows (the view) and what to ask (the tasks). */
export type Draft = { view: View; tasks: Task[] };

// Drafts live in this browser only: the server only ever sees runs.
const key = (datasetId: string) => `rowlab.draft.${datasetId}`;

/** A dataset's saved draft, if there is one. */
export function loadDraft(datasetId: string): Draft | undefined {
  const saved = localStorage.getItem(key(datasetId));
  return saved ? (JSON.parse(saved) as Draft) : undefined;
}

/** Save a dataset's draft, e.g. to start from a run's settings. */
export function saveDraft(datasetId: string, draft: Draft): void {
  localStorage.setItem(key(datasetId), JSON.stringify(draft));
}

/**
 * The dataset's draft, saved as it changes. Without a saved one it starts from `initial`; `isNew`
 * says so, for defaults that need more to go on.
 */
export function useDraft(datasetId: string, initial: () => Draft) {
  const [isNew] = useState(() => loadDraft(datasetId) === undefined);
  const [draft, setDraft] = useState<Draft>(() => loadDraft(datasetId) ?? initial());

  const update = useCallback(
    (changes: Partial<Draft> | ((draft: Draft) => Partial<Draft>)) => {
      setDraft((draft) => {
        const next = { ...draft, ...(typeof changes === "function" ? changes(draft) : changes) };
        saveDraft(datasetId, next);
        return next;
      });
    },
    [datasetId],
  );

  return { draft, update, isNew };
}
