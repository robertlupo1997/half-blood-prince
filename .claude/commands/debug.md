# Debug Issues

Troubleshoot issues by investigating logs, code, and git history. **Read-only investigation only.**

## Initial Response

With context: "I'll help debug issues with [topic]"
Without context: "What issue are you experiencing?"

## Investigation Resources

### 1. Code State
- Pipeline: `src/halfblood/` modules
- Tests: `tests/test_pipeline.py` (44 tests, all mocked)
- Eval: `eval/eval_harness.py`
- Fixtures: `tests/fixtures/`

### 2. Git State
- Current branch and commit
- Recent changes: `git log --oneline -10`
- Uncommitted changes: `git status`

### 3. Runtime State
- Import check: `python -c "from halfblood.cli import main; print('ok')"`
- PDF load: `python -c "from halfblood.document_processor import DocumentProcessor; dp = DocumentProcessor(); print(dp.load('tests/fixtures/potions_textbook.pdf'))"`

## Investigation Process

### Step 1: Understand the Problem
- Read relevant context
- Assess current state
- Identify what should vs does happen

### Step 2: Investigate Systematically
Deploy parallel checks:
- Review recent git changes
- Read relevant source files
- Run tests to isolate failures
- Check import chains

### Step 3: Present Findings

```markdown
## Debug Report: [Issue]

### Problem Statement
[What was reported]

### Evidence Found
- [Finding 1 with file:line or traceback excerpt]
- [Finding 2]

### Root Cause
[Most likely cause based on evidence]

### Recommended Next Steps
1. [First action]
2. [Second action]

### Additional Investigation (if needed)
- [What else to check]
```

## Constraints

- **Read-only**: Do not modify files during debug
- **Require problem description**: Can't debug without knowing what's wrong
- **Focus on evidence**: Base conclusions on actual findings

## Quick Reference Commands

```bash
# Check recent changes
git log --oneline -10
git diff HEAD~3

# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_pipeline.py -v -k "test_name"

# Check lint
ruff check src/ tests/ eval/

# Type check
mypy src/halfblood/

# Verify imports
python -c "from halfblood.cli import main; print('ok')"
python -c "from halfblood.document_processor import DocumentProcessor; print('ok')"
python -c "from halfblood.annotation_generator import AnnotationGenerator; print('ok')"
python -c "from halfblood.epub_processor import EpubProcessor; print('ok')"
python -c "from halfblood.web_preview import generate_web_preview; print('ok')"
```

$ARGUMENTS
