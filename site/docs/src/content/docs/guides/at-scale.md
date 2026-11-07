---
title: Labeling at scale
description: Label a large dataset without paying for more model calls than the question needs.
---

Cost is calls times price. Cut the calls before cutting the price: ask the expensive question only
of the rows it applies to, ask related questions together, and never ask twice.

## Cascade

Most questions apply to a subset of the rows. Find that subset with a cheap first pass, then run the
expensive task only on it. A decision model, or a short yes/no prompt on a small LLM, makes a good
first pass: "Is this review about delivery?" over a million rows, then "What went wrong with the
delivery?" over the 4% that are. The second run's SQL is a filter on the first run's column:

```sql
SELECT * FROM data WHERE "delivery__jev-1.14" = true
```

Check the first pass on a sample before trusting it ([Comparing models](/guides/comparing-models)):
a first pass that misses rows loses them for good.

## Ask once

Several facts from the same rows go in one Extract task with several fields: one call answers them
all. Separate tasks are each a call per row and model.

The same prompt and model on the same row is never paid for twice, so iterate on a sample before the
full run, and resume a stopped or failed run rather than starting a new one. When the data grows, add
the new rows as a new dataset (a file of just them, with a stable id), run on it, and join the
results to the earlier ones where you keep your data.

## Estimate and agree

Preview the full run and look at the rows, calls and cost before starting it. Prefer two passes that
cost a tenth to one pass that is slightly more accurate, unless accuracy is what matters.

## Run and watch

A run on a million rows takes hours, and its dataset fills in a chunk of 500 rows at a time: sample
the answers early (`WHERE <column> IS NOT NULL`) and stop the run if they are wrong, before the
budget is spent.
Some answers fail at scale (rate limits, provider errors, unusable replies); when the run is done,
resume it once to ask them again, then see what is still missing.
