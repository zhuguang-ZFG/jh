# Project Coding Guidelines

## Session Startup — Mandatory

Every new session MUST load cross-session memory from evo_server first:

```bash
python D:/jh/hooks/evo_hook_startup.py
```

This injects accumulated skills, patterns, failures, and memories from past sessions.
Run this BEFORE answering the user's first substantive question.
If the VPS is unreachable, continue without it (don't block the session).

---

## Auto-Generated Guidelines

> Generated from 12 sessions, 50 skills, 25 patterns
> Last updated: 2026-05-28 01:30

## Active Domains

- **general**: 8 successful sessions
- **python**: 3 successful sessions

## Known Failure Patterns (Avoid These)

- 0 files touched, 0 new, 0 edits, 0 commands; Modified: github_learner.py, main.py, telegram_bot.py, evolution_engine.py

## Proven Techniques (Use These)

- Created evo-server with FastAPI
- All done, task completed successfully.
- FastAPI POST endpoints must use Body() for JSON body; Windows GBK cant handle emoji in hook output; failures/relevant must be POST not GET; skill extr
- 46 files, 477 commands, 837 tool calls
- 46 files, 485 commands, 846 tool calls

## Key Skills (by confidence)

- **test_skill_extraction** [python]: weight=1.00
- **fastapi_json_body** [python]: weight=1.00
- **hook_unicode_safety** [python]: weight=1.00
- **pretooluse_hook_pattern** [python]: weight=1.00
- **git_commit_pattern_extraction** [python]: weight=1.00
- **dependency_aware_editing** [python]: weight=1.00
- **convention_extractor** [python]: weight=1.00
- **scp_deploy_vps** [devops]: weight=1.00
- **sqlite_wal_migration** [python]: weight=1.00
- **evolution_engine_dual_path** [python]: weight=1.00

## Learned Code Patterns

- **api_route_get** [general]: API route: app.get('*', async (c) => {
- **class_shimserver_pattern** [general]: Class ShimServer with methods: def app
- **class_clientdisconnected_pattern** [general]: Class ClientDisconnected with methods: def _log_incoming_request
- **class_shimmodel_pattern** [general]: Class ShimModel with methods: def is_anthropic, def is_openai_chat
- **class_modelsettings_pattern** [general]: Class ModelSettings with methods: def load
- **class_fakeupstream_pattern** [testing]: Class FakeUpstream with methods: def release
- **class_modelsettingsfixture_pattern** [testing]: Class ModelSettingsFixture with methods: def one
- **class__adaptivelimiter_pattern** [general]: Class _AdaptiveLimiter with methods: def acquire

## Code Quality Trends

- Average quality score: 90/100

## Language-Specific Notes

### Python

- Use `typing.List`, `typing.Dict` for Python 3.6 compat
- Prefer `Optional[X]` over `X | None`

### txt


## Project Rules

- [llm_sync] [{"category": "Web Development", "summary": "Learn advanced FastAPI features such as dependency injection, custom middleware, and OpenAPI customizatio
