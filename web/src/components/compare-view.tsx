"use client";

import {
  Columns3Icon,
  GitCompareArrowsIcon,
  PanelRightCloseIcon,
  PanelRightOpenIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef } from "react";

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
import { api, type Dataset } from "@/lib/api/client";
import { columnLabel, formatNumber } from "@/lib/format";
import { ALL_ROWS, type WhereFilter } from "@/lib/sql";
import { useComparison } from "@/lib/use-comparison";

const NO_REFERENCE = "none";
const NUMERIC = /^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|FLOAT|DOUBLE|DECIMAL.*|DATE)$/;

/** Compare the whole dataset. URL-backed setup survives reloads and trips to the underlying rows. */
export function CompareView({
  dataset,
  onFilter,
}: {
  dataset: Dataset;
  onFilter: (filters: WhereFilter[], columns: string[]) => void;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const anchor = useComboboxAnchor();
  const choices = dataset.columns.filter((c) => c.name !== "__row_id");
  const encoded = params.get("compare");
  const columns = useMemo(() => {
    try {
      const parsed: unknown = JSON.parse(encoded ?? "[]");
      return Array.isArray(parsed)
        ? [
            ...new Set(
              parsed.filter(
                (name): name is string =>
                  typeof name === "string" &&
                  dataset.columns.some((c) => c.name === name && name !== "__row_id"),
              ),
            ),
          ]
        : [];
    } catch {
      return [];
    }
  }, [encoded, dataset.columns]);
  const referenceParam = params.get("reference");
  const reference = choices.some((c) => c.name === referenceParam) ? referenceParam : null;
  const tolerance = params.get("tolerance") ?? "";
  const compared = reference ? [...columns, reference] : columns;
  const types = compared.map((name) => choices.find((c) => c.name === name)!.type);
  const numeric = types.length > 0 && types.every((type) => NUMERIC.test(type));
  const dates = types.length > 0 && types.every((type) => type === "DATE");
  const mixed = new Set(types).size > 1 && !numeric;
  const enough = columns.length >= 2 || (columns.length === 1 && !!reference);
  const problem =
    reference && columns.includes(reference)
      ? "The reference must be different from the compared columns."
      : numeric &&
          tolerance !== "" &&
          (!Number.isFinite(Number(tolerance)) || Number(tolerance) < 0)
        ? "Tolerance must be a finite number of zero or more."
        : undefined;
  const request = useMemo(
    () =>
      enough && !problem
        ? {
            sql: ALL_ROWS,
            columns,
            reference,
            tolerance: numeric && tolerance !== "" ? Number(tolerance) : null,
          }
        : undefined,
    [enough, problem, columns, reference, numeric, tolerance],
  );
  const result = useComparison(dataset.id, request, dataset.run?.done);

  function change(next: { columns?: string[]; reference?: string | null; tolerance?: string; focus?: boolean }) {
    const query = new URLSearchParams(params);
    if (next.columns) query.set("compare", JSON.stringify(next.columns));
    if (next.reference !== undefined) {
      if (next.reference) query.set("reference", next.reference);
      else query.delete("reference");
    }
    if (next.tolerance !== undefined) {
      if (next.tolerance) query.set("tolerance", next.tolerance);
      else query.delete("tolerance");
    }
    if (next.focus !== undefined) {
      if (next.focus) query.set("focus", "compare");
      else query.delete("focus");
    }
    router.replace(`/?${query}`, { scroll: false });
  }

  // Defaults from a run must not overwrite a selection made while that request was pending.
  const latestParams = useRef(params);
  useEffect(() => {
    latestParams.current = params;
  }, [params]);
  useEffect(() => {
    if (!dataset.run) return;
    let current = true;
    api
      .GET("/v1/runs/{run_id}", { params: { path: { run_id: dataset.run.id } } })
      .then(({ data }) => {
        if (!current || !data || latestParams.current.has("compare")) return;
        const group = modelGroup(data.columns);
        if (!group.length) return;
        const query = new URLSearchParams(latestParams.current);
        query.set("compare", JSON.stringify(group));
        router.replace(`/?${query}`, { scroll: false });
      })
      .catch(() => {
        /* Manual selection remains available if run defaults cannot load. */
      });
    return () => {
      current = false;
    };
  }, [dataset.run?.id, dataset.run, router]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-card px-3 py-2">
        <Popover>
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
        {numeric && (
          <>
            <Label htmlFor="compare-tolerance" className="text-xs">
              Tolerance{dates ? " (days)" : ""}
            </Label>
            <Input
              id="compare-tolerance"
              className="h-7 w-24"
              type="number"
              min={0}
              step="any"
              placeholder="Exact"
              value={tolerance}
              aria-invalid={!!problem}
              onChange={(e) => change({ tolerance: e.target.value })}
            />
          </>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto text-xs"
          aria-pressed={params.get("focus") === "compare"}
          onClick={() => change({ focus: params.get("focus") !== "compare" })}
        >
          {params.get("focus") === "compare" ? <PanelRightOpenIcon /> : <PanelRightCloseIcon />}
          {params.get("focus") === "compare" ? "Restore run pane" : "Expand comparison"}
        </Button>
        <span className="text-xs text-muted-foreground">
          All {formatNumber(dataset.row_count)} rows
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
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
              key={JSON.stringify(request)}
              dataset={dataset}
              comparison={result.data}
              tolerance={request.tolerance}
              onFilter={onFilter}
            />
          </>
        )}
      </div>
    </div>
  );
}

/** The first task answered by several models, excluding probability/reason output columns. */
function modelGroup(runColumns: string[]): string[] {
  const groups = new Map<string, string[]>();
  for (const column of runColumns.filter((c) => !c.endsWith("_proba") && !c.endsWith("_reason"))) {
    const base = column.split("__")[0];
    groups.set(base, [...(groups.get(base) ?? []), column]);
  }
  return [...groups.values()].find((g) => g.length > 1) ?? [];
}
