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

The **Compare** tab starts with the columns' α and, for three or more columns, how often they all
agree. Then comes a table of every model against the reference, or every pair without one: the match
rate with its interval in brackets, κ, and, when the models have them, calibration and cost. Select
a row for its confusion table, with precision and recall per label, and its calibration bins, or for
numbers a histogram of the differences, with the mean absolute difference, bias and error
quantiles. The confusion table counts the rows where both columns have an answer. Click a count or
a bar to see those rows in **Rows** (this replaces its search and filters); ⌘↵ shows the rows that
differ. The columns, reference, rules and selected pair are kept in the URL, so a comparison can be
shared.

Without a reference, agreement is not accuracy: two models can agree on a wrong answer. When the
stakes warrant it, [label](/guides/labeling#label-by-hand) 30 to 50 of the sampled rows by hand and
use that as the reference.

## Agreement beyond chance

Raw agreement flatters easy questions: two models that answer "no" to almost every row agree on
almost every row, whatever they read. So each pair also gets **Cohen's κ**, and the comparison as a
whole **Krippendorff's α**: 1 is full agreement, 0 is what chance would give, below 0 is worse than
chance. κ is for two columns of labels, over the rows where both have one. α takes any number of
columns, the reference included, and skips the rows with fewer than two answers, so it uses what
partly answered rows there are. Both are empty when every answer is the same, as nothing can then be
told from chance.

α weighs a difference by what the values are (`alpha_level`): numbers and dates by how far apart
they are (dates in days; the tolerance doesn't apply), the levels of a scale task by how many levels
apart, and anything else (yes/no, options, text, lists) as simply different. Values of 0.8 and up are
usually read as reliable, and below 0.67 as too unreliable to draw conclusions from.

## How sure the numbers are

Agreement rates and accuracy come with a 95% interval (Wilson's): on 10 rows, 8 right is anywhere
from 49% to 94%; on 200 rows, 160 right is 74% to 85%. When two models' intervals overlap, the sample
can't tell them apart: add rows before choosing. Precision and recall per label have no interval;
read them with their support, the rows they count.

## Calibration

A Classify answer comes with `_proba`, the model's probability that it is right. Against a
reference, the comparison checks it: the **Brier score** (mean squared difference between the
probability and being right, 0 is perfect), the **expected calibration error** (how far the
probability is from the accuracy, over ten bins of the probability), and **AUROC** (how well the
probability tells right answers from wrong ones: 1 always ranks the right ones higher, 0.5 is
chance). Each bin has its rows' accuracy and a `WHERE` clause, so a threshold can be checked and
used: the rows below 0.8, say, go to a second model or to labelling by hand.

## Cost

Each column a model wrote in a run comes with what it cost (`costs`): the run's spend on that task
and model, and per 1,000 answered rows. Cached answers were free, so a model asked again on rows it
already answered looks cheaper than it is. Against a reference, a column also gets the cost per
correct answer, the cost of an answer over its accuracy. Columns uploaded with the data or labelled
by hand have no cost.

## Matching rules

Answers match only when they are equal, unless you loosen it:

- **Ignore case** and **trim whitespace**, for text. They change what counts as the same, never the
  data.
- **A tolerance**, for numbers and dates (in days). It must be zero or more.

κ, α and calibration count matches by the same rules, except that α on numbers and dates measures
distance and ignores the tolerance.

An empty string is an answer; a null is a missing one, left out of accuracy and counted apart.
Macro F1 and balanced accuracy use all labels, even when the confusion table shows only some.

The API and MCP `columns_compare` do the same, and can compare the rows of a `SELECT` rather than
the whole dataset; the `WHERE` clauses they return apply to that query.

## Choose

Judge quality by what the column is for. For a classifier that selects rows for a next step, the cost
of a miss is what matters: on a question that is true for 2% of rows, 98% accuracy can mean every
positive missed, so read precision and recall on the positives. For summaries, translations and other
written answers, two good answers differ in wording, so compare them with a short rubric (correct,
complete, nothing added) on a sample read by hand. A `_proba` column is only a threshold once checked
against the reference, by its calibration; models' own confidence is often miscalibrated.

Then choose by cost and speed among the models that meet the bar. A model that is slightly less
accurate at a tenth of the price is usually right for a first pass, with the expensive one taking the
rows it is unsure about, by its calibrated `_proba`. Cost per correct answer puts both in one number.
Prefer the decision model when it matches the LLM on the sample.
