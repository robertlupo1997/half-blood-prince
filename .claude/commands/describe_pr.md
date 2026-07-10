---
description: Generate comprehensive PR descriptions from diffs
---

# Generate PR Description

Create a thorough pull request description from the current branch's changes.

## Process

### 1. Identify the PR
- Check if current branch has a PR: `gh pr view --json url,number,title,state 2>/dev/null`
- If no PR exists, list open PRs: `gh pr list --limit 10 --json number,title,headRefName`
- Ask the user which PR to describe (or if they want to create one)

### 2. Gather Information
- Get the full diff: `gh pr diff {number}` or `git diff main...HEAD`
- Get commit history: `git log main..HEAD --oneline`
- Read changed files for full context

### 3. Analyze Changes
- Read through the entire diff carefully
- Understand the purpose and impact of each change
- Identify user-facing changes vs internal implementation
- Note breaking changes or migration requirements
- Check for test additions/modifications

### 4. Run Verification
- `pytest tests/ -v` — run full test suite
- `ruff check src/ tests/ eval/` — lint check
- Note which checks pass/fail

### 5. Generate Description

```markdown
## Summary
[1-3 bullet points: what changed and why]

## Changes

### [Category 1: e.g., "Retry Logic"]
- [Change description with file references]

### [Category 2: e.g., "Test Coverage"]
- [Change description]

## Testing
- [x] All 44 existing tests pass
- [x] New tests added for [feature]
- [ ] Manual: Verify annotation rendering on [scenario]

## Breaking Changes
[None / list of breaking changes]
```

### 6. Update the PR
- Save description to `thoughts/shared/prs/{number}_description.md`
- Update PR: `gh pr edit {number} --body-file thoughts/shared/prs/{number}_description.md`
- Confirm update was successful

## Guidelines
- Focus on "why" as much as "what"
- Be thorough but scannable
- Include breaking changes prominently
- Always attempt to run verification commands
- Note which verification steps need manual testing

$ARGUMENTS
