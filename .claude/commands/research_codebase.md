# Research Codebase

Document existing codebase implementation without suggesting changes.

## Core Directive

**Document code AS IT EXISTS.**

Do NOT:
- Suggest improvements
- Critique implementation
- Propose enhancements
- Identify problems
- Comment on code quality

## Process

### 1. Await Query
"Ready to research the codebase. What would you like me to investigate?"

### 2. File Reading
Read all mentioned files completely before spawning agents.

### 3. Decomposition
Break research questions into focused areas:
- Component structure
- Data flow (PDF/EPUB in → annotations → rendered output)
- LLM integration patterns
- Configuration and constants
- Error handling approaches

### 4. Parallel Research
Spawn specialized agents:
- `codebase-analyzer` - Trace implementation details

### 5. Synthesis
Compile findings with precise `file:line` references.

### 6. Documentation
Save to `thoughts/shared/research/YYYY-MM-DD_topic.md`

## Output Format

```markdown
---
date: [ISO timestamp]
researcher: Claude
git_commit: [hash]
git_branch: [branch]
topic: [research topic]
tags: [annotation-engine, pdf-rendering, epub, cli, eval, etc.]
---

# Research: [Topic]

## Summary
[2-3 sentence overview]

## Findings

### [Subtopic 1]
[Description with file:line references]

### [Subtopic 2]
[Description with file:line references]

## Code References

| Component | File | Lines | Purpose |
|-----------|------|-------|---------|
| [name] | `path/file.ext` | 45-120 | [what it does] |

## Architecture

[How components connect]

## Open Questions

- [Unanswered question from research]
```

## Key Constraints

- **Documentarian only**: Describe what exists
- **Concrete references**: Include file:line for all claims
- **No recommendations**: Document, don't advise
- **Parallel execution**: Use multiple agents concurrently

$ARGUMENTS
