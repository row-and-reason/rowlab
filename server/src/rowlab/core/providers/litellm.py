"""LiteLLM, a gateway in front of other providers: what is particular to it, beside the chat
completions every provider serves (`model_api`).

A gateway names models as its operator routes them, e.g. `openrouter/<vendor>/<model>`, so a provider
can give a prefix for rowlab's model ids. A virtual key may list no models (a wildcard route), and may
not read its own details, so a key is checked by listing models: 401 for a key LiteLLM doesn't know.
"""

from rowlab.core.providers import model_api


def check_key(base_url: str, api_key: str) -> None:
    """Raise ProviderError unless LiteLLM accepts the key."""
    model_api.get(base_url + "/v1/models", api_key)
