# Step 2: Add neatlogs.init()

1. Find the entry point.
2. Add `import os`, `import neatlogs`; `load_dotenv()` before init.
3. Call `init()` BEFORE importing `google.adk`.

```python
import os
import neatlogs
from dotenv import load_dotenv

load_dotenv()
neatlogs.init(api_key=os.getenv("NEATLOGS_API_KEY"), workflow_name="my-adk-app")

from google.adk.runners import InMemoryRunner   # after init
```

## NOTE
No `instrumentations=[...]` needed — `neatlogs.wrap(runner)` installs the hooks.
