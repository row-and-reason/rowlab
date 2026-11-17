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

## Try on a sample

Preview the run: read each rendered prompt, and the warnings (a column that is empty for the first
rows, a placeholder that matches no column). Run on a sample in a stable order:

```sql
SELECT * FROM data ORDER BY md5('s1' || __row_id) LIMIT 50
```

The same seed (`'s1'`) gives the same rows every time, and a bigger sample (`LIMIT 200`) keeps the
smaller one, so its answers are already there and not paid for again. Read the answers next to the
rows they came from, not the counts alone. Look for rows the prompt didn't anticipate: empty cells,
another language, a row that is really two, text that contradicts itself.

To fix the prompt or the options, give the new version its own column name (`delivery_v2`) and run it
on the same sample, next to the first: answers to a different question never go in the same column.
Several variants can be tasks of one run. When the answer is a judgement rather than a fact, run a
second model on the same rows and [compare](/guides/comparing-models); the disagreements are where
the prompt is unclear. A try you no longer want is deleted from the column's menu (MCP
`answers_delete`).

## Run on all rows

Preview the same tasks without the `LIMIT`, and note the rows, the answers already there, the calls
and the cost: only the answers still missing are asked and paid for. Start the run. If the first
answers look wrong, stop it. A run that stopped or failed with the prompt right, or a done run with
failed answers, is resumed with **Continue** or **Retry failed** on its card in the Runs tab: it
asks only for what is missing.

## Check the result

Query the dataset: the share of each answer, the rows with no answer, and a handful of rows per
option read against their text. Compare the distribution with what you expect of the data: all one
value, or nearly uniform, is a reason to read more examples, not a verdict. A `_reason` column, when
the task asked for one, explains odd answers.

Then [export](/guides/exporting).

## Labels people set

People's labels are a column of the dataset too, named for them (`gold`), set on any rows, before or
after models run. No model is called, so no key is needed. A column of labels answers a task like any
other:

- **The same task the models do**, as a reference to measure them against.
- **A judgement of a model's answer**, e.g. a yes/no task "Is `delivery__jev-1.14` right for this
  review?", over the rows the model answered.

In the app, switch the right column from **Ask models** to **Label by hand** (or ⌘K → Label by hand),
pick a label column or name a new one with the task it answers, and label the rows of the current view
one at a time from the keyboard. Each label is saved as you go, and stays editable; there is no finish
step. Filter the view first to label a sample, or the rows a model answered.

Through the API, set them with `PUT /v1/datasets/{id}/labels/{column}`, up to 1,000 at a time; the
first labels in a column bring the task they answer:

```json
{ "task": { "template": "Is this review about delivery? {{review}}", "type": "yes_no" },
  "labels": [{ "row_id": 0, "value": true }] }
```

The value follows the [answer type](/how-it-works/answer-types): a boolean for yes/no, an option's
name for pick one and scale, a list of names for pick any, text for write, an object keyed by field
for extract. Null clears a label, and the last saved value wins. A batch is saved whole or not at
all. Who set each label is recorded. Labels have no `_proba` column; they query,
[compare](/guides/comparing-models) and export like any other column. Agents do the same over
[MCP](/agents/mcp) with `labels_set`.

Labels that come with the file, an earlier annotation or an observed outcome, are a column of it
already, and serve as a reference just as well.
