---
title: Skills
description: Skills that teach an agent to label well with rowlab.
---

The MCP tools say what rowlab can do. The skills in
[row-and-reason/agent-skills](https://github.com/row-and-reason/agent-skills) say how to do it
well: the methodology of the [guides](/guides/labeling), written for an agent. They work in Claude
Code, Codex, Cursor and any other client that reads `SKILL.md` files.

```sh
npx skills add row-and-reason/agent-skills --skill rowlab-labeling
npx skills add row-and-reason/agent-skills --skill rowlab-model-selection
npx skills add row-and-reason/agent-skills --skill rowlab-labeling-at-scale
```

| Skill                      | When the agent uses it                                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------------------------- |
| `rowlab-labeling`          | any "label each row as…" request: define the question, try it on a few rows, run on all, check, deliver |
| `rowlab-model-selection`   | which model to use, whether a cheaper one will do, how accurate a column is                             |
| `rowlab-labeling-at-scale` | large datasets, several questions over the same rows, or a run whose estimate is more than expected     |

The skills tell the agent to report the estimate before a run on all rows, to read answers against
their rows rather than counts, and to name the datasets it made so you can look at them yourself.
