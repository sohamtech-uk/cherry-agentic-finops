# Span kinds (Google ADK)

`neatlogs.wrap(runner)` emits:
- **WORKFLOW** — `runner.run` / `run_async` per invocation (token usage, output, tool calls from the event stream)

Your own code: `@neatlogs.span(kind="WORKFLOW"|"CHAIN"|...)`.
