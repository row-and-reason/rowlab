"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { PaneHeader } from "@/components/pane";
import { StorageConnections } from "@/components/storage-connections";
import { TooltipButton } from "@/components/tooltip-button";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Item, ItemContent, ItemGroup, ItemTitle } from "@/components/ui/item";
import { Spinner } from "@/components/ui/spinner";
import { api, type Settings } from "@/lib/api/client";
import { errorMessage } from "@/lib/format";
import { type Section, SECTIONS, settingsUrl } from "@/lib/settings";

// App-wide settings: sections on the left, the picked one on the right. Esc goes back.
export default function SettingsPage() {
  return (
    <Suspense fallback={<Spinner className="m-6" />}>
      <SettingsView />
    </Suspense>
  );
}

function SettingsView() {
  const router = useRouter();
  const params = useSearchParams();
  const section: Section = SECTIONS.find((s) => s.id === params.get("section"))?.id ?? "providers";
  const back = `/?${params.get("from") ?? ""}`;
  const [settings, setSettings] = useState<Settings>();

  useEffect(() => {
    api.GET("/v1/settings").then(({ data }) => setSettings(data));
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && !e.defaultPrevented) router.push(back);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [router, back]);

  const link = (id: Section) => settingsUrl(new URLSearchParams(params.get("from") ?? ""), id);

  return (
    <main className="flex min-h-0 flex-1">
      <nav className="flex w-56 shrink-0 flex-col border-r">
        <PaneHeader>
          <TooltipButton
            label="Back"
            keys={["Esc"]}
            variant="ghost"
            size="icon-sm"
            render={<Link href={back} />}
          >
            <ArrowLeftIcon />
          </TooltipButton>
          <span className="font-semibold">Settings</span>
        </PaneHeader>
        <ItemGroup className="gap-0.5 p-2">
          {SECTIONS.map((s) => (
            <Item
              key={s.id}
              size="xs"
              variant={s.id === section ? "muted" : "default"}
              render={<Link href={link(s.id)} />}
            >
              <ItemContent>
                <ItemTitle>{s.label}</ItemTitle>
              </ItemContent>
            </Item>
          ))}
        </ItemGroup>
      </nav>
      <section className="flex min-w-0 flex-1 flex-col">
        <PaneHeader>
          <span className="font-medium">{SECTIONS.find((s) => s.id === section)!.label}</span>
        </PaneHeader>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          <div className="max-w-xl">
            {section === "providers" ? (
              <FieldSet>
                <FieldLegend>OpenRouter</FieldLegend>
                <FieldDescription>
                  Decision models and hundreds of LLMs, through one key.
                </FieldDescription>
                <OpenRouterKey settings={settings} onSaved={setSettings} />
              </FieldSet>
            ) : (
              <FieldSet>
                <FieldLegend>S3-compatible</FieldLegend>
                <FieldDescription>AWS S3, Cloudflare R2, MinIO and others.</FieldDescription>
                <StorageConnections />
              </FieldSet>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

/** Save an OpenRouter API key, checked with OpenRouter first. */
function OpenRouterKey({
  settings,
  onSaved,
}: {
  settings: Settings | undefined;
  onSaved: (settings: Settings) => void;
}) {
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();

  async function save() {
    setSaving(true);
    setError(undefined);
    const { data, error } = await api.PUT("/v1/settings/openrouter-key", { body: { key } });
    setSaving(false);
    if (error) {
      setError(errorMessage(error));
      return;
    }
    setKey("");
    onSaved(data);
    toast.success("OpenRouter key saved");
  }

  if (settings?.openrouter_key === "environment") {
    return (
      <p className="text-sm text-muted-foreground">
        The key comes from the <code>OPENROUTER_API_KEY</code> environment variable. Unset it to
        save one here instead.
      </p>
    );
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (key.trim()) save();
      }}
    >
      <Field data-invalid={!!error}>
        <FieldLabel htmlFor="openrouter-key">API key</FieldLabel>
        <div className="flex gap-2">
          <Input
            id="openrouter-key"
            type="password"
            placeholder={
              settings?.openrouter_key ? "Saved · paste a new one to replace it" : "sk-or-v1-…"
            }
            autoComplete="off"
            value={key}
            aria-invalid={!!error}
            onChange={(e) => setKey(e.target.value)}
          />
          <Button type="submit" disabled={saving || !key.trim()}>
            {saving && <Spinner data-icon="inline-start" />}
            Save
          </Button>
        </div>
        {error ? (
          <FieldError>{error}</FieldError>
        ) : (
          <FieldDescription>
            Used for model calls. Checked with OpenRouter before it is saved, and never shown again.
          </FieldDescription>
        )}
      </Field>
    </form>
  );
}
