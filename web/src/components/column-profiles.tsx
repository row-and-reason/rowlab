"use client";

import { useEffect, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type ColumnProfile } from "@/lib/api/client";
import { errorMessage, formatNumber } from "@/lib/format";

/**
 * Statistics for every column and nested field, each draggable into the prompt. Fetched when shown,
 * since profiling scans the whole dataset.
 */
export function ColumnProfiles({ datasetId }: { datasetId: string }) {
  const [profiles, setProfiles] = useState<ColumnProfile[]>();
  const [error, setError] = useState<string>();
  const [search, setSearch] = useState("");

  useEffect(() => {
    api
      .GET("/v1/datasets/{dataset_id}/profile", {
        params: { path: { dataset_id: datasetId } },
      })
      .then(({ data, error }) =>
        error ? setError(errorMessage(error)) : setProfiles(data),
      );
  }, [datasetId]);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  if (!profiles) return <Spinner />;
  const shown = profiles.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Input
          className="w-64"
          placeholder="Search columns"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="text-sm text-muted-foreground">
          Drag a column into the prompt.
        </span>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Column</TableHead>
            <TableHead>Type</TableHead>
            <TableHead className="text-right">Nulls</TableHead>
            <TableHead className="text-right">Distinct (approx.)</TableHead>
            <TableHead>Min</TableHead>
            <TableHead>Max</TableHead>
            <TableHead>Average</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((p) => (
            <TableRow
              key={p.name}
              draggable
              className="cursor-grab"
              onDragStart={(e) =>
                e.dataTransfer.setData("text/plain", `{{${p.name}}}`)
              }
            >
              <TableCell className="font-mono text-xs">{p.name}</TableCell>
              <TableCell>
                <Badge variant="secondary" className="font-mono">
                  {p.type}
                </Badge>
              </TableCell>
              <TableCell className="text-right">
                {p.null_percentage == null ? "" : `${p.null_percentage}%`}
              </TableCell>
              <TableCell className="text-right">
                {p.approx_unique == null ? "" : formatNumber(p.approx_unique)}
              </TableCell>
              {[p.min, p.max, p.avg].map((value, i) => (
                <TableCell
                  key={i}
                  className="max-w-48 truncate"
                  title={value ?? ""}
                >
                  {value}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
