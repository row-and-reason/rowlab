"use client";

import { createColumnHelper, tableFeatures, useTable } from "@tanstack/react-table";
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
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
import { api, type Dataset, type Filter, type QueryResult, type Scope } from "@/lib/api/client";
import { columnLabel, errorMessage, formatCell, formatNumber } from "@/lib/format";

type Row = Record<string, unknown>;

const ROW_ID = "__row_id";

const features = tableFeatures({});
const helper = createColumnHelper<typeof features, Row>();
const emptyRows: Row[] = [];

const OPS: { value: Filter["op"]; label: string }[] = [
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
const opLabel = (op: Filter["op"]) => OPS.find((o) => o.value === op)?.label;
const takesValue = (op: Filter["op"]) => op !== "is_null" && op !== "is_not_null";

const PAGE_SIZES = [50, 100, 250, 500].map((n) => ({ value: String(n), label: `${n} rows` }));

/**
 * Server-side search, filters, sort, limit and paging over a dataset's rows. All but the paging are
 * the job's scope: the rows shown here are exactly the rows the job runs on. `version` changes when
 * the rows themselves do, e.g. as a run fills in its answers, so the page is fetched again.
 */
export function DatasetExplorer({
  dataset,
  scope,
  onScopeChange,
  version,
}: {
  dataset: Dataset;
  scope: Scope;
  onScopeChange: (changes: Partial<Scope>) => void;
  version?: number;
}) {
  const { search, filters } = scope;
  const sort = scope.sort[0] ?? null;
  const [searchInput, setSearchInput] = useState(search);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(100);

  function changeScope(changes: Partial<Scope>) {
    onScopeChange(changes);
    setPage(0);
  }

  // Each result remembers the request it answers, so a stale response is never shown as current.
  const request = useMemo(
    () => ({ ...scope, offset: page * pageSize, page_size: pageSize }),
    [scope, page, pageSize],
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
      onScopeChange({ search: searchInput });
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput, search, onScopeChange]);

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

  const columns = useMemo(
    () =>
      dataset.columns.map((c) =>
        helper.accessor((row) => row[c.name], {
          id: c.name,
          header: columnLabel(c.name),
          cell: (info) => <CellValue value={info.getValue()} />,
        }),
      ),
    [dataset.columns],
  );
  const table = useTable({ features, columns, data: shown?.rows ?? emptyRows });

  const loading = result?.request !== request;
  const total = shown?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);

  function toggleSort(column: string) {
    if (sort?.column !== column) changeScope({ sort: [{ column, desc: false }] });
    else if (!sort.desc) changeScope({ sort: [{ column, desc: true }] });
    else changeScope({ sort: [] });
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-b px-3 py-2">
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
          onAdd={(filter) => changeScope({ filters: [...filters, filter] })}
        />
        <DisplayButton
          scope={scope}
          pageSize={pageSize}
          onScopeChange={changeScope}
          onPageSizeChange={(size) => {
            setPageSize(size);
            setPage(0);
          }}
        />
        {filters.map((f, i) => (
          <Badge key={i} variant="secondary" className="h-7 gap-1 pr-0.5">
            {columnLabel(f.column)} {opLabel(f.op)}{" "}
            {takesValue(f.op) && <code>{String(f.value)}</code>}
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Remove filter"
              onClick={() => changeScope({ filters: filters.filter((_, j) => j !== i) })}
            >
              <XIcon />
            </Button>
          </Badge>
        ))}
        {scope.limit && (
          <Badge variant="secondary" className="h-7 gap-1 pr-0.5">
            First {formatNumber(scope.limit)} rows
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Remove limit"
              onClick={() => changeScope({ limit: null })}
            >
              <XIcon />
            </Button>
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          {loading && <Spinner />}
          <span
            title={
              shown && shown.matched > total
                ? `${formatNumber(shown.matched)} rows match`
                : undefined
            }
          >
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
                  const column = dataset.columns.find((c) => c.name === header.id);
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

function FilterButton({ dataset, onAdd }: { dataset: Dataset; onAdd: (filter: Filter) => void }) {
  const columnItems = dataset.columns.map((c) => ({ value: c.name, label: columnLabel(c.name) }));
  const [open, setOpen] = useState(false);
  const [column, setColumn] = useState<string | null>(null);
  const [op, setOp] = useState<Filter["op"]>("eq");
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

/** How the rows are shown: the limit (part of the job's scope) and the page size. */
function DisplayButton({
  scope,
  pageSize,
  onScopeChange,
  onPageSizeChange,
}: {
  scope: Scope;
  pageSize: number;
  onScopeChange: (changes: Partial<Scope>) => void;
  onPageSizeChange: (size: number) => void;
}) {
  const sort = scope.sort[0];
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
              value={scope.limit ?? ""}
              onChange={(e) =>
                onScopeChange({ limit: Number(e.target.value) > 0 ? Number(e.target.value) : null })
              }
            />
            <FieldDescription>
              Only the first rows, in this order. The job runs on these.
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
                  <Button variant="ghost" size="xs" onClick={() => onScopeChange({ sort: [] })}>
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
