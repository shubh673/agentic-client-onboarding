"""Stage agents.

One module per stage. Each module exposes an `Agent` class with an async
`run(...)` method that returns a structured result dict and emits log
entries via an injected callback. The shape mirrors the LangGraph reference
in `C:/Users/artlptp258user/Desktop/Project/agent` but **without** any LLM
call — the orchestration here is plain Python so it stays deterministic.
"""
