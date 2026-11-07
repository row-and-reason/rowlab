---
title: Labeling
description: Turn a request into a question per row, try it, read the answers, then run on all rows.
---

The workflow is the same whatever the question: turn the request into one question per row with an
answer of a fixed type, ask it of a few rows, read the answers against the rows, then ask it of all
rows.

## Define the question

State what one row is, and what the column must say about it. Pick the narrowest
[answer type](/how-it-works/answer-types) that holds the answer. A question that needs two answers
is two tasks, run together on the same rows. Make the options cover every row.

Read the dataset first, its profile included, and write the prompt from the row's columns, by name.
Say what the model is looking at ("a customer review of a kitchen product") and what each option
means when the words alone could be read two ways. Put a long or variable text last.

## Try on a few rows

Preview the run: read each rendered prompt, and the warnings (a column that is empty for the first
rows, a placeholder that matches no column). Run on about twenty rows (`LIMIT 20`) and read the
answers next to the rows they came from, not the counts alone. Look for rows the prompt didn't
anticipate: empty cells, another language, a row that is really two, text that contradicts itself.
Fix the prompt or the options and run again from the source dataset. Twenty rows cost little either
way.

When the answer is a judgement rather than a fact, run a second model on the same rows and
[compare](/guides/comparing-models); the disagreements are where the prompt is unclear.

## Run on all rows

Preview again for the full query, from the source dataset, and note the rows, calls and cost. Start
the run. If the first answers look wrong, stop it and start a new run with the fixed prompt. Resume is
for runs that stopped or failed with the prompt right, and for a done run's failed rows.

## Check the result

Query the finished dataset: the share of each answer, the rows with no answer, and a handful of rows
per option read against their text. Compare the distribution with what you expect of the data: all one
value, or nearly uniform, is a reason to read more examples, not a verdict. A `_reason` column, when
the task asked for one, explains odd answers.

Then [export](/guides/exporting).
