# Implement Plan

Execute an implementation plan from `thoughts/shared/plans/` or a specified file.

## Process

### 1. Load Context
- Read the plan file completely, noting any existing checkmarks
- Review all referenced files without truncation
- Understand how components interconnect
- Create a todo list for tracking

### 2. Implementation Approach

**Follow the plan's intent while adapting to what you find.**

Plans guide work, but use judgment when reality diverges from expectations.

When issues arise, stop and articulate:
- Expected vs actual state
- Why the discrepancy matters
- Request guidance on proceeding

### 3. Verification Process

After each phase:
1. Run automated checks (tests, lint, type check)
2. Pause and notify human with format:

```
## Phase [X.Y] Complete

### Automated Verification
- [x] `pytest tests/ -v` - All tests pass
- [x] `ruff check src/ tests/ eval/` - No lint errors
- [x] `mypy src/halfblood/` - No type errors

### Manual Verification Required
- [ ] Verify annotation rendering looks correct
- [ ] Check connector arrows point to right targets

Ready to proceed to Phase [X.Z]?
```

3. Only proceed after manual verification confirmed

### 4. Resuming Work
- Trust completed checkmarks
- Begin at first unchecked item
- Resume momentum without re-verifying prior work unless issues arise

## Quick Reference Commands

```bash
# Install
pip install -e ".[dev]"

# Tests
pytest tests/ -v

# Lint
ruff check src/ tests/ eval/

# Type check
mypy src/halfblood/

# Smoke test
python -c "from halfblood.cli import main; print('imports ok')"

# Quick PDF test (no API key)
python -c "
from halfblood.document_processor import DocumentProcessor
dp = DocumentProcessor()
pages = dp.load('tests/fixtures/potions_textbook.pdf')
print(f'{len(pages)} pages loaded')
"

# Full annotate (needs ANTHROPIC_API_KEY)
halfblood annotate tests/fixtures/potions_textbook.pdf -o /tmp/annotated.pdf --pages 1-3

# Eval (needs ANTHROPIC_API_KEY)
python eval/eval_harness.py --list
python eval/eval_harness.py
```

$ARGUMENTS
