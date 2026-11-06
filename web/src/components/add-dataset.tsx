"use client";

import { ArrowLeftIcon, CloudIcon, GlobeIcon, UploadIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConnectionSelect } from "@/components/connection-select";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { Spinner } from "@/components/ui/spinner";
import { createDataset, type Dataset } from "@/lib/api/client";
import { errorMessage, formatNumber } from "@/lib/format";

const KINDS = [
  {
    kind: "file",
    label: "Local file",
    title: "Add a local file",
    description: "Upload a file from this computer.",
    icon: UploadIcon,
  },
  {
    kind: "s3",
    label: "S3",
    title: "Add data from S3",
    description: "An object in AWS S3, Cloudflare R2, MinIO or other S3-compatible storage.",
    icon: CloudIcon,
  },
  {
    kind: "web",
    label: "Web",
    title: "Add data from the web",
    description: "A file at a public http(s) URL.",
    icon: GlobeIcon,
  },
] as const;
export type SourceKind = (typeof KINDS)[number]["kind"];

/**
 * Add a dataset in two steps: where it is (this computer, S3 or the web), then which file. `startAt`
 * skips the first step when where is already known.
 */
export function AddDataset({
  open,
  startAt,
  onOpenChange,
  onAdded,
}: {
  open: boolean;
  startAt?: SourceKind;
  onOpenChange: (open: boolean) => void;
  onAdded: (dataset: Dataset) => void;
}) {
  const [kind, setKind] = useState<SourceKind | undefined>(startAt);
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState("");
  const [connectionId, setConnectionId] = useState<string | null>(null);

  // Closing starts over at the first step.
  function changeOpen(next: boolean) {
    onOpenChange(next);
    if (!next) {
      setKind(undefined);
      setSource("");
    }
  }

  async function add(input: { file: File } | { source: string; connectionId?: string | null }) {
    setBusy(true);
    const { data, error } = await createDataset(input);
    setBusy(false);
    if (error) {
      toast.error(errorMessage(error));
      return;
    }
    toast.success(`Loaded ${data.name}: ${formatNumber(data.row_count)} rows`);
    changeOpen(false);
    onAdded(data);
  }

  const picked = KINDS.find((k) => k.kind === kind);
  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-1">
            {picked && (
              <Button
                variant="ghost"
                size="icon-sm"
                className="-ml-2"
                aria-label="Back"
                disabled={busy}
                onClick={() => setKind(undefined)}
              >
                <ArrowLeftIcon />
              </Button>
            )}
            {picked?.title ?? "Add data"}
          </DialogTitle>
          <DialogDescription>
            CSV, TSV, JSON, JSONL or Parquet, optionally gzipped. The format is detected
            automatically.
          </DialogDescription>
        </DialogHeader>

        {!kind && (
          <ItemGroup className="gap-1">
            {KINDS.map((k) => (
              <Item
                key={k.kind}
                variant="outline"
                size="sm"
                render={
                  <button type="button" className="text-left" onClick={() => setKind(k.kind)} />
                }
              >
                <ItemMedia variant="icon">
                  <k.icon />
                </ItemMedia>
                <ItemContent>
                  <ItemTitle>{k.label}</ItemTitle>
                  <ItemDescription>{k.description}</ItemDescription>
                </ItemContent>
              </Item>
            ))}
          </ItemGroup>
        )}

        {kind === "file" && (
          <Field>
            <FieldLabel htmlFor="dataset-file">File</FieldLabel>
            <Input
              id="dataset-file"
              type="file"
              autoFocus
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) add({ file });
              }}
            />
            {busy && (
              <FieldDescription className="flex items-center gap-2">
                <Spinner /> Loading…
              </FieldDescription>
            )}
          </Field>
        )}

        {(kind === "s3" || kind === "web") && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (source.trim()) {
                add({ source: source.trim(), connectionId: kind === "s3" ? connectionId : null });
              }
            }}
          >
            <FieldGroup>
              {kind === "s3" && (
                <ConnectionSelect
                  id="dataset-connection"
                  value={connectionId}
                  onChange={setConnectionId}
                />
              )}
              <Field>
                <FieldLabel htmlFor="dataset-source">{kind === "s3" ? "Object" : "URL"}</FieldLabel>
                <div className="flex gap-2">
                  <Input
                    id="dataset-source"
                    autoFocus
                    placeholder={kind === "s3" ? "s3://bucket/path/data.csv" : "https://…/data.csv"}
                    value={source}
                    disabled={busy}
                    onChange={(e) => setSource(e.target.value)}
                  />
                  <Button type="submit" disabled={busy || !source.trim()}>
                    {busy && <Spinner data-icon="inline-start" />}
                    Load
                  </Button>
                </div>
              </Field>
            </FieldGroup>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
