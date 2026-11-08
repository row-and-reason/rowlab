---
title: Skill
description: One skill for labeling, measuring quality and running at scale with rowlab.
---

The MCP tools describe what rowlab can do. The
[Rowlab skill](https://github.com/row-and-reason/agent-skills/tree/main/skills/rowlab)
teaches an agent how to use them: define a task, label manually or with models, compare
quality, choose a model, run at scale and export the result.

```sh
npx skills add row-and-reason/agent-skills --skill rowlab
```

Add `-a codex -g` to install globally for Codex, or `-a claude-code -g` for Claude Code.
Installing the skill does not connect or sign in to the MCP server; follow the
[MCP connection guide](/agents/mcp) separately. Restart your agent after installation.

One skill covers the whole workflow. It teaches the agent to inspect answers alongside
inputs, distinguish model agreement from accuracy, evaluate representative samples,
and stay within the authorized scope and budget. Exact tool arguments come from the
connected server rather than a second copy of the API documentation.

For manual labeling, the agent starts a manual run, presents rows or receives labels,
saves answers with `run_answers`, then locks the completed output with `run_finish`.
Manual execution does not imply human authorship: the agent submits labels supplied by
the user or explicitly authorized for it to produce. This workflow requires a server
that exposes those tools.

If you installed the earlier separate Rowlab skills, remove those installed copies after
installing `rowlab` to avoid competing instructions.
