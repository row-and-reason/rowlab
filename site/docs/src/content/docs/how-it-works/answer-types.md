---
title: Answer types
description: Classify, extract or write, and which models can answer each.
---

Pick the narrowest type that holds the answer. A narrow type is cheaper, easier to check, and lets a
decision model do the work.

## Classify

Puts the row in a known box. Any model answers these, each answer with a probability (0 to 1) that
it is right; decision models return it, LLMs are asked for it.

| Type     | Answer                | Columns                                                            |
| -------- | --------------------- | ------------------------------------------------------------------ |
| Yes/no   | `true` or `false`     | `<column>__<model>`, `_proba`                                      |
| Pick one | one of the options    | the option's name, `_proba`                                        |
| Pick any | any of the options    | one `true`/`false` column per option: `<column>_<option>__<model>` |
| Scale    | one of ordered levels | the level's name, `_proba`                                         |

Options have a name and, when the name alone could be read two ways, a description. A scale's
options are its levels, listed lowest first (`low`, `medium`, `high`), and the answer is one of
them, not a number. Options must
cover every row: add _not applicable_ or _can't tell_ when the question doesn't apply to some rows,
so the model never has to guess.

## Extract

Pulls typed facts out of the row. LLMs only. Fields have a name, a type (text, number, boolean,
date, list, or nested items) and a description; a field is empty when the text doesn't say. One field
makes one column; several make `<column>_<field>__<model>` each. Several facts from the same rows
belong in one extract task: one call answers them all.

## Write

Produces new text from the row: a summary, a translation, a rewrite. LLMs only. The column holds the
text.

## Models

Models come from OpenRouter, and are picked by name per task. Two kinds:

- **Decision models** (such as `typesafe/jev-1.14`, the default) answer Classify questions fast and
  cheaply, and are often as good as an LLM on clear-cut questions.
- **LLMs** (the default is `anthropic/claude-haiku-5.5`) answer everything, and are needed for
  Extract and Write.

Run two or three on the same rows and [compare](/guides/comparing-models) before choosing.
