# Iterate Implementation Plan

Update an existing implementation plan with targeted, surgical edits.

## Process

### 1. Parse Input
Identify:
- Plan file path
- Requested changes

If missing, prompt for specific information.

### 2. Research If Needed
Only spawn research tasks when changes require new technical understanding:
- `codebase-analyzer` - Find affected modules
- `web-search-researcher` - Research external APIs/libraries

### 3. Present Understanding
Before making changes, confirm:
- What the current plan says
- What the requested change is
- How it affects other parts of the plan

### 4. Update the Plan
Make surgical edits:
- Maintain existing structure
- Update only affected sections
- Keep success criteria measurable
- Preserve completed checkmarks

### 5. Review Changes
Present:
- What was changed
- What was preserved
- Any new dependencies or risks

## Key Principles

- **Be skeptical**: Question vague feedback, verify feasibility
- **Be surgical**: Precise edits, not wholesale rewrites
- **Research only what's needed**: Don't over-investigate
- **Confirm understanding**: Before modifying
- **Maintain quality**: Success criteria must be testable

## Success Criteria Structure

Always maintain two categories:

**Automated Verification**:
- Tests pass: `pytest tests/ -v`
- Lint clean: `ruff check src/ tests/ eval/`
- Types check: `mypy src/halfblood/`
- Imports work: `python -c "from halfblood.cli import main"`

**Manual Verification**:
- PDF annotation rendering quality
- EPUB roundtrip fidelity
- Web preview functionality
- Font fallback behavior

$ARGUMENTS
