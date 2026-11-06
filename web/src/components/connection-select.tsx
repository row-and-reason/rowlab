"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, type Connection } from "@/lib/api/client";

// Picked when no connection is: the AWS credentials in rowlab's environment, if any.
const ENVIRONMENT = "environment";

/** Saved connections to S3-compatible storage, fetched again each time a form needs them. */
export function useConnections(): Connection[] | undefined {
  const [connections, setConnections] = useState<Connection[]>();
  useEffect(() => {
    api.GET("/v1/settings/connections").then(({ data }) => setConnections(data));
  }, []);
  return connections;
}

/** Which connection reads or writes an `s3://` location. `null` means the environment's credentials. */
export function ConnectionSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string | null;
  onChange: (connectionId: string | null) => void;
}) {
  const connections = useConnections();
  const items = [
    { value: ENVIRONMENT, label: "AWS credentials from the environment, or none" },
    ...(connections ?? []).map((c) => ({ value: c.id, label: c.name })),
  ];
  // With connections saved, one of them is likelier meant than the environment: the first is picked.
  useEffect(() => {
    if (value === null && connections?.length) onChange(connections[0].id);
    // Only once the connections arrive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connections]);

  return (
    <Field>
      <FieldLabel htmlFor={id}>Connection</FieldLabel>
      <Select
        items={items}
        value={value ?? ENVIRONMENT}
        onValueChange={(picked) => onChange(picked === ENVIRONMENT ? null : (picked as string))}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <FieldDescription>
        Without a connection, public buckets work too. Add or change connections in{" "}
        <Link href="/settings/?section=storage" className="underline">
          Settings → Storage
        </Link>
        .
      </FieldDescription>
    </Field>
  );
}
