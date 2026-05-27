# AI Trends Source Policy

The collector should prefer stable public endpoints that can be fetched by cron
without browser state or operator-local files.

## Preferred source order

1. Official RSS or Atom feeds.
2. Official public API endpoints with documented response formats.
3. Public GitHub releases endpoints for project release signals.
4. X recent search or configured X RSS feeds only as weak signals when explicitly enabled.

## Allowed source types

| Source type | Use for | Notes |
| --- | --- | --- |
| `rss` | Official blogs and announcement feeds | Parsed into normalized `blog` raw items. |
| `atom` | Official Atom feeds | Parsed into normalized `atom` raw items. |
| `github_release` | Release notes for agent frameworks, model tooling, MCP tools, and infrastructure | Uses public release payloads; token may be used for rate limits. |
| `unitysquare_blog` | Unity Korea official UnitySquare blog list endpoint | Parsed into normalized `official_site` raw items. |
| `x_weak_signal` | Early social signals from X recent search | Never primary evidence. Requires `AI_TRENDS_X_BEARER_TOKEN`. |
| `x_rss_signal` | Early social signals from configured public RSS/Atom feeds | Never primary evidence. Requires `AI_TRENDS_X_RSS_FEEDS_JSON` or `AI_TRENDS_X_RSS_FEEDS_FILE`; no login, cookies, or scraping. |

## Active default sources

- OpenAI News RSS: `https://openai.com/news/rss.xml`
- Google AI Blog RSS: `https://blog.google/technology/ai/rss/`
- Hugging Face Blog RSS: `https://huggingface.co/blog/feed.xml`
- Microsoft AI Blog RSS: `https://blogs.microsoft.com/ai/feed/`
- NVIDIA Generative AI Blog RSS: `https://developer.nvidia.com/blog/category/generative-ai/feed/`
- Unreal Engine official Atom feed: `https://www.unrealengine.com/rss`
- Unity Square Korea Blog official list endpoint: `https://unitysquare.co.kr/growwith/unityblog/unityWebinarList?page=1&search_sort=desc`
- Hermes Agent GitHub releases: `https://api.github.com/repos/NousResearch/hermes-agent/releases`
- OpenAI Agents SDK GitHub releases: `https://api.github.com/repos/openai/openai-agents-python/releases`
- LangChain GitHub releases: `https://api.github.com/repos/langchain-ai/langchain/releases`
- LlamaIndex GitHub releases: `https://api.github.com/repos/run-llama/llama_index/releases`
- Vercel AI SDK GitHub releases: `https://api.github.com/repos/vercel/ai/releases`
- MCP TypeScript SDK GitHub releases: `https://api.github.com/repos/modelcontextprotocol/typescript-sdk/releases`
- MCP Python SDK GitHub releases: `https://api.github.com/repos/modelcontextprotocol/python-sdk/releases`
- Microsoft AutoGen GitHub releases: `https://api.github.com/repos/microsoft/autogen/releases`
- CrewAI GitHub releases: `https://api.github.com/repos/crewAIInc/crewAI/releases`
- Unity ML-Agents GitHub releases: `https://api.github.com/repos/Unity-Technologies/ml-agents/releases`
- X recent search weak signal when `AI_TRENDS_X_BEARER_TOKEN` is registered.
- X RSS weak signals when `AI_TRENDS_X_RSS_FEEDS_JSON` or `AI_TRENDS_X_RSS_FEEDS_FILE` is registered.

Do not add known failing feed URLs such as unavailable Anthropic or Mistral RSS
candidates until an official fetchable feed/API endpoint is confirmed.

## X-as-signal-only policy

X content is useful for early discovery but should not be treated as primary
evidence.

Rules:

- Keep X API collection disabled unless `AI_TRENDS_X_BEARER_TOKEN` is explicitly registered.
- Keep X RSS collection disabled unless `AI_TRENDS_X_RSS_FEEDS_JSON` or `AI_TRENDS_X_RSS_FEEDS_FILE` is explicitly registered.
- Mark X API rows with `source_type` `x_weak_signal` and tag `x-weak-signal`.
- Mark X RSS rows with `source_type` `x_rss_signal` and tag `x-rss-signal`.
- Prefer the first URL in the post as evidence; otherwise use the canonical post
  URL.
- Do not publish a high-impact claim based only on X. Confirm with an official
  blog, release note, documentation page, changelog, or public repository before
  elevating importance.
- Do not use browser scraping, logged-in cookies, exported archives, screenshots,
  or operator downloads for X collection.

## Evidence requirements

For every candidate in `raw_items`:

- `url` must be an absolute http(s) URL.
- `evidence_urls_json` must contain one or more absolute http(s) URLs.
- `published_at` must be timezone-aware.
- `summary` should be source text or a concise cleaned version of source text.
- Score columns may be blank immediately after hourly collection. Report jobs
  must include a rationale when they score an item for a digest.

## Independence requirements

Sources must be fetchable from the cron environment alone:

- No browser cookies.
- No interactive login prompts.
- No local download dependencies.
- No cache-warm assumptions.
- No workstation-specific absolute paths.
- No manual copy/paste as an input to scheduled runs.

If a source cannot satisfy these requirements, treat it as manual research input
outside the scheduled automation rather than adding it to cron collection.
