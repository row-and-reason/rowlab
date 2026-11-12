"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { TooltipButton } from "@/components/tooltip-button";
import type { Task } from "@/lib/api/client";
import type { Row } from "@/lib/api/client";

export function ManualAnswer({
  task,
  row,
  disabled,
  onSave,
}: {
  task: Task;
  row: Row;
  disabled: boolean;
  onSave: (value: unknown) => void;
}) {
  const current =
    task.type === "extract"
      ? Object.fromEntries(
          task.fields.map((f) => [
            f.name,
            row[task.fields.length === 1 ? task.column : `${task.column}_${f.name}`] ?? null,
          ]),
        )
      : row[task.column];
  const [text, setText] = useState(
    task.type === "extract" ? JSON.stringify(current, null, 2) : String(current ?? ""),
  );
  const [picked, setPicked] = useState(
    task.options.filter((o) => row[`${task.column}_${o.name}`] === true).map((o) => o.name),
  );
  const [error, setError] = useState<string>();
  function submitText() {
    if (disabled) return;
    try {
      const value = task.type === "extract" ? JSON.parse(text) : text;
      setError(undefined);
      onSave(value);
    } catch {
      setError("Enter valid JSON for the task's fields.");
    }
  }
  if (task.type === "yes_no")
    return (
      <div className="flex gap-2">
        {[true, false].map((value) => (
          <TooltipButton
            key={String(value)}
            label={`Label ${value ? "Yes" : "No"}`}
            keys={[value ? "Y" : "N"]}
            size="sm"
            variant={current === value ? "default" : "outline"}
            disabled={disabled}
            onClick={() => onSave(value)}
          >
            {value ? "Yes" : "No"}
          </TooltipButton>
        ))}
      </div>
    );
  if (task.type === "pick_one" || task.type === "scale")
    return (
      <div className="flex flex-col gap-2">
        {task.options.map((o, i) => (
          <TooltipButton
            key={o.name}
            label={o.description || o.name}
            keys={i < 9 ? [String(i + 1)] : undefined}
            size="sm"
            variant={current === o.name ? "default" : "outline"}
            disabled={disabled}
            onClick={() => onSave(o.name)}
          >
            {o.name}
            {o.description && ` · ${o.description}`}
          </TooltipButton>
        ))}
      </div>
    );
  if (task.type === "pick_any")
    return (
      <div className="flex flex-col gap-2">
        {task.options.map((o) => (
          <label key={o.name} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={picked.includes(o.name)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                setPicked(checked ? [...picked, o.name] : picked.filter((p) => p !== o.name))
              }
            />
            {o.name}
            {o.description && ` · ${o.description}`}
          </label>
        ))}
        <Button size="sm" disabled={disabled} onClick={() => onSave(picked)}>
          Save & next
        </Button>
      </div>
    );
  return (
    <div className="flex flex-col gap-2">
      {task.type === "extract" && (
        <p className="text-xs text-muted-foreground">
          Enter JSON:{" "}
          {task.fields
            .map((f) => `${f.name} (${f.type})${f.description ? ": " + f.description : ""}`)
            .join(", ")}
        </p>
      )}
      <Textarea
        aria-label="Label value"
        aria-describedby="manual-submit-hint"
        autoFocus
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && !e.repeat) {
            e.preventDefault();
            e.stopPropagation();
            submitText();
          }
        }}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
      <p id="manual-submit-hint" className="text-xs text-muted-foreground">
        Enter to save & next · Shift+Enter for a new line
      </p>
      <TooltipButton
        label="Save and move to the next row"
        keys={["↵"]}
        size="sm"
        disabled={disabled}
        onClick={submitText}
      >
        Save & next
      </TooltipButton>
    </div>
  );
}
