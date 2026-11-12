---
title: Runs
description: What a run is, what it costs, and what happens when it stops.
---

A run asks one or more questions (tasks) of the rows a SQL query selects, with one or more models,
and writes the answers as columns of a new dataset.

## Tasks

A task is a prompt, an answer type, and the models that answer it. The prompt is the question or
instruction with the row's columns in it, as `{{column}}`; the preview renders it for the first rows
so you can read exactly what the model will see. A run can have several tasks over the same rows,
and several models per task; each model writes its own columns.

Columns are named after the task and the model: `<column>__<model>`, e.g. `team__jev-1.14`. Classify
answers come with `<column>__<model>_proba`, the probability the answer is right. With _reason_ on,
an LLM also explains its answer in `<column>__<model>_reason`.

## Cost

Before a run starts, the estimate says how many rows, how many calls (rows × tasks × models) and what
they cost, from each model's price. It counts all a call sends, not just the prompt: an LLM's
instructions and answer schema, a decision model's options, and the instructions decision APIs add
themselves (about 260 tokens a call; some models add none, so for them it errs high). A finished run
says what it did cost, and how many tokens each model was billed for.

The same prompt, model and row is never paid for twice in a dataset's tree: the datasets made from one
added file, through any number of runs. A run keeps each model reply with the dataset it makes, by a
hash of the model, its settings, the question and the rendered prompt, and reuses the replies of the
done runs in its tree. So a run on all rows after a try on twenty pays only for the rest; a changed
prompt, options or model is a new question. Deleting a dataset deletes the replies kept with it, and a
file added again is a new tree, asked again.

## Progress and turns

A run proceeds in chunks of 500 rows. Each finished chunk is written to the new dataset, so it fills
in while the run goes, and you can query it (`WHERE <column> IS NOT NULL`) to read the first
answers and stop the run if they are wrong.

On a shared server, runs take turns a chunk at a time, so one person's million rows don't block
another's twenty. Each organisation has `ROWLAB_RUNS_PER_ORG` runs going at once; the rest queue.

## Stop, fail, resume

A stopped run keeps the chunks it finished; the chunk under way is dropped, though the replies paid
for in it are kept until it is redone, and cost nothing then. The same goes when a runner stops or
restarts under a run: the run goes back in the queue and continues from that chunk. A run fails, with the reason shown above its rows,
when OpenRouter refuses the key or the key is out of credits, since every call would fail alike; the
rows answered so far stay. Other calls fail on their own (rate limits, a provider error, a reply that
doesn't fit the answer type): the run finishes with those rows marked failed. _Resume_ asks the
failed rows again, and continues a stopped or failed run; it never re-asks what was answered.

A run's tasks are frozen when it starts. To change the prompt, start a new run from the source
dataset.

## Manual runs

A run can be answered [by hand](/guides/labeling#label-by-hand) instead:
`POST /v1/datasets/{id}/runs` with `"method": "manual"` (the default is `"llm"`). It freezes the
tasks and rows, makes the new dataset, and waits in status `manual`. Save answers with
`PUT /v1/runs/{id}/tasks/{task_id}/answers`, up to 1,000 at a time:

```json
{ "answers": [{ "row_id": 0, "value": true }] }
```

The value follows the [answer type](/how-it-works/answer-types): a boolean for yes/no, an option's
name for pick one and scale, a list of names for pick any, text for write, an object keyed by field
for extract. Null clears an answer. The last saved value wins; a batch that was cut off may be
partly saved, so send it again. `POST /v1/runs/{id}/finish` locks the dataset, with unanswered cells
null, and is safe to repeat.
