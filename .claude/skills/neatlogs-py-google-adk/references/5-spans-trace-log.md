# Step 5: Combine wrap() with @span / trace / log

Use the manual primitives for YOUR orchestration code. The wrapped runner's span nests under whatever span is active.

## Don't add a span just to bracket one runner invocation

Building the message and consuming the `run_async` event stream is still a SINGLE runner invocation — the wrapped runner already emits its own span for it. A `@neatlogs.span(kind="CHAIN")` around just that is an empty layer. Log inside the WORKFLOW and let the runner span nest directly under it.

```python
import neatlogs
from google.genai import types

@neatlogs.span(kind="WORKFLOW", name="session")
async def main():
    runner = neatlogs.wrap(InMemoryRunner(agent=agent, app_name="app"))
    for text in questions:
        neatlogs.log("query: {q}", q=text)
        message = types.Content(role="user", parts=[types.Part(text=text)])
        async for event in runner.run_async(user_id="user-1", session_id=sid, new_message=message):
            ...                      # runner span nests under WORKFLOW
```

Hierarchy: `WORKFLOW(session) > WORKFLOW(google_adk.runner.run_async) > AGENT/LLM/TOOL`.

## Use CHAIN only for REAL multi-step work

`kind="CHAIN"` is correct when YOUR function chains several stages around the runner call — e.g. pre-fetch data, run the agent, then post-process the collected output:

```python
@neatlogs.span(kind="CHAIN", name="answer_and_store")
async def answer_and_store(runner, sid, text):
    ctx = await fetch_context(text)      # step 1
    final = await run_agent(runner, sid, f"{ctx}\n\n{text}")  # step 2 (runner span nests here)
    await store_result(text, final)      # step 3
    return final
```

If the function only builds a message and drains the event stream, don't wrap it in its own span.

- `@neatlogs.span(kind="WORKFLOW")` — the user-facing entry point.
- `@neatlogs.span(kind="CHAIN")` — YOUR functions that chain several real steps, not a single runner call.
- `@neatlogs.span(kind="EVALUATOR"|"MEMORY")` — an ordinary application-owned evaluator or memory function; evaluator function input/output and errors are captured automatically.
- `neatlogs.trace("name", kind=...)` — the sole span for the only kinds `@span` rejects (`LLM`, `RERANKER`, and `VECTOR_STORE`), or for a raw/custom operation with no decorator boundary or direct canonical metadata needs (for example, a DeepEval callback); never a second layer for the same operation.
- `neatlogs.log("msg {k}", k=v)` — steps inside a span.
