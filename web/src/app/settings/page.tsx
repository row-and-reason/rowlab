"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

import { ApiKeys } from "@/components/api-keys";
import { useCan, useMe } from "@/components/me";
import { MembersSettings } from "@/components/members-settings";
import { PaneHeader } from "@/components/pane";
import { Plans } from "@/components/plans";
import { StorageSettings } from "@/components/storage-settings";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { TooltipButton } from "@/components/tooltip-button";
import { UsageSettings } from "@/components/usage-settings";
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
import { type Section, sections, settingsUrl } from "@/lib/settings";

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
  const me = useMe();
  const shown = sections(me);
  const section: Section = shown.find((s) => s.id === params.get("section"))?.id ?? "providers";
  const back = `/?${params.get("from") ?? ""}`;
  const [settings, setSettings] = useState<Settings>();

  const [loadError, setLoadError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    api
      .GET("/v1/settings")
      .then(({ data, error }) => {
        if (current) {
          if (data) setSettings(data);
          else setLoadError(errorMessage(error));
        }
      })
      .catch(() => {
        if (current) setLoadError("Could not reach rowlab.");
      });
    return () => {
      current = false;
    };
  }, [attempt]);

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
      <nav className="flex w-[16%] min-w-48 shrink-0 flex-col border-r bg-sidebar">
        <PaneHeader>
          <span className="pl-1.5 text-sm font-medium">Settings</span>
          <TooltipButton
            className="ml-auto"
            label="Back"
            keys={["Esc"]}
            variant="ghost"
            size="icon-sm"
            render={<Link href={back} />}
            nativeButton={false}
          >
            <ArrowLeftIcon />
          </TooltipButton>
        </PaneHeader>
        <ItemGroup className="gap-0.5 p-2">
          {shown.map((s) => (
            <Item
              key={s.id}
              size="xs"
              variant={s.id === section ? "muted" : "default"}
              aria-current={s.id === section ? "page" : undefined}
              className="aria-[current=page]:bg-sidebar-accent aria-[current=page]:text-sidebar-accent-foreground"
              render={<Link href={link(s.id)} />}
            >
              <ItemContent>
                <ItemTitle>{s.label}</ItemTitle>
              </ItemContent>
            </Item>
          ))}
        </ItemGroup>
        <div className="mt-auto border-t px-4 py-3 text-xs text-muted-foreground">
          <p className="truncate font-medium text-foreground" title={me.org.name}>
            {me.user ? me.org.name : "Local workspace"}
          </p>
          <p className="mt-1">
            {me.user
              ? `${me.role[0].toUpperCase()}${me.role.slice(1)} access`
              : "Stored on this instance"}
          </p>
        </div>
      </nav>
      <section className="flex min-w-0 flex-1 flex-col">
        <PaneHeader>
          <span className="font-medium">{shown.find((s) => s.id === section)!.label}</span>
        </PaneHeader>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          <div className={section === "usage" ? "max-w-4xl" : "max-w-2xl"}>
            {section === "providers" &&
              (loadError ? (
                <Alert variant="destructive">
                  <AlertDescription>{loadError}</AlertDescription>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setLoadError(undefined);
                      setAttempt((n) => n + 1);
                    }}
                  >
                    Retry
                  </Button>
                </Alert>
              ) : !settings ? (
                <Spinner />
              ) : (
                <FieldSet className="gap-4">
                  <FieldLegend variant="label" className="flex items-center justify-between gap-3">
                    OpenRouter
                    <Badge variant="secondary">
                      {settings.openrouter_key === "environment"
                        ? "Managed by server"
                        : settings.openrouter_key
                          ? "Connected"
                          : "Not connected"}
                    </Badge>
                  </FieldLegend>
                  <FieldDescription>
                    One provider key for decision models and LLMs.
                  </FieldDescription>
                  <OpenRouterKey settings={settings} onSaved={setSettings} />
                </FieldSet>
              ))}
            {section === "storage" && <StorageSettings />}
            {section === "members" && <MembersSettings />}
            {section === "api-keys" && <ApiKeys />}
            {section === "usage" && <UsageSettings />}
            {section === "plans" && <Plans />}
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
  const canAdmin = useCan("admin");

  async function save() {
    setSaving(true);
    setError(undefined);
    try {
      const { data, error } = await api.PUT("/v1/settings/openrouter-key", { body: { key } });
      if (error) {
        setError(errorMessage(error));
        return;
      }
      setKey("");
      onSaved(data);
      toast.success("OpenRouter key saved");
    } catch {
      setError("Could not reach rowlab. Your key was not saved.");
    } finally {
      setSaving(false);
    }
  }

  if (!canAdmin) {
    return (
      <p className="text-sm text-muted-foreground">
        {settings?.openrouter_key ? "A key is set." : "No key is set yet."} Admins change it.
      </p>
    );
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
        <div className="flex items-center gap-2">
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
          <Button type="submit" size="sm" disabled={saving || !key.trim()}>
            {saving && <Spinner data-icon="inline-start" />}
            Save
          </Button>
        </div>
        {error ? (
          <FieldError>{error}</FieldError>
        ) : (
          <FieldDescription>
            Checked before saving. Used for model calls; never shown again.
          </FieldDescription>
        )}
      </Field>
    </form>
  );
}
