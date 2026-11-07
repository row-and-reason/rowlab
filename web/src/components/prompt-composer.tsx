"use client";

import { ChevronLeftIcon, ChevronRightIcon, TriangleAlertIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { KnownFields, PromptEditor, usePromptEditor } from "@/components/prompt-editor";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { api, type Dataset, type RenderResult } from "@/lib/api/client";
import { errorMessage, formatNumber } from "@/lib/format";

/** A task's prompt, with the row's columns in it, previewed as sent for each row the query picks. */
export function PromptComposer({
  dataset,
  sql,
  template,
  onChange,
}: {
  dataset: Dataset;
  sql: string;
  template: string;
  onChange: (template: string) => void;
}) {
  const [rendered, setRendered] = useState(template);
  // Position within the query's rows, reset when the query changes.
  const [position, setPosition] = useState({ sql, index: 0 });
  const index = position.sql === sql ? position.index : 0;
  const setIndex = (index: number) => setPosition({ sql, index });
  const editor = usePromptEditor(template, onChange);

  useEffect(() => {
    const timer = setTimeout(() => setRendered(template), 300);
    return () => clearTimeout(timer);
  }, [template]);

  // Each result remembers the request it answers, so a stale response is never shown as current.
  const request = useMemo(
    () => ({ template: rendered, sql, offset: index, limit: 1 }),
    [rendered, sql, index],
  );
  const [result, setResult] = useState<{
    request: typeof request;
    data?: RenderResult;
    error?: string;
  }>();
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
  const lastIndex = Math.max(0, (shown?.selected_rows ?? 1) - 1);

  return (
    <KnownFields value={known}>
      <Field>
        <FieldLabel>Prompt</FieldLabel>
        <PromptEditor editor={editor} />
        <FieldDescription className="text-xs">
          Drag a column into the prompt, or type{" "}
          {"{{column}}"}.
          {shown && template &&
            ` ≈ ${formatNumber(Math.round(shown.tokens.avg))} tokens/row · ${formatNumber(shown.tokens.total_estimate)} total.`}
        </FieldDescription>
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
      </Field>

      {row && (
        <Field>
          <div className="flex items-center justify-between gap-2">
            <FieldLabel>
              Preview · row {formatNumber(index + 1)} of {formatNumber(shown?.selected_rows ?? 0)}
            </FieldLabel>
            <div className="flex items-center gap-1">
              {loading && <Spinner />}
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Previous row"
                disabled={index === 0}
                onClick={() => setIndex(Math.max(0, index - 1))}
              >
                <ChevronLeftIcon />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Next row"
                disabled={index >= lastIndex}
                onClick={() => setIndex(Math.min(lastIndex, index + 1))}
              >
                <ChevronRightIcon />
              </Button>
            </div>
          </div>
          <p className="rounded-lg bg-muted p-3 text-sm whitespace-pre-wrap">
            {row.prompt || <span className="text-muted-foreground">Your prompt preview will appear here.</span>}
          </p>
        </Field>
      )}
    </KnownFields>
  );
}

/** Text with `backticked` parts shown as code, as in the server's warnings. */
function Code({ text }: { text: string }) {
  return text.split("`").map((part, i) => (i % 2 ? <code key={i}>{part}</code> : part));
}
