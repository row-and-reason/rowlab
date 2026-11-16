---
title: Self-hosted models
description: Ask open-weight models and fine-tuned checkpoints you serve yourself, as columns beside catalog models.
---

A model doesn't have to be on OpenRouter for rowlab to ask it. An open-weight model on a GPU you
rent, or the checkpoints of one you fine-tune, can be added as your organisation's own models. Their
answers are columns of the dataset like any other model's: the same question asked the same way, the
same yes/no and probability, the same [comparison](/guides/comparing-models). Each answers through
its own provider, so one run can mix them with catalog models, and nobody else's runs change.

## Serve the model

rowlab speaks two decision APIs, and which one a model needs depends on the model:

| Provider type         | Endpoint            | Answers                                                                                       |
| --------------------- | ------------------- | --------------------------------------------------------------------------------------------- |
| **System One**        | `POST /v1/systemone` | dedicated decision models (Clef, D3, Kev, Laya), and generic models on vLLM                   |
| **OpenAI-compatible** | `POST /v1/decisions` | generic models on vLLM, LoRA adapters on vLLM, and anything behind a LiteLLM gateway          |

[vLLM](https://docs.vllm.ai/en/latest/models/structured_decisions_models/) serves both. Tested with
vLLM 0.33.0:

```sh
uv pip install vllm==0.33.0
# A dedicated decision model: add its provider as System One.
vllm serve vllm-sr/d3-mini --max-model-len 16384 --logprobs-mode raw_logprobs \
  --api-key "$KEY" --port 8000
# A generic model with LoRA checkpoints, each under its own name: add it as OpenAI-compatible.
vllm serve Qwen/Qwen3.5-4B-Base --max-model-len 16384 --logprobs-mode raw_logprobs \
  --api-key "$KEY" --port 8000 \
  --enable-lora --max-lora-rank 16 --lora-modules step-1000=./ckpt/1000 step-2000=./ckpt/2000
```

Some decision models come with a server of their own, which speaks System One: Kev's
(`python -m kev.serve`, with `KEV_API_KEY`) and Laya's (`laya-serve`, with `LAYA_API_KEY`). A model
whose answers come from a head of its own, as Kev's do, is only itself on its own server: loaded as
a LoRA adapter in vLLM, it answers with the base model's next-token probabilities instead.

Wait for the server to be up before you start a run: vLLM takes from two to six minutes to load a
model, most of it compiling on the first start.

## Give it an address

rowlab calls the server, so it needs an address rowlab can reach, and the server needs a key
(vLLM's `--api-key`), which rowlab sends with every call:

- **rowlab on your own machine** reaches anything your machine does, `http://` too: a server on your
  network, or a rented GPU's port forwarded over SSH (`ssh -L 8000:localhost:8000 gpu`) as
  `http://localhost:8000`.
- **A hosted rowlab, such as rowlab.dev,** needs a public `https://` address, so the key never
  travels in clear. Any of these gives one:
  - **Runpod** gives each exposed HTTP port one: `https://<pod-id>-8000.proxy.runpod.net`.
  - **A Cloudflare quick tunnel**, from any machine and without an account:
    `cloudflared tunnel --url http://localhost:8000` prints an `https://….trycloudflare.com`
    address. It changes when the tunnel restarts; a named tunnel on your own domain keeps one.
  - **A reverse proxy** with a certificate in front of vLLM, such as Caddy.

  rowlab.dev reaches public servers on port 443 and on ports 1024 to 65535, so HTTPS on the
  server's own port works too. A hosted rowlab reaches private addresses only on hosts its operator
  names in [`ROWLAB_PRIVATE_HOSTS`](/self-host/configuration#private-hosts).

## Add it to rowlab

An admin adds the server as a provider in **Settings → Providers**: its type, its address (e.g.
`https://abc123-8000.proxy.runpod.net`) and the key it was started with. Then anyone who can run tasks adds
models to it, from the provider's menu (**Add model**), the SDK or an agent:

- **Id**: what answer columns and comparisons show, e.g. `fallacy-ft-step-2000`. Lowercase letters,
  digits, `.`, `_` and `-`.
- **Served as**: the name the server gives it: vLLM's model name, `--served-model-name`, or the name
  in `--lora-modules`.
- **Kind**: decision model or LLM.
- **Note**: what answers, in words you'll understand months later: the base model and its revision,
  the training run, the step.
- **Prices**: leave them empty for a GPU paid by the hour. Estimates and runs show its cost as not
  priced rather than as $0, and **Settings → Usage** counts its answers and tokens, at no cost.

The model is asked one short question before it is added, so a wrong name, key or provider type is
caught then, not in the middle of a run.

## Checkpoints from a training script

Register each checkpoint as it is saved and score it like any other model:

```python
from rowlab_sdk import Client, Task

rl = Client()
fallacy = Task(template="Does this argument contain a logical fallacy? {{text}}", column="fallacy")
for step in (1000, 2000, 3000):
    ckpt = rl.models.create(
        f"fallacy-ft-step-{step}",
        provider="gpu",  # the provider's name in Settings
        upstream=f"step-{step}",  # its --lora-modules name
        note=f"Qwen/Qwen3.5-4B-Base + LoRA, run 7, step {step}",
    )
    run = rl.runs.create(dataset_id, fallacy.model_copy(update={"models": [ckpt.id]}))
    rl.runs.wait(run.id)
```

Creating a model that is already there, with the same provider, served name and kind, returns it,
so a script can run again after a crash; one deleted by mistake comes back the same way. An agent
does the same with the `model_add` tool, and changes a model's note or prices with `model_update`.

## What stays fixed

A column has to say which weights answered long after the server is gone, so a model's id stands for
one thing:

- **Its provider, served name and kind never change.** Its note and prices can. For other weights,
  add another model.
- **A deleted model's id goes to no other model.** Its answers stay in the datasets, and replies
  kept for it would otherwise be given to the new weights. Adding the same model again brings it
  back.
- **Replies are kept by rowlab's id, not the served name.** Two checkpoints served as `fallacy-ft`
  one after the other are two models, never each other's answers.

What rowlab can't check is the server itself: a server restarted with other weights under the same
name answers as the same model. Give each checkpoint its own served name, and record the weights in
the note.

## When the server moves or stops

A rented GPU's address changes each time. When a run can't reach its model's server at all, it
stops and says so, rather than filling the rest of the rows with failures. Start the server again,
change the provider's base URL in **Settings → Providers** (with its key entered again, as a key
goes only to the address it was saved for), and start the run again: it asks only for the answers
it didn't get. A stable name for the GPU, from a tunnel or your own DNS, saves changing the
address.

## Comparing fairly

- **One endpoint for one series.** The two endpoints frame the question differently, and give
  different probabilities for the same model and text (0.65 against 0.92 in one test). Compare a
  base model and its checkpoints through the same one: OpenAI-compatible, since vLLM 0.33's
  `/v1/systemone` ignores LoRA adapters.
- **Where the probability comes from.** A dedicated decision model reads it from a head trained for
  it. A generic model's comes from its next-token probabilities for the answer's labels, which
  aren't calibrated. Say which in the note; compare calibration with that in mind.

## Calls at once

rowlab makes up to 16 calls at a time per run (`ROWLAB_RUNNER_CALLS`). vLLM queues what it can't
take at once; Laya refuses more than 16 in flight (`LAYA_MAX_CONCURRENT`), which rowlab retries, so
raise it if several runs ask it at once.
