# Step 4: Wrap the Runner with neatlogs.wrap()

```python
import neatlogs
from google.adk.runners import InMemoryRunner
from google.genai import types

runner = neatlogs.wrap(InMemoryRunner(agent=assistant_agent, app_name="weather-app"))
session = await runner.session_service.create_session(app_name="weather-app", user_id="user-1")

message = types.Content(role="user", parts=[types.Part(text="weather in Paris?")])
async for event in runner.run_async(user_id="user-1", session_id=session.id, new_message=message):
    ...   # run_async stays an async generator after wrap()
```

Produces a `WORKFLOW google_adk.runner.run_async` span per invocation (token usage, output, tool calls extracted from the event stream).

## Rules
- Wrap the Runner once; use the returned reference.
- `run()` / `run_async()` remain (sync / async) generators — consume them the same way.
