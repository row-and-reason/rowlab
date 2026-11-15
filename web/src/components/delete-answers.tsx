"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Spinner } from "@/components/ui/spinner";
import { api, type AnswerColumn } from "@/lib/api/client";
import { errorMessage, formatNumber } from "@/lib/format";
import { modelSlug } from "@/lib/tasks";

/** What an answer column is called in menus: "fallacy from jev-1.14", or "labels in gold". */
export function answerLabel(answer: AnswerColumn): string {
  return answer.model ? `${answer.name} from ${modelSlug(answer.model)}` : `labels in ${answer.name}`;
}

/** Confirm, then delete a task's answers from a model, or a label column. */
export function DeleteAnswers({
  datasetId,
  answer,
  onClose,
  onDeleted,
}: {
  datasetId: string;
  answer: AnswerColumn | undefined;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [deleting, setDeleting] = useState(false);

  async function remove() {
    if (!answer) return;
    setDeleting(true);
    const { error } = await api.DELETE("/v1/datasets/{dataset_id}/answers", {
      params: {
        path: { dataset_id: datasetId },
        query: { column: answer.name, model: answer.model ?? undefined },
      },
    });
    setDeleting(false);
    if (error) toast.error(errorMessage(error));
    else toast.success(`Deleted ${answerLabel(answer)}`);
    onClose();
    onDeleted();
  }

  return (
    <AlertDialog open={!!answer} onOpenChange={(open) => !open && !deleting && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {answer && answerLabel(answer)}?</AlertDialogTitle>
          <AlertDialogDescription>
            {answer?.model
              ? `Its ${formatNumber(answer.answered)} answers leave the dataset. Model replies are kept, so asking the same again is free.`
              : `Its ${formatNumber(answer?.answered ?? 0)} labels are deleted for good.`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" disabled={deleting} onClick={remove}>
            {deleting && <Spinner />}
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
