# Roadmap

**Today:** everything planned for the launch is built: datasets from files, URLs and S3; tasks that
classify, extract and write, asked of decision models and LLMs or labelled by hand; runs that stop,
resume and never pay twice; comparisons; exports; the hosted mode with organisations, sign-in, usage
and protections; MCP, the agent skill and the Python SDK; the website and the docs. What rowlab does
is described in the [docs](https://docs.rowlab.dev); how it got here is in the git history.

**Left for the launch:** `rowlab` 0.1.0 on PyPI, through the Publish workflow's trusted publishing,
and `rowlab-python-sdk` 0.1.0, through `sdk-release.yml`'s (it needs a PyPI pending publisher
first).

## Next

- **Discover → label.** An LLM proposes the categories, then a run labels with them.
- **One-click cascades.** Rows a model is unsure about go to an LLM. This is possible by hand today:
  query the low-probability rows and run again on them.
- **Provider batch APIs,** for big runs at a lower price.
- **Data processing terms for the hosted version:** a DPA, a retention policy, GDPR requests.
- **The smoke test's run step in CI,** with a low-limit OpenRouter key as a secret; until then it
  runs only locally.

## Ideas

Not planned yet; noted so they aren't lost. Add new ones here.

- **Translation APIs for Translate.** Machine translation services (e.g. DeepL, Google Translate) as
  models for the Translate preset, next to LLMs: cheaper and faster for plain translation. They'd be a
  third kind of model that only answers Write tasks started from Translate, with the target language as
  a setting rather than part of the prompt.
- **More model providers.** OpenRouter is the only provider today; Settings → Providers is where others
  would go: direct API keys for OpenAI, Anthropic, Google and the like, or a local OpenAI-compatible
  server (Ollama, vLLM) for private data. Each adds its models to the picker next to OpenRouter's.
- **More kinds of storage.** S3-compatible storage is the only remote one; Settings → Storage is where
  others would go: Google Cloud Storage, Azure Blob Storage, and maybe databases or warehouses
  (Postgres, BigQuery) as sources and destinations.
- **Other sign-in providers.** WorkOS is the only one; a generic OIDC login (Keycloak, Authentik,
  Google) would let self-hosters sign in without a WorkOS project, if they ask for it.
- **Recommended models first.** In the model picker, show a short "Recommended for <type>" group at the
  top, picked by the task's type (e.g. fast decision models for Classify, LLMs good at structured output
  for Extract), then the rest sorted as now.

## Risks and open questions

- **"JSONLD":** implemented as JSONL (one JSON object per line). JSON-LD (linked data) would need its own
  flattening step — still to be confirmed.
- **OpenRouter Decisions API is alpha.** Keeping it behind one module limits the impact of changes.
  Confirm the exact request/response fields and whether the model catalog can be filtered via the API.
- **Local secret storage** (OpenRouter key, S3 keys) is plaintext in the local data dir unless
  `ROWLAB_SECRET_KEY` is set — acceptable for a single-user local tool; always encrypted when hosted.
- **Large files:** 1M+ rows must stay responsive in the explorer and runs; test early with real data.
