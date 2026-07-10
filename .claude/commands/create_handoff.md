# Create Handoff Document

Create a comprehensive handoff document for transferring work between Claude sessions.

## File Location
`thoughts/shared/handoffs/YYYY-MM-DD_HH-MM-SS_description.md`

## Template

```markdown
---
date: [ISO timestamp with timezone]
researcher: Claude
git_commit: [current commit hash]
git_branch: [current branch]
repository: half-blood-prince
topic: [brief topic]
tags: [annotation-engine, pdf-rendering, epub, cli, eval, etc.]
status: [in-progress | blocked | complete]
---

# Handoff: [Description]

## Task Status

### Current Phase
[Phase X.Y: Name]

### Progress
- [x] Completed items
- [ ] In progress items
- [ ] Remaining items

## Critical References

1. `CLAUDE.md` - Full project context and known issues
2. `docs/ARCHITECTURE.md` - Technical architecture
3. [Other key files]

## Recent Changes

Files modified this session (use `file:line` syntax):
- `src/halfblood/annotation_generator.py:45-120` - Added retry logic
- `tests/test_pipeline.py:200-250` - New retry tests

## Key Learnings

### What Worked
- [Pattern or approach that succeeded]

### What Didn't Work
- [Approach that failed and why]

### Important Discoveries
- [Non-obvious finding with file:line reference]

## Artifacts Produced

- `src/halfblood/new_module.py` - Description
- `tests/test_new.py` - Test file

## Blockers (if any)

- [Blocker description]
- Required resolution: [what needs to happen]

## Action Items & Next Steps

Priority order:
1. [ ] First thing to do next
2. [ ] Second priority
3. [ ] Third priority

## Verification Commands

```bash
# Run these to verify current state
pip install -e ".[dev]"
pytest tests/ -v
ruff check src/ tests/ eval/
mypy src/halfblood/
python -c "from halfblood.cli import main; print('imports ok')"
```

## Other Notes

[Any additional context for the next session]
```

## After Creating

Run verification commands to confirm state matches documentation.

$ARGUMENTS
