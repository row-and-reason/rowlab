"use client";

import { createColumnHelper, tableFeatures, useTable } from "@tanstack/react-table";
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Dataset, Row } from "@/lib/api/client";
import { columnLabel, formatCell, formatNumber } from "@/lib/format";
import type { View } from "@/lib/sql";
import { useDatasetRows } from "@/lib/use-dataset-rows";
import {
  DisplayButton,
  FilterButton,
  opLabel,
  SqlButton,
  takesValue,
} from "@/components/dataset-controls";

const ROW_ID = "__row_id";

const features = tableFeatures({});
const helper = createColumnHelper<typeof features, Row>();
const emptyRows: Row[] = [];

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
  priorityColumns,
  onCount,
  onPickRow,
  selectedPosition,
}: {
  dataset: Dataset;
  view: View;
  sql: string;
  onViewChange: (changes: Partial<View>) => void;
  version?: number;
  priorityColumns?: string[];
  onCount?: (count: number) => void;
  onPickRow?: (position: number) => void;
  selectedPosition?: number;
}) {
  const { search, filters } = view;
  const custom = view.sql !== null;
  const sort = view.sort[0] ?? null;
  const [searchInput, setSearchInput] = useState(search);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(100);
  const [previousSearch, setPreviousSearch] = useState(search);
  const [previousSql, setPreviousSql] = useState(sql);
  // Comparison drill-through can replace the view while this tab remains mounted.
  if (search !== previousSearch) {
    setPreviousSearch(search);
    setSearchInput(search);
  }
  if (sql !== previousSql) {
    setPreviousSql(sql);
    setPage(0);
  }

  function changeView(changes: Partial<View>) {
    onViewChange(changes);
    setPage(0);
  }

  // Debounce typing in the search box.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput === search) return;
      onViewChange({ search: searchInput });
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput, search, onViewChange]);

  const { result, shown, loading } = useDatasetRows(dataset.id, sql, page, pageSize, version);

  useEffect(() => {
    if (result?.data) onCount?.(result.data.total);
  }, [result, onCount]);

  // The query's columns, which SQL can choose or compute.
  const shownColumns = useMemo(() => {
    const available = shown?.columns ?? dataset.columns;
    if (!priorityColumns?.length) return available;
    const order = [ROW_ID, ...priorityColumns];
    return [...available].sort((a, b) => {
      const ai = order.indexOf(a.name),
        bi = order.indexOf(b.name);
      return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi);
    });
  }, [shown?.columns, dataset.columns, priorityColumns]);
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
          <TableHeader className="bg-muted/40">
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
                      className="w-px px-3 select-none"
                      draggable={header.id !== ROW_ID}
                      onDragStart={(e) => e.dataTransfer.setData("text/plain", `{{${header.id}}}`)}
                    >
                      <Button
                        variant="ghost"
                        size="xs"
                        className="-ml-2 text-muted-foreground"
                        title={column?.type}
                        // Custom SQL sorts itself.
                        disabled={custom}
                        onClick={() => toggleSort(header.id)}
                      >
                        {columnLabel(header.id)}
                        <SortIcon
                          data-icon="inline-end"
                          className={
                            sort?.column !== header.id ? "text-muted-foreground" : undefined
                          }
                        />
                      </Button>
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row, index) => (
              <TableRow
                key={row.id}
                className="border-border/60"
                data-state={selectedPosition === page * pageSize + index ? "selected" : undefined}
                onClick={() => onPickRow?.(page * pageSize + index)}
              >
                {row.getAllCells().map((cell) => (
                  <TableCell key={cell.id} className="max-w-96 truncate px-3 tabular-nums">
                    <table.FlexRender cell={cell} />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {shown?.total === 0 && !result?.error && (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <SearchIcon />
              </EmptyMedia>
              <EmptyTitle>No rows</EmptyTitle>
              <EmptyDescription>
                {custom
                  ? "The SQL returns no rows from this dataset."
                  : "No row matches the search and filters."}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
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
