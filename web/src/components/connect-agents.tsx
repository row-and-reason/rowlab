"use client";

import { use } from "react";
import { browser } from "react-dom";
import { toast } from "sonner";

import { useMe } from "@/components/me";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";

export function ConnectAgents() {
  use(browser("Connection commands use this server's address."));
  const me = useMe();
  const url = `${(process.env.NEXT_PUBLIC_API_URL || window.location.origin).replace(/\/$/, "")}/mcp`;
  const quotedUrl = `'${url.replaceAll("'", "'\\''")}'`;

  async function copy(commands: string) {
    try {
      await navigator.clipboard.writeText(commands);
      toast.success("Commands copied");
    } catch {
      toast.error("Could not copy. Select and copy the commands below.");
    }
  }

  return (
    <div className="grid gap-6">
      <p className="text-sm text-muted-foreground">
        Connect your agent to this rowlab and install its skill for labeling, comparing quality and
        running at scale. Run these commands in your terminal with your agent CLI and Node.js
        installed. Skills are installed for your user, across projects.
        {me.user
          ? " Sign in with the same account you use here when the browser opens."
          : " This local server needs no sign-in."}
      </p>
      {(["codex", "claude-code"] as const).map((agent) => {
        const cli = agent === "codex" ? "codex" : "claude";
        const commands = [
          agent === "codex"
            ? `codex mcp add rowlab --url ${quotedUrl}`
            : `claude mcp add --scope user --transport http rowlab ${quotedUrl}`,
          ...(me.user ? [`${cli} mcp login rowlab`] : []),
          `npx skills add row-and-reason/agent-skills --skill rowlab -a ${agent} -g -y`,
        ].join("\n");
        return (
          <Field key={agent}>
            <div className="flex items-center justify-between gap-2">
              <FieldLabel htmlFor={`connect-${agent}`}>
                {agent === "codex" ? "Codex" : "Claude Code"}
              </FieldLabel>
              <Button size="sm" variant="outline" onClick={() => copy(commands)}>
                Copy commands
              </Button>
            </div>
            <Textarea id={`connect-${agent}`} readOnly value={commands} rows={me.user ? 3 : 2} />
            <FieldDescription>
              Restart your agent after installation. Ask it to list your rowlab datasets to check
              the connection.
            </FieldDescription>
          </Field>
        );
      })}
    </div>
  );
}
