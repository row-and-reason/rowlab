"use client";

import { ArrowLeftIcon, CloudIcon, DownloadIcon } from "lucide-react";
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
import { ConnectionSelect } from "@/components/connection-select";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { api, type Dataset, downloadUrl, type ExportFormat } from "@/lib/api/client";
import { errorMessage, formatBytes } from "@/lib/format";

const FORMATS: { value: ExportFormat; label: string }[] = [
  { value: "csv", label: "CSV" },
  { value: "jsonl", label: "JSONL" },
  { value: "parquet", label: "Parquet" },
];

const DESTINATIONS = [
  {
    kind: "download",
    label: "Download",
    title: "Download",
    description: "A file in this browser's downloads.",
    icon: DownloadIcon,
  },
  {
    kind: "s3",
    label: "S3",
    title: "Export to S3",
    description: "An object in AWS S3, Cloudflare R2, MinIO or other S3-compatible storage.",
    icon: CloudIcon,
  },
] as const;
type Destination = (typeof DESTINATIONS)[number]["kind"];

/** Export a dataset in two steps: where to (a download or S3), then the format and where exactly. */
export function ExportDataset({
  dataset,
  open,
  onOpenChange,
  sql,
}: {
  dataset: Dataset;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sql?: string;
}) {
  const [destination, setDestination] = useState<Destination>();
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [includeRowId, setIncludeRowId] = useState(false);
  const [path, setPath] = useState("");
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [scope, setScope] = useState("all");
  const [error, setError] = useState<string>();
  const query = scope === "current" ? sql : undefined;

  async function download() {
    setSaving(true);
    setError(undefined);
    try {
      const response = await fetch(downloadUrl(dataset.id, format, includeRowId, query));
      if (!response.ok) {
        setError(errorMessage(await response.json()));
        return;
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${dataset.name}.${format}`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success(`Downloaded ${dataset.name}.${format}`);
      onOpenChange(false);
    } catch {
      setError("Could not download the dataset. Check the connection and try again.");
    } finally {
      setSaving(false);
    }
  }

  async function save() {
    setSaving(true);
    setError(undefined);
    try {
      const { data, error } = await api.POST("/v1/datasets/{dataset_id}/export", {
        params: { path: { dataset_id: dataset.id } },
        body: {
          format,
          path: path.trim(),
          include_row_id: includeRowId,
          connection_id: connectionId,
          sql: query,
        },
      });
      if (error) {
        setError(errorMessage(error));
        return;
      }
      toast.success(`Saved ${data.path} (${formatBytes(data.size_bytes)})`);
      onOpenChange(false);
    } catch {
      setError("Could not export the dataset. Check the connection and try again.");
    } finally {
      setSaving(false);
    }
  }

  const picked = DESTINATIONS.find((d) => d.kind === destination);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-1">
            {picked && (
              <Button
                variant="ghost"
                size="icon-sm"
                className="-ml-2"
                aria-label="Back"
                disabled={saving}
                onClick={() => setDestination(undefined)}
              >
                <ArrowLeftIcon />
              </Button>
            )}
            {picked ? `${picked.title}: ${dataset.name}` : `Export ${dataset.name}`}
          </DialogTitle>
          <DialogDescription>
            Choose the rows to export. All columns, including reviewed labels, are included. In CSV,
            nested values are JSON.
          </DialogDescription>
        </DialogHeader>

        {!destination ? (
          <ItemGroup className="gap-1">
            {DESTINATIONS.map((d) => (
              <Item
                key={d.kind}
                variant="outline"
                size="sm"
                render={
                  <button
                    type="button"
                    className="text-left"
                    onClick={() => setDestination(d.kind)}
                  />
                }
              >
                <ItemMedia variant="icon">
                  <d.icon />
                </ItemMedia>
                <ItemContent>
                  <ItemTitle>{d.label}</ItemTitle>
                  <ItemDescription>{d.description}</ItemDescription>
                </ItemContent>
              </Item>
            ))}
          </ItemGroup>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (destination === "s3" && path.trim()) save();
            }}
          >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="export-scope">Rows</FieldLabel>
                <Select
                  items={[
                    {
                      value: "all",
                      label: `Whole dataset (${dataset.row_count.toLocaleString()} rows)`,
                    },
                    ...(sql
                      ? [
                          {
                            value: "current",
                            label: "Current rows (search, filters and sample)",
                          },
                        ]
                      : []),
                  ]}
                  value={scope}
                  onValueChange={(value) => setScope(value ?? "all")}
                >
                  <SelectTrigger id="export-scope" className="w-full" disabled={saving}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">
                      Whole dataset ({dataset.row_count.toLocaleString()} rows)
                    </SelectItem>
                    {sql && (
                      <SelectItem value="current">
                        Current rows (search, filters and sample)
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </Field>
              {destination === "s3" && (
                <ConnectionSelect
                  id="export-connection"
                  value={connectionId}
                  onChange={setConnectionId}
                />
              )}
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
              {destination === "download" ? (
                <Button type="button" disabled={saving} onClick={() => void download()}>
                  {saving ? <Spinner /> : <DownloadIcon data-icon="inline-start" />}
                  Download {dataset.name}.{format}
                </Button>
              ) : (
                <Field>
                  <FieldLabel htmlFor="export-path">Object</FieldLabel>
                  <div className="flex gap-2">
                    <Input
                      id="export-path"
                      autoFocus
                      placeholder="s3://bucket/folder/"
                      value={path}
                      disabled={saving}
                      onChange={(e) => setPath(e.target.value)}
                    />
                    <Button type="submit" disabled={!path.trim() || saving}>
                      {saving && <Spinner data-icon="inline-start" />}
                      Export
                    </Button>
                  </div>
                  <FieldDescription>
                    End in / for {dataset.name}.{format} in that folder. An existing object is
                    replaced.
                  </FieldDescription>
                </Field>
              )}
            </FieldGroup>
            {error && (
              <Alert variant="destructive" className="mt-3">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
