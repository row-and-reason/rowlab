"use client";

import { TriangleAlertIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { insertField, KnownFields, PromptEditor, usePromptEditor } from "@/components/prompt-editor";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { api, type Dataset, type RenderResult } from "@/lib/api/client";
import { errorMessage, formatCell, formatNumber } from "@/lib/format";

/** Write a prompt template from the dataset's columns and preview it row by row. */
export function PromptComposer({ dataset }: { dataset: Dataset }) {
  // Kept in the browser until templates are saved as part of a job.
  const storageKey = `rowlab.template.${dataset.id}`;
  const [template, setTemplate] = useState(() => localStorage.getItem(storageKey) ?? "");
  const [rendered, setRendered] = useState(template);
  const [rowId, setRowId] = useState(0);
  const editor = usePromptEditor(template, setTemplate);

  useEffect(() => {
    localStorage.setItem(storageKey, template);
    const timer = setTimeout(() => setRendered(template), 300);
    return () => clearTimeout(timer);
  }, [storageKey, template]);

  // Each result remembers the request it answers, so a stale response is never shown as current.
  const request = useMemo(() => ({ template: rendered, offset: rowId, limit: 1 }), [rendered, rowId]);
  const [result, setResult] = useState<{ request: typeof request; data?: RenderResult; error?: string }>();
  useEffect(() => {
    let current = true;
    api
      .POST("/v1/datasets/{dataset_id}/render", {
        params: { path: { dataset_id: dataset.id } },
        body: request,
      })
      .then(({ data, error }) => {
        if (current) setResult(error ? { request, error: errorMessage(error) } : { request, data });
      });
    return () => {
      current = false;
    };
  }, [dataset.id, request]);

  // The last good result stays on screen while the next one loads.
  const [shown, setShown] = useState<RenderResult>();
  if (result?.data && result.data !== shown) setShown(result.data);
  const loading = result?.request !== request || rendered !== template;
  const known = useMemo(() => (shown ? new Set(shown.fields.map((f) => f.path)) : null), [shown]);
  const row = shown?.rows[0];
  const lastRow = dataset.row_count - 1;

  return (
    <KnownFields value={known}>
      <div className="grid gap-4 @3xl:grid-cols-[minmax(0,1fr)_16rem]">
        <div className="flex min-w-0 flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Prompt</CardTitle>
              <CardDescription>
                Sent once per row, with each column filled in from that row.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <PromptEditor editor={editor} />
              {shown && (
                <p className="text-sm text-muted-foreground">
                  ≈ {formatNumber(Math.round(shown.tokens.avg))} tokens per row (
                  {formatNumber(shown.tokens.min)}–{formatNumber(shown.tokens.max)}) · ≈{" "}
                  {formatNumber(shown.tokens.total_estimate)} tokens for all{" "}
                  {formatNumber(dataset.row_count)} rows
                </p>
              )}
              {result?.error && (
                <Alert variant="destructive">
                  <AlertDescription>{result.error}</AlertDescription>
                </Alert>
              )}
              {shown?.warnings.map((warning) => (
                <Alert key={warning}>
                  <TriangleAlertIcon />
                  <AlertDescription>
                    <Code text={warning} />
                  </AlertDescription>
                </Alert>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Preview</CardTitle>
              <CardDescription>
                Row {formatNumber(rowId)} of {formatNumber(dataset.row_count)}
                {row && ` · ≈ ${formatNumber(row.tokens)} tokens`}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex items-center gap-2">
                <Pagination className="mx-0 w-auto">
                  <PaginationContent>
                    <PaginationItem>
                      <PaginationPrevious
                        href="#"
                        aria-disabled={rowId === 0}
                        className={rowId === 0 ? "pointer-events-none opacity-50" : ""}
                        onClick={(e) => {
                          e.preventDefault();
                          setRowId(Math.max(0, rowId - 1));
                        }}
                      />
                    </PaginationItem>
                    <PaginationItem>
                      <PaginationNext
                        href="#"
                        aria-disabled={rowId >= lastRow}
                        className={rowId >= lastRow ? "pointer-events-none opacity-50" : ""}
                        onClick={(e) => {
                          e.preventDefault();
                          setRowId(Math.min(lastRow, rowId + 1));
                        }}
                      />
                    </PaginationItem>
                  </PaginationContent>
                </Pagination>
                {loading && <Spinner />}
              </div>
              {row && (
                <>
                  <p className="text-sm whitespace-pre-wrap">
                    {row.prompt || <span className="text-muted-foreground">Empty prompt</span>}
                  </p>
                  {Object.keys(row.values).length > 0 && (
                    <Table>
                      <TableBody>
                        {Object.entries(row.values).map(([path, value]) => (
                          <TableRow key={path}>
                            <TableCell className="w-1/3 font-mono text-xs">{path}</TableCell>
                            <TableCell className="max-w-0 truncate" title={formatCell(value)}>
                              {value === null ? (
                                <span className="text-muted-foreground">empty</span>
                              ) : (
                                formatCell(value)
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="self-start">
          <CardHeader>
            <CardTitle>Columns</CardTitle>
            <CardDescription>Click or drag into the prompt.</CardDescription>
          </CardHeader>
          <CardContent>
            {shown ? (
              <Command>
                <CommandInput placeholder="Search columns" />
                <CommandList className="max-h-[32rem]">
                  <CommandEmpty>No matching columns.</CommandEmpty>
                  {shown.fields.map((field) => (
                    <CommandItem
                      key={field.path}
                      value={field.path}
                      draggable
                      onDragStart={(e) => e.dataTransfer.setData("text/plain", `{{${field.path}}}`)}
                      onSelect={() => editor && insertField(editor, field.path)}
                    >
                      <span className="truncate font-mono" title={field.path}>
                        {field.path}
                      </span>
                      <span
                        className="ml-auto max-w-20 shrink-0 truncate text-xs text-muted-foreground"
                        title={field.type}
                      >
                        {field.type}
                      </span>
                    </CommandItem>
                  ))}
                </CommandList>
              </Command>
            ) : (
              <Spinner />
            )}
          </CardContent>
        </Card>
      </div>
    </KnownFields>
  );
}

/** Text with `backticked` parts shown as code, as in the server's warnings. */
function Code({ text }: { text: string }) {
  return text.split("`").map((part, i) => (i % 2 ? <code key={i}>{part}</code> : part));
}
