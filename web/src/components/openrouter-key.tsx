"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, type Settings } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";

/** Save an OpenRouter API key, checked with OpenRouter first. */
export function OpenRouterKeyDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (settings: Settings) => void;
}) {
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();

  async function save() {
    setSaving(true);
    setError(undefined);
    const { data, error } = await api.PUT("/v1/settings/openrouter-key", { body: { key } });
    setSaving(false);
    if (error) {
      setError(errorMessage(error));
      return;
    }
    setKey("");
    onOpenChange(false);
    onSaved(data);
    toast.success("OpenRouter key saved");
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>OpenRouter API key</DialogTitle>
          <DialogDescription>
            Used for model calls. Stored on this machine only and never shown again.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (key.trim()) save();
          }}
        >
          <Field data-invalid={!!error}>
            <FieldLabel htmlFor="openrouter-key">API key</FieldLabel>
            <div className="flex gap-2">
              <Input
                id="openrouter-key"
                type="password"
                placeholder="sk-or-v1-…"
                autoComplete="off"
                value={key}
                aria-invalid={!!error}
                onChange={(e) => setKey(e.target.value)}
              />
              <Button type="submit" disabled={saving || !key.trim()}>
                {saving && <Spinner data-icon="inline-start" />}
                Save
              </Button>
            </div>
            {error ? (
              <FieldError>{error}</FieldError>
            ) : (
              <FieldDescription>Checked with OpenRouter before it is saved.</FieldDescription>
            )}
          </Field>
        </form>
      </DialogContent>
    </Dialog>
  );
}
