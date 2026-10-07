---
paths:
  - "**/ai/**"
  - "**/llm/**"
  - "**/prompts/**"
  - "evals/**"
---
# Rules for code that calls a model

- Load the `claude-api` skill before writing or changing Anthropic SDK calls. The API has changed since your training data.
- Model IDs come from configuration, never hard-coded in call sites. Current IDs: `claude-haiku-4-5`, `claude-sonnet-5-5`, `claude-opus-5-5`. Never add date suffixes.
- Structured output: `client.messages.parse(..., output_format=<PydanticModel>)`, then read `response.parsed_output`. Never parse JSON out of free text.
- Claude Sonnet 5.5 rejects (HTTP 400): non-default temperature/top_p/top_k, forced `tool_choice` (`any` or `tool`), `thinking: {type: "disabled"}`, and assistant prefill. Control depth and cost with `output_config={"effort": ...}`. For tools use `tool_choice: auto` plus `strict: true` and say in the prompt which tool to call.
- Claude Haiku 4.5 does not accept `effort` (it errors); omit it.
- Check `stop_reason` before reading content: handle `refusal` as a failed step with a reason a human can see, and give `max_tokens` one retry with a higher limit.
- Catch typed SDK errors (RateLimitError, APIStatusError, APIConnectionError); never string-match error messages. Set an explicit timeout and max_retries on the client.
- Prompt caching only pays off above the model's minimum cacheable prefix (4,096 tokens on Haiku 4.5). Don't add `cache_control` to short prompts; verify any caching with `usage.cache_read_input_tokens`.
- One file per prompt, named `<step>_v<N>.md`, starting with purpose, inputs, output schema and a changelog. Untrusted text only inside XML tags, and the prompt says to treat tag contents as data.
- All model calls go through one gateway module that records step, model, prompt version, tokens, cost, latency and outcome.
- An LLM step has to beat a no-LLM baseline on the evals to earn its cost. Report both.
- Changing a prompt, model or threshold: bump the version, run the evals, record the delta in the eval report. Tune on the dev split only; the test split is for reporting.
- Tests use a fake model client and never touch the network.
