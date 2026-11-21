import type { AnswerColumn, Column, Dataset } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";
import type { View } from "@/lib/sql";
import { modelSlug } from "@/lib/tasks";

type Columns = Pick<Dataset, "columns" | "answers">;

// Answer columns the table shows until some are picked. A dataset can have thousands (one per
// option, model and task), too many to read at once or to look at.
const SHOWN_AT_FIRST = 200;

/**
 * What the view hides an answer by, all its columns at once: its first column. One of the file's
 * own columns is hidden by its name.
 */
export function answerKey(answer: AnswerColumn): string {
  return answer.columns[0];
}

/**
 * What the view leaves out of the table: what was hidden in the Display menu or, until something
 * is, the answers beyond the newest ones that fit in `SHOWN_AT_FIRST` columns.
 */
export function hiddenColumns(dataset: Columns, view: View): string[] {
  if (view.hidden) return view.hidden;
  const hidden = [];
  let shown = 0;
  for (const answer of dataset.answers) {
    shown += answer.columns.length;
    // The newest answer always shows, however many columns it has.
    if (shown > SHOWN_AT_FIRST && answer !== dataset.answers[0]) hidden.push(answerKey(answer));
  }
  return hidden;
}

/** The columns the table shows, and the search looks in: all but those the view hides. */
export function shownColumns(dataset: Columns, view: View): Column[] {
  const hidden = new Set(hiddenColumns(dataset, view));
  for (const answer of dataset.answers) {
    if (hidden.has(answerKey(answer))) for (const column of answer.columns) hidden.add(column);
  }
  return dataset.columns.filter((c) => !hidden.has(c.name));
}

/** What the view hides once `key` is shown if it was hidden, or hidden if it was shown. */
export function toggleHidden(dataset: Columns, view: View, key: string): string[] {
  const hidden = hiddenColumns(dataset, view);
  return hidden.includes(key) ? hidden.filter((k) => k !== key) : [...hidden, key];
}

/** What the view hides once `columns` show, e.g. those just compared: `view.hidden` if they do. */
export function revealed(dataset: Columns, view: View, columns: string[]): View["hidden"] {
  const keys = new Set(columns);
  for (const answer of dataset.answers) {
    if (answer.columns.some((c) => keys.has(c))) keys.add(answerKey(answer));
  }
  const hidden = hiddenColumns(dataset, view);
  return hidden.some((k) => keys.has(k)) ? hidden.filter((k) => !keys.has(k)) : view.hidden;
}

/**
 * The columns to show or hide, in groups: answers from models (newest first), labels people set,
 * then the file's own columns. An answer is one choice, whatever it has columns.
 */
export function displayGroups(
  dataset: Columns,
): { label: string; items: { value: string; label: string; detail?: string }[] }[] {
  const answered = new Set(dataset.answers.flatMap((a) => a.columns));
  const answers = (from: AnswerColumn[]) =>
    from.map((a) => ({
      value: answerKey(a),
      label: a.model ? `${a.name} · ${modelSlug(a.model)}` : a.name,
      detail: a.columns.length > 1 ? `${formatNumber(a.columns.length)} columns` : undefined,
    }));
  return [
    { label: "Answers", items: answers(dataset.answers.filter((a) => a.model)) },
    { label: "Labels", items: answers(dataset.answers.filter((a) => !a.model)) },
    {
      label: "The file's columns",
      items: dataset.columns
        .filter((c) => c.name !== "__row_id" && !answered.has(c.name))
        .map((c) => ({ value: c.name, label: c.name })),
    },
  ];
}
