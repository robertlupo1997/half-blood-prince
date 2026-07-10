---
description: Stage and commit changes with a well-crafted message
---

# Smart Commit

Create a well-structured commit from current changes.

## Process

1. Run `git status` and `git diff` to understand all changes
2. Run `git diff --cached` to see already-staged changes
3. Run `git log --oneline -5` to match commit message style
4. Group related changes logically
5. Draft a concise commit message focused on "why" not "what"
6. Present the commit plan to the user for approval
7. Stage specific files (never `git add -A` — review what's being added)
8. Create the commit

## Commit message format
```
type: concise description of why

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Types: feat, fix, refactor, style, docs, chore, test

## Safety checks
- Never commit .env files, credentials, API keys, or secrets
- Never commit __pycache__, .egg-info, dist/, build/ artifacts
- Never commit font files (fonts/*.ttf — .gitignore handles this)
- Review each file being staged — no `git add .` or `git add -A`
- Check for accidental debug prints or hardcoded test values

## Before committing
- Run `pytest tests/ -v` to verify tests pass
- Run `ruff check src/ tests/ eval/` if ruff is configured
- Confirm no regressions in existing functionality

$ARGUMENTS
