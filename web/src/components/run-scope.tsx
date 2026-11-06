"use client";

import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatNumber } from "@/lib/format";
import type { View } from "@/lib/sql";

const MODES = [
  { value: "sample", label: "Random sample" },
  { value: "first", label: "First rows in table order" },
  { value: "all", label: "All matching rows" },
];

export function RunScope({
  view,
  onChange,
}: {
  view: View;
  onChange: (changes: Partial<View>) => void;
}) {
  const mode = view.limit === null ? "all" : view.sample ? "sample" : "first";
  const label =
    view.sql !== null
      ? "Custom SQL"
      : mode === "all"
        ? "All matching rows"
        : `${mode === "sample" ? "Sample" : "First"} ${formatNumber(view.limit!)} rows`;
  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" size="sm" />}>
        Scope: {label}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72">
        {view.sql !== null ? (
          <FieldDescription>
            Custom SQL defines the run&apos;s rows. Edit it in the Rows toolbar.
          </FieldDescription>
        ) : (
          <div className="flex flex-col gap-3">
            <Field>
              <FieldLabel htmlFor="run-scope">Rows to process</FieldLabel>
              <Select
                items={MODES}
                value={mode}
                onValueChange={(value) =>
                  onChange({
                    limit: value === "all" ? null : (view.limit ?? 20),
                    sample: value === "sample",
                  })
                }
              >
                <SelectTrigger id="run-scope" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MODES.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            {mode !== "all" && (
              <Field>
                <FieldLabel htmlFor="run-size">
                  {mode === "sample" ? "Sample size" : "Number of rows"}
                </FieldLabel>
                <Input
                  id="run-size"
                  type="number"
                  min={1}
                  step={1}
                  value={view.limit ?? 20}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    if (Number.isInteger(n) && n > 0) onChange({ limit: n });
                  }}
                />
              </Field>
            )}
            <FieldDescription>
              The table shows exactly the rows this run will process. Random samples stay fixed
              while you refine a prompt. Search and filters apply before sampling; page size only
              changes the display.
            </FieldDescription>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
