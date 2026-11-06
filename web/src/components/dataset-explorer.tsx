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
  ScanTextIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
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

const PAGE_SIZES = [50, 100, 250, 500].map((n) => ({
  value: String(n),
  label: `${n} rows`,
}));

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
  onReview,
  selectedRow,
  hideAnswers = false,
}: {
  dataset: Dataset;
  view: View;
  sql: string;
  onViewChange: (changes: Partial<View>) => void;
  version?: string;
  onReview: (index: number) => void;
  selectedRow?: number | null;
  hideAnswers?: boolean;
}) {
  const { search, filters } = view;
  const custom = view.sql !== null;
  const sort = view.sort[0] ?? null;
  const [searchInput, setSearchInput] = useState(search);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(100);
  const [wrap, setWrap] = useState(false);
  const [confidence, setConfidence] = useState(false);
  const [editingSql, setEditingSql] = useState(false);
  const [lastGoodSql, setLastGoodSql] = useState<string>();
  const [retry, setRetry] = useState(0);

  function changeView(changes: Partial<View>) {
    onViewChange(changes);
    setPage(0);
  }

  // Each result remembers the request it answers, so a stale response is never shown as current.
  const request = useMemo(
    () => ({ sql, offset: page * pageSize, limit: pageSize, version, retry }),
    [sql, page, pageSize, version, retry],
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
        if (current) {
          setResult(error ? { request, error: errorMessage(error) } : { request, data });
          if (data) setLastGoodSql(sql);
        }
      })
      .catch(() => {
        if (current)
          setResult({
            request,
            error: "Could not reach rowlab. Check that the server is running, then retry.",
          });
      });
    return () => {
      current = false;
    };
  }, [dataset.id, request, version, sql]);

  // Only show rows belonging to this request; failed queries never display old results.
  const shown = result?.request === request ? result.data : undefined;

  // The query's columns, which SQL can choose or compute.
  const shownColumns = shown?.columns ?? dataset.columns;
  const columns = useMemo(
    () =>
      shownColumns
        .filter(
          (c) =>
            (confidence || !c.name.endsWith("_proba")) &&
            (!hideAnswers || c.name === ROW_ID || !c.name.includes("__")),
        )
        .map((c) =>
          helper.accessor((row) => row[c.name], {
            id: c.name,
            header: columnLabel(c.name),
            cell: (info) => <CellValue value={info.getValue()} />,
          }),
        ),
    [shownColumns, confidence, hideAnswers],
  );
  const table = useTable({ features, columns, data: shown?.rows ?? emptyRows });

  const loading = result?.request !== request;
  const total = shown?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
  const queryError = result?.request === request ? result.error : undefined;

  function toggleSort(column: string) {
    if (sort?.column !== column) changeView({ sort: [{ column, desc: false }], sample: false });
    else if (!sort.desc) changeView({ sort: [{ column, desc: true }], sample: false });
    else changeView({ sort: [], sample: false });
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
                aria-label="Search rows"
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
              wrap={wrap}
              onWrapChange={setWrap}
              confidence={confidence}
              onConfidenceChange={setConfidence}
              onViewChange={changeView}
              onPageSizeChange={(size) => {
                setPageSize(size);
                setPage(0);
              }}
            />
          </>
        )}
        <SqlButton
          sql={sql}
          open={editingSql}
          onOpenChange={setEditingSql}
          onApply={(written) => changeView({ sql: written })}
        />
        <Button
          variant="ghost"
          size="sm"
          disabled={!shown?.rows.length || !shown.columns.some((c) => c.name === ROW_ID)}
          onClick={() => onReview(page * pageSize)}
        >
          <ScanTextIcon data-icon="inline-start" /> Review rows
        </Button>
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
            {view.sample ? "Sample" : "First"} {formatNumber(view.limit)} rows
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Remove limit"
              onClick={() => changeView({ limit: null, sample: false })}
            >
              <XIcon />
            </Button>
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          {loading && <Spinner />}
          <span>
            {queryError
              ? "Query failed"
              : loading
                ? "Loading rows…"
                : total === 0
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

      {queryError && (
        <Alert variant="destructive" className="m-3 w-auto">
          <AlertDescription>
            <p>Couldn&apos;t load these rows. No previous results are shown.</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => setEditingSql(true)}>
                Edit SQL
              </Button>
              {lastGoodSql && lastGoodSql !== sql && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => changeView({ sql: lastGoodSql })}
                >
                  Revert to last working query
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={() => setRetry((value) => value + 1)}>
                Retry
              </Button>
            </div>
            <Collapsible>
              <CollapsibleTrigger render={<Button size="xs" variant="ghost" />}>
                Error details
              </CollapsibleTrigger>
              <CollapsibleContent>
                <pre className="text-xs whitespace-pre-wrap break-words select-text">
                  {queryError}
                </pre>
              </CollapsibleContent>
            </Collapsible>
          </AlertDescription>
        </Alert>
      )}

      {!loading && !queryError && shown?.rows.length === 0 && (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>No matching rows</EmptyTitle>
            <EmptyDescription>
              Change the search, filters or query to see more data.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setSearchInput("");
                changeView({ search: "", filters: [], sql: null });
              }}
            >
              Clear search and filters
            </Button>
          </EmptyContent>
        </Empty>
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
              <TableRow
                key={row.id}
                data-state={
                  selectedRow === page * pageSize + Number(row.id) ? "selected" : undefined
                }
                onDoubleClick={() => onReview(page * pageSize + Number(row.id))}
              >
                {row.getAllCells().map((cell) => (
                  <TableCell
                    key={cell.id}
                    className={
                      wrap ? "max-w-80 whitespace-pre-wrap break-words" : "max-w-80 truncate"
                    }
                  >
                    {cell.column.id === ROW_ID ? (
                      <Button
                        size="xs"
                        variant="ghost"
                        aria-label={`Review row ${page * pageSize + Number(row.id) + 1}`}
                        onClick={() => onReview(page * pageSize + Number(row.id))}
                      >
                        {String(cell.getValue())}
                      </Button>
                    ) : (
                      <table.FlexRender cell={cell} />
                    )}
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
  const columnItems = dataset.columns.map((c) => ({
    value: c.name,
    label: columnLabel(c.name),
  }));
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
            <SelectTrigger className="w-full" aria-label="Filter column">
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
              <SelectTrigger className="w-28" aria-label="Filter operator">
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
  wrap,
  onWrapChange,
  confidence,
  onConfidenceChange,
  onViewChange,
  onPageSizeChange,
}: {
  view: View;
  pageSize: number;
  wrap: boolean;
  onWrapChange: (value: boolean) => void;
  confidence: boolean;
  onConfidenceChange: (value: boolean) => void;
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
          <Field orientation="horizontal">
            <Checkbox
              id="wrap-cells"
              checked={wrap}
              onCheckedChange={(value) => onWrapChange(value === true)}
            />
            <FieldLabel htmlFor="wrap-cells">Wrap cell text</FieldLabel>
          </Field>
          <Field orientation="horizontal">
            <Checkbox
              id="show-confidence"
              checked={confidence}
              onCheckedChange={(value) => onConfidenceChange(value === true)}
            />
            <FieldLabel htmlFor="show-confidence">Show model confidence columns</FieldLabel>
          </Field>
          <FieldDescription>
            Confidence is supplied by the model; it is not verified accuracy. Set the run&apos;s
            sample size beside Run.
          </FieldDescription>
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
function SqlButton({
  sql,
  onApply,
  open,
  onOpenChange,
}: {
  sql: string;
  onApply: (sql: string) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [text, setText] = useState(sql);
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
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
            onOpenChange(false);
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
