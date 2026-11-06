"use client";

import { createColumnHelper, tableFeatures, useTable } from "@tanstack/react-table";
import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon, XIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
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
import { api, type Dataset, type Filter, type QueryResult, type Sort } from "@/lib/api/client";
import { errorMessage, formatCell, formatNumber } from "@/lib/format";

type Row = Record<string, unknown>;

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

/** Server-side search, filters, sort and paging over a dataset's rows. */
export function DatasetExplorer({ dataset }: { dataset: Dataset }) {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Filter[]>([]);
  const [sort, setSort] = useState<Sort | null>(null);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(100);

  // Each result remembers the request it answers, so a stale response is never shown as current.
  const request = useMemo(
    () => ({ search, filters, sort: sort ? [sort] : [], offset: page * pageSize, limit: pageSize }),
    [search, filters, sort, page, pageSize],
  );
  const [result, setResult] = useState<{ request: typeof request; data?: QueryResult; error?: string }>();

  // Debounce typing in the search box.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput);
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

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
  }, [dataset.id, request]);

  const columns = useMemo(
    () =>
      dataset.columns.map((c) =>
        helper.accessor((row) => row[c.name], {
          id: c.name,
          header: c.name,
          cell: (info) => <CellValue value={info.getValue()} />,
        }),
      ),
    [dataset.columns],
  );
  // The last good page stays on screen while the next one loads.
  const [shown, setShown] = useState<QueryResult>();
  if (result?.data && result.data !== shown) setShown(result.data);
  const table = useTable({ features, columns, data: shown?.rows ?? emptyRows });

  const loading = result?.request !== request;
  const total = shown?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);

  function toggleSort(column: string) {
    if (sort?.column !== column) setSort({ column, desc: false });
    else if (!sort.desc) setSort({ column, desc: true });
    else setSort(null);
    setPage(0);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="w-64"
          placeholder="Search all columns"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <AddFilter
          dataset={dataset}
          onAdd={(filter) => {
            setFilters([...filters, filter]);
            setPage(0);
          }}
        />
        {loading && <Spinner />}
      </div>

      {filters.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {filters.map((f, i) => (
            <Badge key={i} variant="secondary">
              {f.column} {opLabel(f.op)} {takesValue(f.op) && <code>{String(f.value)}</code>}
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Remove filter"
                onClick={() => {
                  setFilters(filters.filter((_, j) => j !== i));
                  setPage(0);
                }}
              >
                <XIcon />
              </Button>
            </Badge>
          ))}
        </div>
      )}

      {result?.error && !loading && (
        <Alert variant="destructive">
          <AlertDescription>{result.error}</AlertDescription>
        </Alert>
      )}

      <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
        <span>
          {total === 0
            ? "No matching rows"
            : `${formatNumber(page * pageSize + 1)}–${formatNumber(Math.min(total, (page + 1) * pageSize))} of ${formatNumber(total)}`}
        </span>
        <div className="flex items-center gap-2">
          <Select
            items={PAGE_SIZES}
            value={String(pageSize)}
            onValueChange={(value) => {
              setPageSize(Number(value));
              setPage(0);
            }}
          >
            <SelectTrigger size="sm">
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
          <Pagination className="mx-0 w-auto">
            <PaginationContent>
              <PaginationItem>
                <PaginationPrevious
                  href="#"
                  aria-disabled={page === 0}
                  className={page === 0 ? "pointer-events-none opacity-50" : ""}
                  onClick={(e) => {
                    e.preventDefault();
                    setPage(Math.max(0, page - 1));
                  }}
                />
              </PaginationItem>
              <PaginationItem>
                <PaginationNext
                  href="#"
                  aria-disabled={page >= lastPage}
                  className={page >= lastPage ? "pointer-events-none opacity-50" : ""}
                  onClick={(e) => {
                    e.preventDefault();
                    setPage(Math.min(lastPage, page + 1));
                  }}
                />
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        </div>
      </div>

      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => {
                const column = dataset.columns.find((c) => c.name === header.id);
                const SortIcon =
                  sort?.column !== header.id ? ArrowUpDownIcon : sort.desc ? ArrowDownIcon : ArrowUpIcon;
                return (
                  <TableHead key={header.id}>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="-ml-2.5"
                      title={column?.type}
                      onClick={() => toggleSort(header.id)}
                    >
                      {header.id}
                      <SortIcon data-icon="inline-end" />
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

function AddFilter({ dataset, onAdd }: { dataset: Dataset; onAdd: (filter: Filter) => void }) {
  const columnItems = dataset.columns.map((c) => ({ value: c.name, label: c.name }));
  const [column, setColumn] = useState<string | null>(null);
  const [op, setOp] = useState<Filter["op"]>("eq");
  const [value, setValue] = useState("");

  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!column) return;
        onAdd({ column, op, value: takesValue(op) ? value : null });
        setValue("");
      }}
    >
      <Select items={columnItems} value={column} onValueChange={setColumn}>
        <SelectTrigger className="w-40">
          <SelectValue placeholder="Filter column" />
        </SelectTrigger>
        <SelectContent>
          {columnItems.map((c) => (
            <SelectItem key={c.value} value={c.value}>
              {c.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select items={OPS} value={op} onValueChange={(v) => v && setOp(v)}>
        <SelectTrigger className="w-32">
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
          className="w-40"
          placeholder="Value"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      )}
      <Button type="submit" variant="outline" disabled={!column}>
        Add filter
      </Button>
    </form>
  );
}
