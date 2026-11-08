---
title: Your data on app.rowlab.dev
description: Where the hosted version keeps your data, what deleting removes, and which services see what.
---

This page is about the hosted version at [app.rowlab.dev](https://app.rowlab.dev), run by
[Row & Reason](https://rowandreason.com). When you run rowlab yourself, your data stays where you put
it.

## Where it lives

On Row & Reason's own servers. A dataset's rows are kept as Parquet files in object storage, a copy
of the file or source you added; your original is never changed. Everything else is in a Postgres
database: your organisation and its members, the datasets' names and columns, runs with their
prompts, the model replies, how much each run used, and saved OpenRouter keys and S3 credentials,
which are encrypted.

Each organisation's data is its own. Nobody in another organisation sees it, and a model reply is
reused only within the organisation that paid for it.

## Deleting

Deleting a dataset removes its files, the model replies its run kept with them, and the run that
made it, straight away. Datasets made from it stay, with the replies they used. What stays after it:

- **Usage**: how many answers, tokens and dollars a run used, per task, model and day, for
  **Settings → Usage**. No rows.
- **Backups** of the database, for 7 days.

Dataset files themselves aren't backed up: a deleted dataset can't be brought back, and neither can
files lost if the storage fails. Keep your originals.

To delete your organisation or account and everything in it, email
[support@rowandreason.com](mailto:support@rowandreason.com) from the address you sign in with.

## Who else sees it

- **OpenRouter and the model you pick** get, for each row a run asks about, the prompt with that
  row's columns, sent with your OpenRouter key. What they keep is set by
  [OpenRouter's terms](https://openrouter.ai/terms) and your account's privacy settings there.
- **WorkOS** signs you in, so it has your name and email.
- **Cloudflare** carries every request to and from rowlab.dev, and protects it from abuse.
- **PostHog** (EU) gets product analytics from the web app: the pages you open and what you click,
  as you and your organisation. Text on the page, so rows, prompts and answers, is never sent.

Row & Reason doesn't sell your data or train models on it. Exports go only where you send them.
