"use client";

import { Columns3Icon, GitCompareArrowsIcon, SlidersHorizontalIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ComparisonResults } from "@/components/comparison-results";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Combobox,
  ComboboxChip,
  ComboboxChips,
  ComboboxChipsInput,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxItem,
  ComboboxList,
  ComboboxValue,
  useComboboxAnchor,
} from "@/components/ui/combobox";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import type { Dataset } from "@/lib/api/client";
import { comparableColumns, comparisonSetup, type InspectRows } from "@/lib/comparison";
import { columnLabel, formatNumber } from "@/lib/format";
import { useComparison, type ComparisonActions } from "@/lib/use-comparison";
import { useComparisonUrl, useRunDefaultColumns, useSameColumns } from "@/lib/use-comparison-url";

const NO_REFERENCE = "none";

/** Compare the whole dataset. URL-backed setup survives reloads and trips to the underlying rows. */
export function CompareView({
  dataset,
  version,
  onFilter,
  actionsRef,
}: {
  dataset: Dataset;
  /** Changes when answers do, so the comparison is fetched again. */
  version: number;
  actionsRef: React.RefObject<ComparisonActions | null>;
  onFilter: InspectRows;
}) {
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  useEffect(() => {
    actionsRef.current = {
      ...actionsRef.current,
      rules: () => setRulesOpen(true),
      columns: () => setColumnsOpen(true),
    };
    return () => {
      actionsRef.current = { ...actionsRef.current, rules: undefined, columns: undefined };
    };
  }, [actionsRef]);
  const anchor = useComboboxAnchor();
  const datasetColumns = useSameColumns(dataset.columns);
  const choices = comparableColumns(datasetColumns);
  const { columns, reference, tolerance, ignoreCase, trimWhitespace, change, urlChanged } =
    useComparisonUrl(datasetColumns);
  const { numeric, text, dates, mixed, problem, request } = useMemo(
    () =>
      comparisonSetup(
        { columns, reference, tolerance, ignoreCase, trimWhitespace },
        datasetColumns,
      ),
    [columns, reference, tolerance, ignoreCase, trimWhitespace, datasetColumns],
  );
  const result = useComparison(dataset.id, request, version);
  useRunDefaultColumns(dataset.run?.id);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-card px-3 py-2">
        <Popover open={columnsOpen} onOpenChange={setColumnsOpen}>
          <PopoverTrigger render={<Button variant="outline" size="sm" className="text-xs" />}>
            <Columns3Icon data-icon="inline-start" /> Columns
            {columns.length ? ` · ${columns.length}` : "…"}
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80">
            <Label htmlFor="compare-columns">Compared columns</Label>
            <p className="text-xs text-muted-foreground">
              Pick two columns, or one and a reference.
            </p>
            <Combobox
              multiple
              items={choices.filter((c) => c.name !== reference).map((c) => c.name)}
              value={columns}
              onValueChange={(picked: string[], details) => {
                if (details.reason !== "escape-key") change({ columns: picked });
              }}
              itemToStringLabel={columnLabel}
            >
              <ComboboxChips ref={anchor}>
                <ComboboxValue>
                  {(picked: string[]) => (
                    <>
                      {picked.map((name) => (
                        <ComboboxChip key={name}>{columnLabel(name)}</ComboboxChip>
                      ))}
                      <ComboboxChipsInput id="compare-columns" placeholder="Find a column…" />
                    </>
                  )}
                </ComboboxValue>
              </ComboboxChips>
              <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>No matching columns.</ComboboxEmpty>
                <ComboboxList>
                  {(name: string) => (
                    <ComboboxItem key={name} value={name}>
                      {columnLabel(name)}
                    </ComboboxItem>
                  )}
                </ComboboxList>
              </ComboboxContent>
            </Combobox>
          </PopoverContent>
        </Popover>
        <Label htmlFor="compare-reference" className="text-xs">
          Reference
        </Label>
        <Select
          items={[
            { value: NO_REFERENCE, label: "None" },
            ...choices
              .filter((c) => !columns.includes(c.name))
              .map((c) => ({ value: c.name, label: columnLabel(c.name) })),
          ]}
          value={reference ?? NO_REFERENCE}
          onValueChange={(value) => change({ reference: value === NO_REFERENCE ? null : value })}
        >
          <SelectTrigger id="compare-reference" size="sm" className="max-w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_REFERENCE}>None</SelectItem>
            {choices
              .filter((c) => !columns.includes(c.name))
              .map((c) => (
                <SelectItem key={c.name} value={c.name}>
                  {columnLabel(c.name)}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        <Popover open={rulesOpen} onOpenChange={setRulesOpen}>
          <PopoverTrigger render={<Button variant="outline" size="sm" className="text-xs" />}>
            <SlidersHorizontalIcon />{" "}
            {numeric && tolerance !== ""
              ? `Within ${tolerance}${dates ? " days" : ""}`
              : text && (ignoreCase || trimWhitespace)
                ? [ignoreCase && "Ignore case", trimWhitespace && "Trim spaces"]
                    .filter(Boolean)
                    .join(" · ")
                : "Exact match"}
          </PopoverTrigger>
          <PopoverContent align="start" className="w-72 space-y-4">
            <span className="text-sm font-medium">Match rules</span>
            {text ? (
              <>
                <Label className="flex items-center gap-2">
                  <Checkbox
                    checked={ignoreCase}
                    onCheckedChange={(v) => change({ ignore_case: !!v })}
                  />
                  Ignore case
                </Label>
                <Label className="flex items-center gap-2">
                  <Checkbox
                    checked={trimWhitespace}
                    onCheckedChange={(v) => change({ trim_whitespace: !!v })}
                  />
                  Trim surrounding whitespace
                </Label>
                <p className="text-xs text-muted-foreground">
                  Unicode lowercase; ASCII whitespace trimming. Original values stay unchanged.
                  Empty strings count as answers.
                </p>
              </>
            ) : numeric ? (
              <>
                <Label htmlFor="compare-tolerance">Tolerance{dates ? " (days)" : ""}</Label>
                <Input
                  id="compare-tolerance"
                  type="number"
                  min={0}
                  step="any"
                  placeholder="Exact"
                  defaultValue={tolerance}
                  key={tolerance}
                  aria-invalid={!!problem}
                  onBlur={(e) => change({ tolerance: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      change({ tolerance: e.currentTarget.value });
                      e.currentTarget.blur();
                    }
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  Maximum absolute difference. Leave blank for exact matches. Applied on Enter or
                  leaving the field.
                </p>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">
                Text rules require all text columns. Tolerance requires all numbers or all dates.
              </p>
            )}
          </PopoverContent>
        </Popover>
        <span className="ml-auto text-xs text-muted-foreground">
          All {formatNumber(dataset.row_count)} rows
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {problem ? (
          <Alert variant="destructive" className="m-3 w-auto">
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        ) : !request ? (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <GitCompareArrowsIcon />
              </EmptyMedia>
              <EmptyTitle>Compare answers, find differences</EmptyTitle>
              <EmptyDescription>
                Choose columns above to measure agreement. Add a reference to see which labels each
                model misses.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : result.error ? (
          <Alert variant="destructive" className="m-3 w-auto">
            <AlertDescription>{result.error}</AlertDescription>
            <Button size="sm" variant="outline" onClick={result.retry}>
              Retry
            </Button>
          </Alert>
        ) : !result.data ? (
          <div role="status" className="flex items-center gap-2 p-3 text-sm text-muted-foreground">
            <Spinner /> Updating comparison…
          </div>
        ) : (
          <>
            {mixed && (
              <p role="status" className="border-b bg-muted/50 px-3 py-2 text-xs">
                Mixed column types: values are compared as text. Check that these columns represent
                the same thing.
              </p>
            )}
            <ComparisonResults
              actionsRef={actionsRef}
              dataset={dataset}
              comparison={result.data}
              onFilter={(filters, selectedColumns) => {
                // A shortcut can arrive in the same event turn as a rule or selection change.
                if (urlChanged()) return;
                const rules = [
                  request.ignore_case && "ignore case",
                  request.trim_whitespace && "trim whitespace",
                ]
                  .filter(Boolean)
                  .join(" + ");
                onFilter(
                  filters.map((f) => ({
                    ...f,
                    label: rules ? `${f.label ?? "Comparison"} · ${rules}` : f.label,
                  })),
                  selectedColumns,
                );
              }}
            />
          </>
        )}
      </div>
    </div>
  );
}
