"use client";

import {
  ChevronDownIcon,
  Columns3Icon,
  GitCompareArrowsIcon,
  SlidersHorizontalIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ComparisonResults } from "@/components/comparison-results";
import { PickList } from "@/components/pick-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
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
import { Spinner } from "@/components/ui/spinner";
import type { Dataset } from "@/lib/api/client";
import { columnGroups, comparisonSetup, type InspectRows } from "@/lib/comparison";
import { columnLabel } from "@/lib/format";
import { useComparison, type ComparisonActions } from "@/lib/use-comparison";
import { useComparisonUrl, useDefaultColumns, useSameColumns } from "@/lib/use-comparison-url";

// Not a column name: a column can be called "none".
const NO_REFERENCE = "\u0000none";

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
  const [referenceOpen, setReferenceOpen] = useState(false);
  useEffect(() => {
    actionsRef.current = {
      ...actionsRef.current,
      rules: () => setRulesOpen(true),
      columns: () => setColumnsOpen(true),
    };
    return () => {
      actionsRef.current = {
        ...actionsRef.current,
        rules: undefined,
        columns: undefined,
        clear: undefined,
      };
    };
  }, [actionsRef]);
  const datasetColumns = useSameColumns(dataset.columns);
  const { columns, reference, tolerance, ignoreCase, trimWhitespace, rows, change, urlChanged } =
    useComparisonUrl(datasetColumns);
  const { numeric, text, dates, mixed, problem, request } = useMemo(
    () =>
      comparisonSetup(
        { columns, reference, tolerance, ignoreCase, trimWhitespace, rows },
        datasetColumns,
      ),
    [columns, reference, tolerance, ignoreCase, trimWhitespace, rows, datasetColumns],
  );
  const result = useComparison(dataset.id, request, version);
  useDefaultColumns(dataset.answers);
  useEffect(() => {
    actionsRef.current = { ...actionsRef.current, clear: () => change({ columns: [] }) };
  }, [actionsRef, change]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-card px-3 py-2">
        <Popover open={columnsOpen} onOpenChange={setColumnsOpen}>
          <PopoverTrigger render={<Button variant="outline" size="sm" className="text-xs" />}>
            <Columns3Icon data-icon="inline-start" /> Columns
            {columns.length ? ` · ${columns.length}` : "…"}
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80 p-1">
            <PickList
              // The compared columns first, so they're found to untick in a wide dataset.
              groups={[
                {
                  label: "Compared",
                  items: columns.map((name) => ({ value: name, label: name })),
                },
                ...columnGroups(dataset, [reference, ...columns]),
              ]}
              picked={columns}
              onPick={(name) =>
                change({
                  columns: columns.includes(name)
                    ? columns.filter((c) => c !== name)
                    : [...columns, name],
                })
              }
              placeholder="Find a column…"
              empty="No matching columns."
            />
            <div className="flex items-center gap-2 px-2 pb-1">
              <p className="flex-1 text-xs text-muted-foreground">
                Pick two columns, or one and a reference.
              </p>
              <Button
                variant="ghost"
                size="xs"
                disabled={!columns.length}
                onClick={() => change({ columns: [] })}
              >
                Clear
              </Button>
            </div>
          </PopoverContent>
        </Popover>
        <Popover open={referenceOpen} onOpenChange={setReferenceOpen}>
          <PopoverTrigger
            render={<Button variant="outline" size="sm" className="max-w-56 text-xs" />}
          >
            <span className="truncate">
              {reference ? `Reference · ${columnLabel(reference)}` : "No reference"}
            </span>
            <ChevronDownIcon data-icon="inline-end" />
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80 p-1">
            <PickList
              groups={[
                { label: "", items: [{ value: NO_REFERENCE, label: "No reference" }] },
                ...columnGroups(dataset, columns, { reference: true }),
              ]}
              picked={[reference ?? NO_REFERENCE]}
              onPick={(name) => {
                change({ reference: name === NO_REFERENCE ? null : name });
                setReferenceOpen(false);
              }}
              placeholder="Find a column…"
              empty="No matching columns."
            />
            <p className="px-2 pb-1 text-xs text-muted-foreground">
              Labels you trust, to measure the compared columns against.
            </p>
          </PopoverContent>
        </Popover>
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
            {rows === "pairwise" && " · Pairwise rows"}
          </PopoverTrigger>
          <PopoverContent align="start" className="w-72 space-y-4">
            <Label className="flex items-center gap-2">
              <Checkbox
                checked={rows === "common"}
                onCheckedChange={(v) => change({ rows: v ? "common" : "pairwise" })}
              />
              Only rows every column has
            </Label>
            <p className="text-xs text-muted-foreground">
              So each column is measured on the same rows. Off, each pair uses the rows both of its
              columns have.
            </p>
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
              version={version}
              comparison={result.data}
              rows={rows}
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
