---
title: Comparing models
description: Choose a model that is good enough for the question, at the lowest cost, with the same rows asked of each.
---

The question is never "which model is best" but "which model is good enough for this question, at
what cost". Answer it with the same rows asked of two or three models, compared.

## Set up the comparison

Take a sample of 50 to 200 rows that includes the hard cases: `ORDER BY random()` with a `LIMIT`, or
a filter for the rows that matter. Run the same task on it with each candidate model, in one run, so
the result is one dataset with a column per model. Good candidates: the default for the answer type, a
cheaper one, and a decision model when the task is Classify.

When you have labels you trust (earlier annotations, a human-checked column, an observed outcome),
have them as a column of the dataset: join them to the data before adding it to rowlab.

## Read the comparison

_Compare columns_ on the dataset shows agreement between the models' columns, and accuracy against a
reference column when there is one. Agreement rates are the summary; the disagreements are the
finding. Every count comes with a `WHERE` clause: query those rows and read them. Disagreements split
into rows where the prompt is ambiguous (fix the prompt, and the models will agree), rows where one
model is wrong (count which), and rows where the reference is wrong (references are often older than
the data).

Without a reference, agreement is not accuracy: two models can agree on a wrong answer. When the
stakes warrant it, label 30 to 50 of the sampled rows by hand and use that as the reference.

## Choose

Judge quality by what the column is for. For a classifier that selects rows for a next step, the cost
of a miss is what matters: on a question that is true for 2% of rows, 98% accuracy can mean every
positive missed, so read precision and recall on the positives. For summaries, translations and other
written answers, two good answers differ in wording, so compare them with a short rubric (correct,
complete, nothing added) on a sample read by hand. A `_proba` column is only a threshold once checked
against the reference; models' own confidence is often miscalibrated.

Then choose by cost and speed among the models that meet the bar. A model that is slightly less
accurate at a tenth of the price is usually right for a first pass, with the expensive one taking the
rows it is unsure about. Prefer the decision model when it matches the LLM on the sample.
