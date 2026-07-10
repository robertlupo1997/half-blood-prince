---
description: Review uncommitted changes before committing
---

# Local Code Review

Review all staged and unstaged changes in the current branch.

## Process

1. Run `git diff` to see all unstaged changes
2. Run `git diff --cached` to see staged changes
3. Run `git status` to see untracked files
4. Run `pytest tests/ -v` to verify tests still pass

## Review Checklist

For each changed file:

### General
- [ ] Changes match intended purpose
- [ ] No accidental debug code (print statements, breakpoints)
- [ ] No hardcoded values that should be configurable
- [ ] No TODO/FIXME left unresolved from this change

### Security
- [ ] No exposed API keys, secrets, or credentials
- [ ] No raw user/LLM input passed unsanitized to file operations
- [ ] `html.escape` used for all user-provided text in web_preview.py
- [ ] No new XSS vectors in HTML generation

### Python Quality
- [ ] Type annotations on public method signatures
- [ ] No bare `except Exception` (unless intentional with comment)
- [ ] No unused imports
- [ ] Error messages are actionable (not just "error occurred")

### Project-Specific
- [ ] PDF rendering: annotations don't overflow page boundaries
- [ ] EPUB processing: CSS injection doesn't break reader compatibility
- [ ] LLM prompts: tool schema matches Pydantic model
- [ ] Font handling: fallback path works without Caveat font
- [ ] Test coverage: new functionality has corresponding tests
- [ ] Annotation types: any new types added to AnnotationType enum

### Dependencies
- [ ] No new dependencies without discussion
- [ ] pyproject.toml updated if dependencies changed
- [ ] Version constraints are reasonable (not overly broad)

## Output

```
## Local Review Summary

### Changes Reviewed
- `file.py` — [summary of changes]

### Issues Found
- [issue with file:line reference]

### Approved
- [changes that look good]

### Test Results
- pytest: [pass/fail with details]
- ruff: [clean/issues]

### Recommendation
[commit / fix issues first / needs discussion]
```

$ARGUMENTS
