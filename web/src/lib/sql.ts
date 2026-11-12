import type { Column } from "@/lib/api/client";

/** A condition on one column's value, set in the Filter popover. */
export type ColumnFilter = {
  column: string;
  op: "eq" | "ne" | "lt" | "lte" | "gt" | "gte" | "contains" | "is_null" | "is_not_null";
  value: string | null;
};

/** A condition written as SQL, e.g. from a comparison's count, with a label to show for it. */
export type WhereFilter = { where: string; label: string };

export type ViewFilter = ColumnFilter | WhereFilter;

/**
 * Which rows the table shows, and the next run asks about: set with the search box, filters, sorting
 * and limit, which the UI turns into SQL. Or written as SQL directly (`sql`), which they can't show.
 */
export type View = {
  search: string;
  filters: ViewFilter[];
  sort: { column: string; desc: boolean }[];
  limit: number | null;
  sql: string | null;
};

export const ALL_ROWS = "SELECT * FROM data";

const OPERATORS = { eq: "=", ne: "IS DISTINCT FROM", lt: "<", lte: "<=", gt: ">", gte: ">=" };

/** The view as one DuckDB SELECT over `data`, e.g. `SELECT * FROM data WHERE … LIMIT 20`. */
export function viewSql(view: View, columns: Column[]): string {
  if (view.sql !== null) return view.sql;
  const types = new Map(columns.map((c) => [c.name, c.type]));
  const where: string[] = [];
  if (view.search) {
    const text = sqlString(`%${view.search.toLowerCase()}%`);
    const searched = columns
      .filter((c) => c.name !== "__row_id")
      .map((c) => `lower(CAST(${ident(c.name)} AS VARCHAR)) LIKE ${text}`);
    if (searched.length) where.push(`(${searched.join(" OR ")})`);
  }
  for (const f of view.filters) {
    if ("where" in f) {
      where.push(`(${f.where})`);
      continue;
    }
    const column = ident(f.column);
    if (f.op === "is_null") where.push(`${column} IS NULL`);
    else if (f.op === "is_not_null") where.push(`${column} IS NOT NULL`);
    else if (f.op === "contains") {
      where.push(
        `lower(CAST(${column} AS VARCHAR)) LIKE ${sqlString(`%${(f.value ?? "").toLowerCase()}%`)}`,
      );
    } else {
      const type = types.get(f.column) ?? "VARCHAR";
      where.push(`${column} ${OPERATORS[f.op]} CAST(${sqlString(f.value ?? "")} AS ${type})`);
    }
  }
  const order = [
    ...view.sort.map((s) => `${ident(s.column)} ${s.desc ? "DESC" : "ASC"} NULLS LAST`),
    "__row_id",
  ];
  return [
    ALL_ROWS,
    where.length ? `WHERE ${where.join(" AND ")}` : "",
    `ORDER BY ${order.join(", ")}`,
    view.limit ? `LIMIT ${view.limit}` : "",
  ]
    .filter(Boolean)
    .join(" ");
}

/** A column name quoted for SQL. */
function ident(name: string): string {
  return `"${name.replaceAll('"', '""')}"`;
}

/** A string literal for SQL. */
function sqlString(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}
