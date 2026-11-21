---
title: Runs
description: What a run is, what it costs, and what happens when it stops.
---

A run asks one or more questions (tasks) of the rows a SQL query selects, with one or more models,
and adds the answers to the dataset as columns. It asks only for the answers the dataset doesn't
have yet.

## Tasks

A task is a prompt, an answer type, and the models that answer it: any from rowlab's list, or any other
decision model, or LLM with structured outputs, in OpenRouter's catalog (on a server whose own key
pays, only listed ones). A run keeps its models as they were when it started, so it finishes even if
a model leaves the list or the catalog meanwhile. The prompt is the question or
instruction with the row's columns in it, as `{{column}}`; the preview renders it for the first rows
so you can read exactly what the model will see. A run can have several tasks over the same rows,
and several models per task; each model writes its own columns.

Columns are named after the task and the model: `<column>__<model>`, e.g. `team__jev-1.14`. Classify
answers come with `<column>__<model>_proba`, the probability the answer is right. With _reason_ on,
an LLM also explains its answer in `<column>__<model>_reason`.

A column name keeps its question. Starting a task whose column already holds answers to a different
prompt, options or answer type is refused, with a free name to use instead. To try a variant of a
prompt, give it its own column name and put it next to the first as another task of the same run:
both are asked of the same rows and [compare](/guides/comparing-models) directly.

## Cost

Before a run starts, the estimate says how many rows the query picks, how many answers they have
already, how many it would ask for (rows × tasks × models, less those), how many it skips because a
column the prompt uses is empty, how many failed before, and what it would cost, from each model's
price. It counts all a call sends, not just the prompt: an LLM's instructions and answer schema, a
decision model's options, and the instructions decision APIs add themselves (about 260 tokens a call;
some models add none, so for them it errs high). A finished run says what it did cost, and how many
tokens each model was billed for.

The same prompt, model and row is never paid for twice in a dataset. A run asks only for the empty
cells of its columns, so a run on all rows after a try on fifty pays only for the rest. And it keeps
each model reply with the dataset, by a hash of the model, its settings, the question and the rendered
prompt, also when the run stops or fails, so a reply paid for once is reused by any later run, even
after its answers were deleted. Only replies that could be read as an answer are kept. Deleting a
dataset deletes its replies, and a file added again is a new dataset, asked again.

## Progress and turns

A run proceeds in chunks of 500 rows. Each finished chunk is added to the dataset, so it fills in
while the run goes, and you can query it (`WHERE <column> IS NOT NULL`) to read the first answers and
stop the run if they are wrong.

On a shared server, runs take turns a chunk at a time, so one person's million rows don't block
another's twenty. An organisation can have any number of runs going, but only one at a time asks a
given model for a given column.

## Stop, fail, resume

A stopped run keeps the chunks it finished; the chunk under way is dropped, though the replies paid
for in it are kept, and cost nothing when asked again. When a runner stops or restarts under a run,
the run goes back in the queue and continues from that chunk. A run fails, with the reason shown,
when the provider refuses the key or the key is out of credits, or the provider was deleted, since
every call would fail alike; the answers so far stay. Other calls fail on their own (rate limits, a
provider error, no whole reply within 60 seconds, a reply that doesn't fit the answer type), after up to
four tries for those that may pass: the run finishes with those cells empty and counted as failed. A
stop waits for the calls under way, so it can take a few minutes with a slow model, but not forever.

To finish a run, resume it from its menu: **Continue** on a stopped or failed run, **Retry N failed**
on one that finished with failed cells. It asks for what is still missing,
the failed cells and the rows a stopped run didn't get to, never re-asks what was answered, and takes
the replies already paid for free. The resume is a run of its own, with its own rows and bill, shown
as the next attempt of the same run: the Runs tab lists each piece of work once, with its earlier
attempts and why they ended. A run's tasks are frozen
when it starts; to change the prompt, start a run with a new column name.
