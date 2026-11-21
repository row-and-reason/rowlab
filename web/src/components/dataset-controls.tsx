"use client";

import { ChevronDownIcon, CodeIcon, ListFilterIcon, SlidersHorizontalIcon } from "lucide-react";
import { useState } from "react";

import { PickList } from "@/components/pick-list";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { Dataset } from "@/lib/api/client";
import { displayGroups, hiddenColumns, shownColumns, toggleHidden } from "@/lib/columns";
import { columnLabel, formatNumber } from "@/lib/format";
import type { ColumnFilter, View } from "@/lib/sql";

const OPS: { value: ColumnFilter["op"]; label: string }[] = [
  { value: "eq", label: "=" },
  { value: "ne", label: "≠" },
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
  { value: "contains", label: "contains" },
  { value: "is_null", label: "is null" },
  { value: "is_not_null", label: "is not null" },
];
export const opLabel = (op: ColumnFilter["op"]) => OPS.find((o) => o.value === op)?.label;
export const takesValue = (op: ColumnFilter["op"]) => op !== "is_null" && op !== "is_not_null";

const PAGE_SIZES = [50, 100, 250, 500].map((n) => ({ value: String(n), label: `${n} rows` }));

export function FilterButton({
  dataset,
  onAdd,
}: {
  dataset: Dataset;
  onAdd: (filter: ColumnFilter) => void;
}) {
  const columnItems = dataset.columns.map((c) => ({ value: c.name, label: columnLabel(c.name) }));
  const [open, setOpen] = useState(false);
  const [column, setColumn] = useState<string | null>(null);
  const [op, setOp] = useState<ColumnFilter["op"]>("eq");
  const [value, setValue] = useState("");

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger render={<Button variant="ghost" size="sm" className="text-xs" />}>
        <ListFilterIcon data-icon="inline-start" />
        Filter
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72">
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!column) return;
            onAdd({ column, op, value: takesValue(op) ? value : null });
            setValue("");
            setOpen(false);
          }}
        >
          <Select items={columnItems} value={column} onValueChange={setColumn}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Column" />
            </SelectTrigger>
            <SelectContent>
              {columnItems.map((c) => (
                <SelectItem key={c.value} value={c.value}>
                  {c.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex gap-2">
            <Select items={OPS} value={op} onValueChange={(v) => v && setOp(v)}>
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {OPS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {takesValue(op) && (
              <Input
                placeholder="Value"
                aria-label="Filter value"
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
            )}
          </div>
          <Button type="submit" size="sm" className="text-xs" disabled={!column}>
            Add filter
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}

/**
 * How the rows are shown: the limit (which the next run keeps to too), the page size and the
 * columns.
 */
export function DisplayButton({
  dataset,
  view,
  pageSize,
  onViewChange,
  onPageSizeChange,
}: {
  dataset: Dataset;
  view: View;
  pageSize: number;
  onViewChange: (changes: Partial<View>) => void;
  onPageSizeChange: (size: number) => void;
}) {
  const sort = view.sort[0];
  return (
    <Popover>
      <PopoverTrigger render={<Button variant="ghost" size="sm" className="text-xs" />}>
        <SlidersHorizontalIcon data-icon="inline-start" />
        Display
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72">
        <FieldGroup className="gap-4">
          <Field>
            <FieldLabel htmlFor="rows-limit">Limit</FieldLabel>
            <Input
              id="rows-limit"
              type="number"
              min={1}
              placeholder="No limit"
              value={view.limit ?? ""}
              onChange={(e) =>
                onViewChange({ limit: Number(e.target.value) > 0 ? Number(e.target.value) : null })
              }
            />
            <FieldDescription>
              Only the first rows, in this order. The next run asks about these.
            </FieldDescription>
          </Field>
          <Field>
            <FieldLabel>Order</FieldLabel>
            <div className="flex items-center gap-2 text-sm">
              {sort ? (
                <>
                  <span>
                    {columnLabel(sort.column)}, {sort.desc ? "high to low" : "low to high"}
                  </span>
                  <Button variant="ghost" size="xs" onClick={() => onViewChange({ sort: [] })}>
                    Reset
                  </Button>
                </>
              ) : (
                <span className="text-muted-foreground">
                  File order. Click a column header to sort.
                </span>
              )}
            </div>
          </Field>
          <Field>
            <FieldLabel>Rows per page</FieldLabel>
            <Select
              items={PAGE_SIZES}
              value={String(pageSize)}
              onValueChange={(value) => onPageSizeChange(Number(value))}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAGE_SIZES.map((s) => (
                  <SelectItem key={s.value} value={s.value}>
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel>Columns</FieldLabel>
            <ColumnsButton dataset={dataset} view={view} onViewChange={onViewChange} />
          </Field>
        </FieldGroup>
      </PopoverContent>
    </Popover>
  );
}

/** Which columns the table shows, and the search looks in: an answer's columns go together. */
function ColumnsButton({
  dataset,
  view,
  onViewChange,
}: {
  dataset: Dataset;
  view: View;
  onViewChange: (changes: Partial<View>) => void;
}) {
  const groups = displayGroups(dataset);
  const hidden = hiddenColumns(dataset, view);
  const shown = shownColumns(dataset, view).length;
  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" size="sm" className="justify-between" />}>
        {shown === dataset.columns.length
          ? `All ${formatNumber(shown)}`
          : `${formatNumber(shown)} of ${formatNumber(dataset.columns.length)}`}
        <ChevronDownIcon data-icon="inline-end" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-1">
        <PickList
          groups={groups}
          picked={groups.flatMap((g) => g.items.map((i) => i.value)).filter((k) => !hidden.includes(k))}
          onPick={(key) => onViewChange({ hidden: toggleHidden(dataset, view, key) })}
          placeholder="Find a column…"
          empty="No matching columns."
        />
        <div className="flex items-center gap-2 px-2 pb-1">
          <p className="flex-1 text-xs text-muted-foreground">
            A dataset with many answers shows its newest ones, until you pick.
          </p>
          <Button
            variant="ghost"
            size="xs"
            disabled={!view.hidden}
            onClick={() => onViewChange({ hidden: undefined })}
          >
            Reset
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** The SQL behind the rows shown: to read, or to edit, which replaces the search, filters and sort. */
export function SqlButton({ sql, onApply }: { sql: string; onApply: (sql: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(sql);
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setText(sql);
      }}
    >
      <PopoverTrigger render={<Button variant="ghost" size="sm" className="text-xs" />}>
        <CodeIcon data-icon="inline-start" />
        SQL
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[32rem]">
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            onApply(text);
            setOpen(false);
          }}
        >
          <Field>
            <FieldLabel htmlFor="rows-sql">SQL</FieldLabel>
            <Textarea
              id="rows-sql"
              className="min-h-32 font-mono text-xs"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey))
                  e.currentTarget.form?.requestSubmit();
              }}
            />
            <FieldDescription>
              One DuckDB SELECT over the table <code>data</code>. A run asks about the rows it
              returns, so keep <code>__row_id</code> in them. <code>agree([a, b])</code> and{" "}
              <code>disagree([a, b])</code> compare columns.
            </FieldDescription>
          </Field>
          <Button type="submit" size="sm" className="self-end text-xs">
            Use this SQL
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}
