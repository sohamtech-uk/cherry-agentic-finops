# Step 6: flush() and shutdown()

ADK apps are usually async:
```python
if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        neatlogs.flush()
        neatlogs.shutdown()
```
Servers: init once at startup; flush/shutdown on graceful shutdown only.
