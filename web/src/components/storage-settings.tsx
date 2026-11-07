"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useMe } from "@/components/me";
import { StorageConnections } from "@/components/storage-connections";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/lib/api/client";
import { errorMessage, formatBytes } from "@/lib/format";

/** Current recorded dataset sizes, independent of the month or caller's run-usage scope. */
export function DatasetStorage({ bytes }: { bytes: number }) {
  const me = useMe();
  const params = useSearchParams();
  return (
    <section className="space-y-2 border-b pb-4" aria-label="Current dataset storage">
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-sm font-medium">Dataset storage</h3>
        <Button
          nativeButton={false}
          variant="ghost"
          size="sm"
          render={<Link href={`/?${params.get("from") ?? ""}`} />}
        >
          View datasets
        </Button>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-lg font-semibold tabular-nums">{formatBytes(bytes)} used</span>
        <span className="text-xs text-muted-foreground">
          {me.user ? `${me.org.name} · all members` : "This workspace"} · current
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Recorded size of datasets in rowlab. External bucket contents aren’t included.
      </p>
    </section>
  );
}

export function StorageSettings() {
  const [result, setResult] = useState<{ bytes?: number; error?: string }>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    api
      .GET("/v1/settings/usage")
      .then(({ data, error }) => {
        if (current)
          setResult(data ? { bytes: data.storage_bytes } : { error: errorMessage(error) });
      })
      .catch(() => {
        if (current) setResult({ error: "Could not reach rowlab." });
      });
    return () => {
      current = false;
    };
  }, [attempt]);
  return (
    <div className="space-y-5">
      {result?.bytes !== undefined ? (
        <DatasetStorage bytes={result.bytes} />
      ) : result?.error ? (
        <Alert variant="destructive">
          <AlertDescription>{result.error}</AlertDescription>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setResult(undefined);
              setAttempt((n) => n + 1);
            }}
          >
            Retry storage usage
          </Button>
        </Alert>
      ) : (
        <div role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
          <Spinner />
          Loading storage usage…
        </div>
      )}
      <section className="space-y-3">
        <div className="space-y-1">
          <h3 className="text-sm font-medium">External connections</h3>
          <p className="text-xs text-muted-foreground">
            Import and export through AWS S3, Cloudflare R2, MinIO or another S3-compatible service.
          </p>
        </div>
        <StorageConnections />
      </section>
    </div>
  );
}
