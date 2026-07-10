# Create Implementation Plan

Create a detailed technical implementation plan through iterative research and collaboration.

## Process

### 1. Initial Response
If no task provided, ask for:
- Task description
- Context and constraints
- Relevant resources or files

If a file path or task is given, begin reading and analysis immediately.

### 2. Context Gathering
- Read all mentioned files completely (no truncation)
- Spawn parallel research agents:
  - `codebase-analyzer` - Understand implementation patterns
  - `web-search-researcher` - Research libraries or APIs if needed
- Review `CLAUDE.md` for known issues and improvement areas
- Review `docs/ARCHITECTURE.md` for technical constraints

### 3. Research & Discovery
After clarifications:
- Create a research todo list
- Spawn concurrent sub-tasks investigating different aspects
- Verify all findings against actual code before presenting options

### 4. Plan Development
Create an outlined structure for feedback, then write detailed plan to `thoughts/shared/plans/` using format:

```markdown
# [Plan Title]

## Overview
Brief description of what we're building and why.

## Current State
What exists now (with file:line references).

## Desired End State
What success looks like.

## Implementation Phases

### Phase X.Y: [Name]
**Overview**: What this phase accomplishes

**Changes Required**:
1. **File**: `path/to/file.ext`
   - Change description
   - Code snippets if helpful

**Success Criteria**:
- [ ] Automated: `command to run`
- [ ] Manual: Human verification step

## Dependencies
What must exist before starting.

## Risks & Mitigations
Potential issues and how to handle them.
```

### 5. Sync & Iteration
- Save plan with naming: `YYYY-MM-DD_description.md`
- Iterate based on feedback until complete

## Guidelines

- **Be thorough**: Read entire files, research actual code patterns
- **Separate verification**: Automated (tests, lint) vs Manual (UI, rendering)
- **No open questions**: Every decision resolved before finalizing
- **Be skeptical**: Question requirements, verify against codebase
- **Practical focus**: Incremental, testable changes

## Project-Specific Context

Key modules (read before planning changes):
- `src/halfblood/models.py` - Shared data models
- `src/halfblood/annotation_generator.py` - LLM integration
- `src/halfblood/document_processor.py` - PDF rendering engine
- `src/halfblood/epub_processor.py` - EPUB rendering
- `src/halfblood/web_preview.py` - HTML viewer
- `src/halfblood/cli.py` - CLI glue layer
- `eval/eval_harness.py` - Quality evaluation

$ARGUMENTS
