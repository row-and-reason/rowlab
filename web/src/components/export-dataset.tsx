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

/**
 * Export a dataset in two steps: where to (a download or S3), then the format and where exactly. With
 * `tableSql`, the query behind the rows the table shows, it can export only those rows.
 */
export function ExportDataset({
  dataset,
  tableSql,
  open,
  onOpenChange,
}: {
  dataset: Dataset;
  tableSql: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [destination, setDestination] = useState<Destination>();
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [includeRowId, setIncludeRowId] = useState(false);
  const [onlyTable, setOnlyTable] = useState(false);
  const sql = onlyTable ? tableSql : null;
  const [path, setPath] = useState("");
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    const { data, error } = await api.POST("/v1/datasets/{dataset_id}/export", {
      params: { path: { dataset_id: dataset.id } },
      body: {
        format,
        path: path.trim(),
        include_row_id: includeRowId,
        sql,
        connection_id: connectionId,
      },
    });
    setSaving(false);
    if (error) {
      toast.error(errorMessage(error));
      return;
    }
    toast.success(`Saved ${data.path} (${formatBytes(data.size_bytes)})`);
    onOpenChange(false);
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
            Every column; every row, or only those the table shows. In CSV, nested values are
            written as JSON.
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
              {tableSql && (
                <Field orientation="horizontal">
                  <Checkbox
                    id="export-only-table"
                    checked={onlyTable}
                    onCheckedChange={(checked) => setOnlyTable(checked === true)}
                  />
                  <FieldLabel htmlFor="export-only-table" className="font-normal">
                    Only the rows the table shows (its search, filters and limit)
                  </FieldLabel>
                </Field>
              )}
              {destination === "download" ? (
                <Button
                  render={<a href={downloadUrl(dataset.id, format, includeRowId, sql)} download />}
                  onClick={() => onOpenChange(false)}
                >
                  <DownloadIcon data-icon="inline-start" />
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
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
