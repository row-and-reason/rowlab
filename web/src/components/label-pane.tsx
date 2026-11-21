"use client";

import { ChevronLeftIcon, ChevronRightIcon, PlusIcon } from "lucide-react";

import { LabelAnswer } from "@/components/label-answer";
import { TooltipButton } from "@/components/tooltip-button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import type { AnswerColumn, Dataset, Task } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";
import { useLabelling } from "@/lib/use-labelling";

const NEW_COLUMN = "\u0000new";

/**
 * Labelling by hand, one row of the view at a time, into a label column: one the dataset has, or a
 * new one, whose task `editor` sets until its first label is saved. Labels stay editable.
 */
export function LabelPane({
  dataset,
  task,
  isNew,
  editor,
  onPickColumn,
  onNewColumn,
  sql,
  position,
  onPosition,
  onChanged,
  canEdit,
}: {
  dataset: Dataset;
  task: Task;
  isNew: boolean;
  editor: React.ReactNode;
  onPickColumn: (answer: AnswerColumn) => void;
  onNewColumn: () => void;
  sql: string;
  position: number;
  onPosition: (position: number) => void;
  onChanged: () => void;
  canEdit: boolean;
}) {
  const labelColumns = dataset.answers.filter((a) => a.model === null);
  const { item, loading, error, saving, saved, pending, disabled, move, save } = useLabelling({
    datasetId: dataset.id,
    task,
    columns: labelColumns.find((a) => a.name === task.column)?.columns ?? [],
    isNew,
    sql,
    position,
    onPosition,
    onChanged,
    canEdit,
  });
  const answered = labelColumns.find((a) => a.name === task.column)?.answered ?? 0;
  const names = [...labelColumns.map((a) => a.name), ...(isNew ? [task.column] : [])];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b p-2">
        <Select
          value={task.column}
          items={[
            ...names.map((name) => ({ value: name, label: name || "Untitled column" })),
            { value: NEW_COLUMN, label: "New label column" },
          ]}
          onValueChange={(name) => {
            if (name === NEW_COLUMN) onNewColumn();
            else {
              const answer = labelColumns.find((a) => a.name === name);
              if (answer) onPickColumn(answer);
            }
          }}
          disabled={saving || !!pending}
        >
          <SelectTrigger size="sm" aria-label="Label column">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {names.map((name) => (
              <SelectItem key={name} value={name}>
                {name || "Untitled column"}
              </SelectItem>
            ))}
            <SelectSeparator />
            <SelectItem value={NEW_COLUMN}>
              <PlusIcon />
              New label column
            </SelectItem>
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">
          {isNew ? "New: its first label saves it" : `${formatNumber(answered)} labelled`}
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-auto">
        {isNew && <div className="@container border-b">{editor}</div>}
        <div className="flex flex-col gap-3 p-3">
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
          ) : item ? (
            <>
              <span className="text-xs text-muted-foreground">
                Row {String(item.row.__row_id)} · {task.column}
              </span>
              {item.prompt && (
                <div className="whitespace-pre-wrap text-sm select-text">{item.prompt}</div>
              )}
              <LabelAnswer
                // Typing a new column's name must not remount it, and take the focus.
                key={`${isNew ? "" : task.column}:${task.type}:${item.row.__row_id}:${JSON.stringify(item.row)}`}
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
                No more rows in this selection. Change the search or filters to label others.
              </p>
            )
          )}
        </div>
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
    </div>
  );
}
