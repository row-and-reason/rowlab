"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";

export default function Home() {
  const [status, setStatus] = useState("checking…");

  useEffect(() => {
    api.GET("/v1/health").then(({ data, error }) => {
      setStatus(error || !data ? "API unreachable" : `API ${data.status} · v${data.version}`);
    });
  }, []);

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-2">
      <h1 className="text-2xl font-semibold">rowlab</h1>
      <p className="text-sm text-muted-foreground">{status}</p>
    </main>
  );
}
