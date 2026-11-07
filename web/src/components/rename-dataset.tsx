"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { api, type Dataset } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

export function RenameDataset({
  dataset,
  onClose,
  onSaved,
}: {
  dataset: Dataset;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(dataset.name);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const { error } = await api.PATCH("/v1/datasets/{dataset_id}", {
        params: { path: { dataset_id: dataset.id } },
        body: { name: name.trim() },
      });
      if (error) {
        toast.error(errorMessage(error));
        return;
      }
      onSaved();
      onClose();
    } catch {
      toast.error("Could not reach rowlab.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent>
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <DialogHeader>
            <DialogTitle>Rename dataset</DialogTitle>
            <DialogDescription>
              Give this dataset a name you can recognize. Related datasets keep their names.
            </DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="dataset-name">Name</FieldLabel>
            <Input
              id="dataset-name"
              autoFocus
              maxLength={200}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={saving || !name.trim()}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
