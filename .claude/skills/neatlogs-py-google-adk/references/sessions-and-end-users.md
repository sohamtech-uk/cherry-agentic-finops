# Sessions & End-Users

Lineage is modeled with `parent_session_id`. Application-specific session data is
not hardcoded into SDK parameters: pass any JSON-compatible keys through
`session_custom_fields={...}`. The SDK stores that object as
`neatlogs.session.custom_fields` on the root span. For example:

```python
with neatlogs.identify(
    session_id="child_123",
    parent_session_id="parent_456",
    session_custom_fields={"feature_name": "chat", "entry_point": "slack", "tenant": "acme"},
    end_user_id="u_456",
):
    run_turn()
```


Attach an **observability session** and an **end-user identity** to ADK runs so the dashboard can group multi-turn conversations and slice analytics by your customers' users (retention, per-user cost, per-plan usage).

## Model

- `init()` takes NO session/end-user params — its `user_id` is the SDK OPERATOR (you), not your customers.
- Identity is bound per run with `neatlogs.identify(...)`, the wrapper-only path for `neatlogs.wrap(runner)`.
- **One turn = one trace.** An observability session groups turns → pass the **SAME** `session_id` on every turn of a conversation.
- **End-user per session.** Set `end_user_id` (+ optional `end_user_metadata`) once per session.
- **Root-only.** You bind identity around the run; ADK's own root/passthrough spans inherit it via the span processor (neatlogs>=1.4.2). The backend rolls it up — no per-span tagging.

### Two different "sessions" — don't confuse them

ADK has its OWN `session_id` (the runner session) for conversation **STATE / memory**. Neatlogs `identify(session_id=...)` is the **OBSERVABILITY** session used for trace grouping in the dashboard. They are unrelated concepts; reuse the ADK session id as the neatlogs session id only if it happens to be convenient — they are passed to different APIs.

## Multi-turn example

```python
import neatlogs
from google.adk.runners import InMemoryRunner
from google.genai import types

runner = neatlogs.wrap(InMemoryRunner(agent=assistant_agent, app_name="weather-app"))
adk_session = runner.session_service.create_session(app_name="weather-app", user_id="user-1")

conv_id = "conv_123"  # ONE observability session for the whole conversation

for text in ["weather in Paris?", "and tomorrow?", "pack an umbrella?"]:
    message = types.Content(role="user", parts=[types.Part(text=text)])
    # bind identity around EACH turn; same session_id every turn groups them
    with neatlogs.identify(
        session_id=conv_id,
        end_user_id="u_456",
        end_user_metadata={"plan": "pro"},
    ):
        for event in runner.run(
            user_id="user-1",             # ADK runner user (operator-side)
            session_id=adk_session.id,    # ADK STATE session — separate concept
            new_message=message,
        ):
            ...   # each turn = one trace, all sharing observability session conv_123
```

`run_async()` works the same way — wrap the `async for` loop in `with neatlogs.identify(...)`.

## Dashboard

Filter traces by `session_id` to view a full conversation, or by `end_user_id` / `end_user_metadata` (e.g. `plan=pro`) to slice analytics per customer user.
