"use client";

import { createColumnHelper, tableFeatures, useTable } from "@tanstack/react-table";
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CodeIcon,
  ListFilterIcon,
  SearchIcon,
  SlidersHorizontalIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
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
import { Textarea } from "@/components/ui/textarea";
import { api, type Dataset, type QueryResult } from "@/lib/api/client";
import { columnLabel, errorMessage, formatCell, formatNumber } from "@/lib/format";
import type { ColumnFilter, View } from "@/lib/sql";

type Row = Record<string, unknown>;

const ROW_ID = "__row_id";

const features = tableFeatures({});
const helper = createColumnHelper<typeof features, Row>();
const emptyRows: Row[] = [];

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
const opLabel = (op: ColumnFilter["op"]) => OPS.find((o) => o.value === op)?.label;
const takesValue = (op: ColumnFilter["op"]) => op !== "is_null" && op !== "is_not_null";

const PAGE_SIZES = [50, 100, 250, 500].map((n) => ({ value: String(n), label: `${n} rows` }));

/**
 * A dataset's rows, as the view picks them: search, filters, sort and limit, which become `sql`, or SQL
 * written directly. The rows shown here are exactly the rows the next run asks about. Paging is the
 * table's own. `version` changes when the rows themselves do, e.g. as a run fills in its answers, so
 * the page is fetched again.
 */
export function DatasetExplorer({
  dataset,
  view,
  sql,
  onViewChange,
  version,
}: {
  dataset: Dataset;
  view: View;
  sql: string;
  onViewChange: (changes: Partial<View>) => void;
  version?: number;
}) {
  const { search, filters } = view;
  const custom = view.sql !== null;
  const sort = view.sort[0] ?? null;
  const [searchInput, setSearchInput] = useState(search);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(100);

  function changeView(changes: Partial<View>) {
    onViewChange(changes);
    setPage(0);
  }

  // Each result remembers the request it answers, so a stale response is never shown as current.
  const request = useMemo(
    () => ({ sql, offset: page * pageSize, limit: pageSize }),
    [sql, page, pageSize],
  );
  const [result, setResult] = useState<{
    request: typeof request;
    data?: QueryResult;
    error?: string;
  }>();

  // Debounce typing in the search box.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput === search) return;
      onViewChange({ search: searchInput });
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput, search, onViewChange]);

  useEffect(() => {
    let current = true;
    api
      .POST("/v1/datasets/{dataset_id}/query", {
        params: { path: { dataset_id: dataset.id } },
        body: request,
      })
      .then(({ data, error }) => {
        if (current) setResult(error ? { request, error: errorMessage(error) } : { request, data });
      });
    return () => {
      current = false;
    };
  }, [dataset.id, request, version]);

  // The last good page stays on screen while the next one loads.
  const [shown, setShown] = useState<QueryResult>();
  if (result?.data && result.data !== shown) setShown(result.data);

  // The query's columns, which SQL can choose or compute.
  const shownColumns = shown?.columns ?? dataset.columns;
  const columns = useMemo(
    () =>
      shownColumns.map((c) =>
        helper.accessor((row) => row[c.name], {
          id: c.name,
          header: columnLabel(c.name),
          cell: (info) => <CellValue value={info.getValue()} />,
        }),
      ),
    [shownColumns],
  );
  const table = useTable({ features, columns, data: shown?.rows ?? emptyRows });

  const loading = result?.request !== request;
  const total = shown?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);

  function toggleSort(column: string) {
    if (sort?.column !== column) changeView({ sort: [{ column, desc: false }] });
    else if (!sort.desc) changeView({ sort: [{ column, desc: true }] });
    else changeView({ sort: [] });
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-b px-3 py-2">
        {custom ? (
          <Badge variant="secondary" className="h-7 gap-1 pr-0.5">
            Custom SQL
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Back to the search, filters and sort"
              title="Back to the search, filters and sort"
              onClick={() => changeView({ sql: null })}
            >
              <XIcon />
            </Button>
          </Badge>
        ) : (
          <>
            <InputGroup className="w-56">
              <InputGroupAddon>
                <SearchIcon />
              </InputGroupAddon>
              <InputGroupInput
                id="rows-search"
                placeholder="Search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
              />
            </InputGroup>
            <FilterButton
              dataset={dataset}
              onAdd={(filter) => changeView({ filters: [...filters, filter] })}
            />
            <DisplayButton
              view={view}
              pageSize={pageSize}
              onViewChange={changeView}
              onPageSizeChange={(size) => {
                setPageSize(size);
                setPage(0);
              }}
            />
          </>
        )}
        <SqlButton sql={sql} onApply={(written) => changeView({ sql: written })} />
        {!custom &&
          filters.map((f, i) => (
            <Badge key={i} variant="secondary" className="h-7 gap-1 pr-0.5">
              {"where" in f ? (
                f.label
              ) : (
                <>
                  {columnLabel(f.column)} {opLabel(f.op)}{" "}
                  {takesValue(f.op) && <code>{String(f.value)}</code>}
                </>
              )}
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Remove filter"
                onClick={() => changeView({ filters: filters.filter((_, j) => j !== i) })}
              >
                <XIcon />
              </Button>
            </Badge>
          ))}
        {!custom && view.limit && (
          <Badge variant="secondary" className="h-7 gap-1 pr-0.5">
            First {formatNumber(view.limit)} rows
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Remove limit"
              onClick={() => changeView({ limit: null })}
            >
              <XIcon />
            </Button>
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          {loading && <Spinner />}
          <span>
            {total === 0
              ? "No rows"
              : `${formatNumber(page * pageSize + 1)}–${formatNumber(Math.min(total, (page + 1) * pageSize))} of ${formatNumber(total)}`}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Previous page"
            disabled={page === 0}
            onClick={() => setPage(Math.max(0, page - 1))}
          >
            <ChevronLeftIcon />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Next page"
            disabled={page >= lastPage}
            onClick={() => setPage(Math.min(lastPage, page + 1))}
          >
            <ChevronRightIcon />
          </Button>
        </div>
      </div>

      {result?.error && !loading && (
        <Alert variant="destructive" className="m-3 w-auto">
          <AlertDescription>{result.error}</AlertDescription>
        </Alert>
      )}

      {/* Data is text you may want to copy, unlike the interface around it. */}
      <div className="min-h-0 flex-1 overflow-auto select-text">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id}>
                {group.headers.map((header) => {
                  const column = shownColumns.find((c) => c.name === header.id);
                  const SortIcon =
                    sort?.column !== header.id
                      ? ArrowUpDownIcon
                      : sort.desc
                        ? ArrowDownIcon
                        : ArrowUpIcon;
                  return (
                    <TableHead
                      key={header.id}
                      className="select-none"
                      draggable={header.id !== ROW_ID}
                      onDragStart={(e) => e.dataTransfer.setData("text/plain", `{{${header.id}}}`)}
                    >
                      <Button
                        variant="ghost"
                        size="xs"
                        className="-ml-2"
                        title={column?.type}
                        // Custom SQL sorts itself.
                        disabled={custom}
                        onClick={() => toggleSort(header.id)}
                      >
                        {columnLabel(header.id)}
                        <SortIcon
                          data-icon="inline-end"
                          className={sort?.column !== header.id ? "opacity-30" : undefined}
                        />
                      </Button>
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getAllCells().map((cell) => (
                  <TableCell key={cell.id} className="max-w-80 truncate">
                    <table.FlexRender cell={cell} />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function CellValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground">null</span>;
  }
  const text = formatCell(value);
  return (
    <span title={text} className={typeof value === "object" ? "font-mono text-xs" : undefined}>
      {text}
    </span>
  );
}

function FilterButton({
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
      <PopoverTrigger render={<Button variant="ghost" size="sm" />}>
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
          <Button type="submit" size="sm" disabled={!column}>
            Add filter
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}

/** How the rows are shown: the limit (which the next run keeps to too) and the page size. */
function DisplayButton({
  view,
  pageSize,
  onViewChange,
  onPageSizeChange,
}: {
  view: View;
  pageSize: number;
  onViewChange: (changes: Partial<View>) => void;
  onPageSizeChange: (size: number) => void;
}) {
  const sort = view.sort[0];
  return (
    <Popover>
      <PopoverTrigger render={<Button variant="ghost" size="sm" />}>
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
        </FieldGroup>
      </PopoverContent>
    </Popover>
  );
}

/** The SQL behind the rows shown: to read, or to edit, which replaces the search, filters and sort. */
function SqlButton({ sql, onApply }: { sql: string; onApply: (sql: string) => void }) {
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
      <PopoverTrigger render={<Button variant="ghost" size="sm" />}>
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
          <Button type="submit" size="sm" className="self-end">
            Use this SQL
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}
