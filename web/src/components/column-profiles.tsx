"use client";

import { useEffect, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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

/** Per-column statistics. Fetched when shown, since profiling scans the whole dataset. */
export function ColumnProfiles({ datasetId }: { datasetId: string }) {
  const [profiles, setProfiles] = useState<ColumnProfile[]>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    api
      .GET("/v1/datasets/{dataset_id}/profile", { params: { path: { dataset_id: datasetId } } })
      .then(({ data, error }) => (error ? setError(errorMessage(error)) : setProfiles(data)));
  }, [datasetId]);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  if (!profiles) return <Spinner />;

  return (
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
        {profiles.map((p) => (
          <TableRow key={p.name}>
            <TableCell className="font-medium">{p.name}</TableCell>
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
              <TableCell key={i} className="max-w-48 truncate" title={value ?? ""}>
                {value}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
