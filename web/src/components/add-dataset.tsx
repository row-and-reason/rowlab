"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldSeparator } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { createDataset } from "@/lib/api/client";
import { errorMessage, formatNumber } from "@/lib/format";

/** Upload a file, or load one from a path on the server's machine or a public URL. */
export function AddDataset({ onAdded }: { onAdded: () => void }) {
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState("");

  async function add(input: { file: File } | { source: string }) {
    setBusy(true);
    const { data, error } = await createDataset(input);
    setBusy(false);
    if (error) {
      toast.error(errorMessage(error));
      return;
    }
    toast.success(`Loaded ${data.name}: ${formatNumber(data.row_count)} rows`);
    setSource("");
    onAdded();
  }

  return (
    <Card>
      <CardContent>
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="dataset-file">Upload a file</FieldLabel>
            <Input
              id="dataset-file"
              type="file"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) add({ file });
              }}
            />
            <FieldDescription>
              CSV, TSV, JSON, JSONL or Parquet, optionally gzipped. The format is detected
              automatically.
            </FieldDescription>
          </Field>
          <FieldSeparator>or</FieldSeparator>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (source.trim()) add({ source: source.trim() });
            }}
          >
            <Field>
              <FieldLabel htmlFor="dataset-source">Load from a path or URL</FieldLabel>
              <div className="flex gap-2">
                <Input
                  id="dataset-source"
                  placeholder="~/data/customers.csv or https://example.com/data.parquet"
                  value={source}
                  disabled={busy}
                  onChange={(e) => setSource(e.target.value)}
                />
                <Button type="submit" disabled={busy || !source.trim()}>
                  {busy && <Spinner data-icon="inline-start" />}
                  Load
                </Button>
              </div>
              <FieldDescription>
                A path on the machine running rowlab, or a public http(s) URL.
              </FieldDescription>
            </Field>
          </form>
        </FieldGroup>
      </CardContent>
    </Card>
  );
}
