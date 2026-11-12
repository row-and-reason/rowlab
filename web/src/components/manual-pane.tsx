"use client";

import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
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
import { ManualAnswer } from "@/components/manual-answer";
import { TooltipButton } from "@/components/tooltip-button";
import type { Dataset } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";
import { useManualLabeling } from "@/lib/use-manual-labeling";

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
  const {
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
  } = useManualLabeling({
    runId,
    datasetId: dataset.id,
    sql,
    position,
    onPosition,
    onChanged,
    canEdit,
    finishOpen,
    onFinishOpen,
  });

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
