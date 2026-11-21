"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  SearchIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Spinner } from "@/components/ui/spinner";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { answerLabel } from "@/components/delete-answers";
import type { AnswerColumn, Column, Dataset, Row } from "@/lib/api/client";
import { columnLabel, formatCell, formatNumber } from "@/lib/format";
import { shownColumns } from "@/lib/columns";
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

const emptyRows: Row[] = [];
// Rows and columns rendered beyond those on screen, so scrolling doesn't show blanks.
const OVERSCAN_ROWS = 10;
const OVERSCAN_COLUMNS = 4;
// A row's height, which is fixed: cells keep to one line.
const ROW_HEIGHT = 37;
// Column widths, in px: from the header's and the page's longest text, within these bounds.
const MIN_WIDTH = 72;
const MAX_WIDTH = 384;
// Roughly a character of the cells' text (text-sm, tabular digits), erring wide.
const CHAR_WIDTH = 8.5;

/**
 * A dataset's rows, as the view picks them: search, filters, sort and limit, which become `sql`, or SQL
 * written directly. The rows shown here are exactly the rows the next run asks about. Paging is the
 * table's own. `version` changes when the rows themselves do, e.g. as a run fills in its answers, so
 * the page is fetched again. An answer column's header menu deletes its answers (`onDeleteAnswers`).
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
  onDeleteAnswers,
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
  onDeleteAnswers?: (answer: AnswerColumn) => void;
}) {
  const { search, filters } = view;
  const custom = view.sql !== null;
  const sort = view.sort[0] ?? null;
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(100);
  const [previousSql, setPreviousSql] = useState(sql);
  if (sql !== previousSql) {
    setPreviousSql(sql);
    setPage(0);
  }

  function changeView(changes: Partial<View>) {
    onViewChange(changes);
    setPage(0);
  }

  // Only the columns shown are fetched: a dataset can have too many answer columns to read whole.
  const columns = useMemo(() => shownColumns(dataset, view), [dataset, view]);
  const { result, shown, loading } = useDatasetRows(
    dataset.id,
    sql,
    columns.length < dataset.columns.length ? columns.map((c) => c.name) : undefined,
    page,
    pageSize,
    version,
  );

  useEffect(() => {
    if (result?.data) onCount?.(result.data.total);
  }, [result, onCount]);

  // The query's columns, which SQL can choose or compute.
  const tableColumns = useMemo(() => {
    const available = shown?.columns ?? columns;
    if (!priorityColumns?.length) return available;
    const order = [ROW_ID, ...priorityColumns];
    return [...available].sort((a, b) => {
      const ai = order.indexOf(a.name),
        bi = order.indexOf(b.name);
      return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi);
    });
  }, [shown?.columns, columns, priorityColumns]);
  const rows = shown?.rows ?? emptyRows;
  const widths = useMemo(() => columnWidths(tableColumns, rows), [tableColumns, rows]);

  // Only the rows and columns on screen are rendered: a wide page has tens of thousands of cells.
  // The header scrolls with the rows; the overscan absorbs its height.
  const scrollRef = useRef<HTMLDivElement>(null);
  // The app has no React Compiler to skip it; the virtualizer redraws this component as it scrolls.
  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: OVERSCAN_ROWS,
  });
  const columnVirtualizer = useVirtualizer({
    horizontal: true,
    count: tableColumns.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => widths[i],
    overscan: OVERSCAN_COLUMNS,
  });
  // A new page, or other columns: their sizes are estimated afresh, before they are painted.
  useLayoutEffect(() => {
    columnVirtualizer.measure();
  }, [widths, columnVirtualizer]);
  const visibleRows = rowVirtualizer.getVirtualItems();
  const visibleColumns = columnVirtualizer.getVirtualItems();
  const columnsWidth = columnVirtualizer.getTotalSize();
  const before = visibleColumns[0]?.start ?? 0;
  const after = columnsWidth - (visibleColumns.at(-1)?.end ?? 0);
  const above = visibleRows[0]?.start ?? 0;
  const below = rowVirtualizer.getTotalSize() - (visibleRows.at(-1)?.end ?? 0);

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
            <SearchBox search={search} onViewChange={onViewChange} />
            <FilterButton
              dataset={dataset}
              onAdd={(filter) => changeView({ filters: [...filters, filter] })}
            />
            <DisplayButton
              dataset={dataset}
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
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto select-text">
        {/* One scrolling area for both directions; the table's own wrapper would add a second. */}
        <table
          data-slot="table"
          className="min-w-full caption-bottom table-fixed text-sm"
          style={{ width: columnsWidth }}
        >
          <TableHeader className="bg-muted/40">
            <TableRow>
              {before > 0 && <th style={{ width: before }} />}
              {visibleColumns.map((item) => {
                const column = tableColumns[item.index];
                const answer = dataset.answers.find((a) => a.columns.includes(column.name));
                const SortIcon =
                  sort?.column !== column.name
                    ? ArrowUpDownIcon
                    : sort.desc
                      ? ArrowDownIcon
                      : ArrowUpIcon;
                return (
                  <TableHead
                    key={column.name}
                    className="truncate px-3 select-none"
                    style={{ width: item.size }}
                    draggable={column.name !== ROW_ID}
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", `{{${column.name}}}`)}
                  >
                    <ContextMenu disabled={!answer || !onDeleteAnswers}>
                      <ContextMenuTrigger
                        render={
                          <Button
                            variant="ghost"
                            size="xs"
                            className="-ml-2 text-muted-foreground"
                            title={column.type}
                            // Custom SQL sorts itself.
                            disabled={custom}
                            onClick={() => toggleSort(column.name)}
                          />
                        }
                      >
                        {columnLabel(column.name)}
                        <SortIcon
                          data-icon="inline-end"
                          className={
                            sort?.column !== column.name ? "text-muted-foreground" : undefined
                          }
                        />
                      </ContextMenuTrigger>
                      {answer && (
                        <ContextMenuContent>
                          <ContextMenuItem
                            variant="destructive"
                            onClick={() => onDeleteAnswers?.(answer)}
                          >
                            <Trash2Icon />
                            Delete {answerLabel(answer)}…
                          </ContextMenuItem>
                        </ContextMenuContent>
                      )}
                    </ContextMenu>
                  </TableHead>
                );
              })}
              {after > 0 && <th style={{ width: after }} />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {above > 0 && (
              <tr>
                <td style={{ height: above }} />
              </tr>
            )}
            {visibleRows.map((item) => {
              const row = rows[item.index];
              const position = page * pageSize + item.index;
              return (
                <TableRow
                  key={item.index}
                  className="border-border/60"
                  data-state={selectedPosition === position ? "selected" : undefined}
                  onClick={() => onPickRow?.(position)}
                >
                  {before > 0 && <td />}
                  {visibleColumns.map((column) => (
                    <TableCell
                      key={tableColumns[column.index].name}
                      className="truncate px-3 tabular-nums"
                    >
                      <CellValue value={row[tableColumns[column.index].name]} />
                    </TableCell>
                  ))}
                  {after > 0 && <td />}
                </TableRow>
              );
            })}
            {below > 0 && (
              <tr>
                <td style={{ height: below }} />
              </tr>
            )}
          </TableBody>
        </table>
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

/** The rows' search box: its text is its own until typing pauses, so typing doesn't redraw the rows. */
function SearchBox({
  search,
  onViewChange,
}: {
  search: string;
  onViewChange: (changes: Partial<View>) => void;
}) {
  const [text, setText] = useState(search);
  const [previous, setPrevious] = useState(search);
  // Comparison drill-through can replace the search while this tab remains mounted. (Its own
  // search coming back isn't one: a keystroke typed meanwhile is kept.)
  if (search !== previous) {
    setPrevious(search);
    setText(search);
  }
  useEffect(() => {
    const timer = setTimeout(() => {
      if (text === search) return;
      setPrevious(text);
      onViewChange({ search: text });
    }, 300);
    return () => clearTimeout(timer);
  }, [text, search, onViewChange]);
  return (
    <InputGroup className="w-56">
      <InputGroupAddon>
        <SearchIcon />
      </InputGroupAddon>
      <InputGroupInput
        id="rows-search"
        placeholder="Search"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
    </InputGroup>
  );
}

/** Each column's width, in px: enough for its header and the page's longest value, within bounds. */
function columnWidths(columns: Column[], rows: Row[]): number[] {
  return columns.map((column) => {
    // The header's label, plus its sort icon.
    let longest = columnLabel(column.name).length + 3;
    for (const row of rows) {
      const value = row[column.name];
      if (value !== null && value !== undefined) {
        longest = Math.max(longest, formatCell(value).length);
      }
      if (longest * CHAR_WIDTH >= MAX_WIDTH) break;
    }
    return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.ceil(longest * CHAR_WIDTH) + 24));
  });
}
