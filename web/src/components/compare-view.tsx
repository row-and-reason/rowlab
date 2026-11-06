"use client";

import { useEffect, useMemo, useState } from "react";

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
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type Comparison, type Dataset, type Filter } from "@/lib/api/client";
import { columnLabel, errorMessage, formatNumber } from "@/lib/format";

const NO_REFERENCE = "none";
const NUMERIC = /^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|FLOAT|DOUBLE|DECIMAL.*|DATE)$/;

/**
 * The Compare tab: how often any two or more columns give the same value in each row, e.g. several
 * models' answers, or a model against labels you already have (the reference). Every count opens the
 * rows behind it in the Rows tab, as a filter.
 */
export function CompareView({
  dataset,
  onFilter,
}: {
  dataset: Dataset;
  onFilter: (filters: Filter[]) => void;
}) {
  const choices = dataset.columns.filter((c) => c.name !== "__row_id");
  const [columns, setColumns] = useState<string[]>([]);
  const [reference, setReference] = useState<string | null>(null);
  const [tolerance, setTolerance] = useState("");
  const anchor = useComboboxAnchor();

  // To start with: the answers of the run that made this dataset, if it asked several models.
  useEffect(() => {
    if (!dataset.run) return;
    api
      .GET("/v1/runs/{run_id}", { params: { path: { run_id: dataset.run.id } } })
      .then(({ data }) => {
        if (data) setColumns((picked) => (picked.length ? picked : modelGroup(data.columns)));
      });
  }, [dataset.run]);

  const types = new Map(dataset.columns.map((c) => [c.name, c.type]));
  const compared = reference ? [...columns, reference] : columns;
  const numeric = compared.length > 0 && compared.every((c) => NUMERIC.test(types.get(c) ?? ""));
  const enough = columns.length >= 2 || (columns.length === 1 && !!reference);
  const request = useMemo(
    () =>
      enough
        ? {
            // Every row: the comparison is of the whole dataset, whatever the Rows tab shows.
            search: "",
            filters: [],
            columns,
            reference,
            tolerance: numeric && tolerance !== "" ? Number(tolerance) : null,
          }
        : undefined,
    [enough, columns, reference, numeric, tolerance],
  );

  const [result, setResult] = useState<{ comparison?: Comparison; error?: string }>();
  useEffect(() => {
    if (!request) return;
    let current = true;
    api
      .POST("/v1/datasets/{dataset_id}/compare", {
        params: { path: { dataset_id: dataset.id } },
        body: request,
      })
      .then(({ data, error }) => {
        if (current) setResult(error ? { error: errorMessage(error) } : { comparison: data });
      });
    return () => {
      current = false;
    };
  }, [dataset.id, request]);

  const comparison = request ? result?.comparison : undefined;
  return (
    <div className="flex flex-col gap-5 p-4">
      <FieldGroup className="gap-3">
        <Field>
          <FieldLabel htmlFor="compare-columns">Columns</FieldLabel>
          <Combobox
            multiple
            items={choices.map((c) => c.name)}
            value={columns}
            onValueChange={(picked: string[], details) => {
              if (details.reason !== "escape-key") setColumns(picked);
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
                    <ComboboxChipsInput
                      id="compare-columns"
                      placeholder={picked.length ? "" : "Pick two or more columns"}
                    />
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
        </Field>
        <div className="flex gap-3">
          <Field className="flex-1">
            <FieldLabel htmlFor="compare-reference">Reference</FieldLabel>
            <Select
              items={[
                { value: NO_REFERENCE, label: "None" },
                ...choices.map((c) => ({ value: c.name, label: columnLabel(c.name) })),
              ]}
              value={reference ?? NO_REFERENCE}
              onValueChange={(value) => setReference(value === NO_REFERENCE ? null : value)}
            >
              <SelectTrigger id="compare-reference" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_REFERENCE}>None</SelectItem>
                {choices.map((c) => (
                  <SelectItem key={c.name} value={c.name}>
                    {columnLabel(c.name)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldDescription>Labels you trust, to measure the others against.</FieldDescription>
          </Field>
          {numeric && (
            <Field className="w-40">
              <FieldLabel htmlFor="compare-tolerance">Tolerance</FieldLabel>
              <Input
                id="compare-tolerance"
                type="number"
                min={0}
                placeholder="Exact"
                value={tolerance}
                onChange={(e) => setTolerance(e.target.value)}
              />
              <FieldDescription>How far apart still counts as the same.</FieldDescription>
            </Field>
          )}
        </div>
      </FieldGroup>

      {!request ? (
        <p className="text-sm text-muted-foreground">
          Pick two or more columns, or one and a reference.
        </p>
      ) : result?.error ? (
        <Alert variant="destructive">
          <AlertDescription>{result.error}</AlertDescription>
        </Alert>
      ) : !comparison ? (
        <Spinner />
      ) : (
        <Results comparison={comparison} onFilter={onFilter} />
      )}
    </div>
  );
}

function Results({
  comparison,
  onFilter,
}: {
  comparison: Comparison;
  onFilter: (filters: Filter[]) => void;
}) {
  const { agreement, columns } = comparison;
  const count = (rows: number, filters?: Filter[]) =>
    filters && rows > 0 ? (
      <Button variant="link" size="xs" className="h-auto p-0" onClick={() => onFilter(filters)}>
        {formatNumber(rows)}
      </Button>
    ) : (
      formatNumber(rows)
    );

  return (
    <div className="flex flex-col gap-5 text-sm">
      <section className="flex flex-col gap-1">
        <h3 className="font-medium">
          {agreement.rate === null
            ? "Nothing to compare yet"
            : `Agree on ${percent(agreement.rate)} of the rows with answers to compare`}
        </h3>
        <p className="text-muted-foreground">
          {count(agreement.all_agree.rows, [agreement.all_agree.filter!])} all agree ·{" "}
          {count(agreement.disagree.rows, [agreement.disagree.filter!])} disagree ·{" "}
          {formatNumber(agreement.partly_answered)} partly answered ·{" "}
          {formatNumber(agreement.not_answered)} not answered, of {formatNumber(comparison.rows)}{" "}
          rows. Click a number to see its rows.
        </p>
      </section>

      {comparison.reference && (
        <section className="flex flex-col gap-1">
          <h3 className="font-medium">Against {columnLabel(columns.at(-1)!)}</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Column</TableHead>
                <TableHead className="text-right">Accuracy</TableHead>
                <TableHead className="text-right">Right</TableHead>
                <TableHead className="text-right">Wrong</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {comparison.reference.map((r) => (
                <TableRow key={r.column}>
                  <TableCell>{columnLabel(r.column)}</TableCell>
                  <TableCell className="text-right">
                    {r.accuracy === null ? "–" : percent(r.accuracy)}
                  </TableCell>
                  <TableCell className="text-right">{formatNumber(r.correct)}</TableCell>
                  <TableCell className="text-right">
                    {count(r.compared - r.correct, [r.wrong])}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      {columns.length > 2 && (
        <section className="flex flex-col gap-1">
          <h3 className="font-medium">Each two</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Columns</TableHead>
                <TableHead className="text-right">Agree</TableHead>
                <TableHead className="text-right">Disagree</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {comparison.pairs.map((p) => (
                <TableRow key={p.columns.join(" ")}>
                  <TableCell>{p.columns.map(columnLabel).join(" · ")}</TableCell>
                  <TableCell className="text-right">
                    {p.rate === null ? "–" : percent(p.rate)}
                  </TableCell>
                  <TableCell className="text-right">
                    {count(p.compared - p.agree, [p.disagree])}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      {comparison.crosstab && comparison.crosstab.length > 0 && (
        <Crosstab comparison={comparison} count={count} />
      )}

      <section className="flex flex-col gap-1">
        <h3 className="font-medium">Values</h3>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Value</TableHead>
              {columns.map((c) => (
                <TableHead key={c} className="text-right">
                  {columnLabel(c)}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {comparison.values.map((v) => (
              <TableRow key={v.value ?? ""}>
                <TableCell className="max-w-60 truncate">
                  {v.value ?? <span className="text-muted-foreground">Others</span>}
                </TableCell>
                {columns.map((c) => (
                  <TableCell key={c} className="text-right">
                    {formatNumber(v.counts[c] ?? 0)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}

/** Two columns: how often each of the first's values goes with each of the second's. */
function Crosstab({
  comparison,
  count,
}: {
  comparison: Comparison;
  count: (rows: number, filters?: Filter[]) => React.ReactNode;
}) {
  const cells = comparison.crosstab!;
  const [a, b] = comparison.columns;
  const across = [...new Set(cells.map((c) => c.values[1]))];
  const down = [...new Set(cells.map((c) => c.values[0]))];
  const cell = new Map(cells.map((c) => [c.values.join("\u0000"), c]));
  return (
    <section className="flex flex-col gap-1">
      <h3 className="font-medium">
        {columnLabel(a)} (rows) against {columnLabel(b)} (columns)
      </h3>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead />
            {across.map((v) => (
              <TableHead key={v} className="max-w-32 truncate text-right">
                {v}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {down.map((row) => (
            <TableRow key={row}>
              <TableCell className="max-w-40 truncate font-medium">{row}</TableCell>
              {across.map((col) => {
                const c = cell.get([row, col].join("\u0000"));
                return (
                  <TableCell
                    key={col}
                    className={col === row ? "text-right" : "bg-muted text-right"}
                  >
                    {c ? count(c.rows, c.filters) : ""}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}

/** The columns of a run's first task that several models answered, e.g. `team__a` and `team__b`. */
function modelGroup(runColumns: string[]): string[] {
  const groups = new Map<string, string[]>();
  for (const column of runColumns) {
    const base = column.split("__")[0];
    groups.set(base, [...(groups.get(base) ?? []), column]);
  }
  return [...groups.values()].find((g) => g.length > 1) ?? [];
}

function percent(share: number): string {
  return `${Math.round(share * 1000) / 10}%`;
}
