"use client";

import { DownloadIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldSeparator,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { api, type Dataset, downloadUrl, type ExportFormat } from "@/lib/api/client";
import { errorMessage, formatBytes } from "@/lib/format";

const FORMATS: { value: ExportFormat; label: string }[] = [
  { value: "csv", label: "CSV" },
  { value: "jsonl", label: "JSONL" },
  { value: "parquet", label: "Parquet" },
];

/** Download a dataset, or write it to a path on the server's machine, in the format picked here. */
export function ExportDataset({
  dataset,
  open,
  onOpenChange,
}: {
  dataset: Dataset;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [includeRowId, setIncludeRowId] = useState(false);
  const [path, setPath] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    const { data, error } = await api.POST("/v1/datasets/{dataset_id}/export", {
      params: { path: { dataset_id: dataset.id } },
      body: { format, path: path.trim(), include_row_id: includeRowId },
    });
    setSaving(false);
    if (error) {
      toast.error(errorMessage(error));
      return;
    }
    toast.success(`Saved ${data.path} (${formatBytes(data.size_bytes)})`);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Export {dataset.name}</DialogTitle>
          <DialogDescription>
            Every row and column. In CSV, nested values are written as JSON.
          </DialogDescription>
        </DialogHeader>
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="export-format">Format</FieldLabel>
            <Select
              items={FORMATS}
              value={format}
              onValueChange={(value) => setFormat(value as ExportFormat)}
            >
              <SelectTrigger id="export-format" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FORMATS.map((f) => (
                  <SelectItem key={f.value} value={f.value}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field orientation="horizontal">
            <Checkbox
              id="export-row-id"
              checked={includeRowId}
              onCheckedChange={(checked) => setIncludeRowId(checked === true)}
            />
            <FieldLabel htmlFor="export-row-id" className="font-normal">
              Include the # column, to trace rows back to the original file
            </FieldLabel>
          </Field>
          <Button
            render={<a href={downloadUrl(dataset.id, format, includeRowId)} download />}
            onClick={() => onOpenChange(false)}
          >
            <DownloadIcon data-icon="inline-start" />
            Download {dataset.name}.{format}
          </Button>
          <FieldSeparator>or</FieldSeparator>
          <Field>
            <FieldLabel htmlFor="export-path">Save to a path on this machine</FieldLabel>
            <div className="flex gap-2">
              <Input
                id="export-path"
                placeholder={`~/Downloads or ~/data/${dataset.name}.${format}`}
                value={path}
                onChange={(e) => setPath(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && path.trim()) save();
                }}
              />
              <Button variant="outline" disabled={!path.trim() || saving} onClick={save}>
                {saving && <Spinner data-icon="inline-start" />}
                Save
              </Button>
            </div>
            <FieldDescription>
              A folder, or a file name. An existing file is replaced.
            </FieldDescription>
          </Field>
        </FieldGroup>
      </DialogContent>
    </Dialog>
  );
}
