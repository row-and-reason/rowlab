"use client";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { percent, type InspectRows, type Pair } from "@/lib/comparison";
import { formatNumber } from "@/lib/format";

/** A label with a tooltip explaining what it counts. */
export function Definition({ label, description }: { label: string; description: string }) {
  return (
    <Tooltip>
      <TooltipTrigger render={<span tabIndex={0} className="cursor-help" />}>
        {label}
      </TooltipTrigger>
      <TooltipContent>{description}</TooltipContent>
    </Tooltip>
  );
}

/** A rate with its 95% interval: `80.0% (49.0–94.3)`. */
export function Rate({ rate, ci }: { rate: number | null; ci: Pair["rate_ci"] }) {
  return (
    <span className="tabular-nums">
      {percent(rate)}
      {ci && (
        <span className="text-muted-foreground">
          {` (${(ci.low * 100).toFixed(1)}–${(ci.high * 100).toFixed(1)})`}
        </span>
      )}
    </span>
  );
}

/** A row count that opens those rows when there are any and the server gave a predicate. */
export function Count({
  rows,
  where,
  label,
  columns,
  onFilter,
  children,
}: {
  rows: number;
  where?: string | null;
  label: string;
  columns: string[];
  onFilter: InspectRows;
  children?: React.ReactNode;
}) {
  return where && rows > 0 ? (
    <Button
      variant="ghost"
      size="sm"
      className="h-auto px-0 text-xs text-primary hover:text-primary dark:hover:text-primary tabular-nums"
      aria-label={`Inspect ${formatNumber(rows)} rows: ${label}`}
      onClick={() => onFilter([{ where, label }], columns)}
    >
      {formatNumber(rows)}
      {children && <> {children}</>}
    </Button>
  ) : (
    <span className="tabular-nums">
      {formatNumber(rows)}
      {children && <> {children}</>}
    </span>
  );
}
