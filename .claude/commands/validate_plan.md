# Validate Plan Implementation

Verify that an implementation plan was correctly executed by checking success criteria and identifying deviations.

## Process

### 1. Context Discovery
- Locate the implementation plan
- Determine current phase
- Gather evidence through git analysis and test execution

### 2. Systematic Validation

For each phase, check:
- [ ] Completion status (files exist, code implemented)
- [ ] Automated verifications pass
- [ ] Manual criteria can be assessed
- [ ] Edge cases considered

**Think deeply about edge cases:**
- Were error conditions handled?
- Are there missing validations?
- Does the implementation match the spec?

### 3. Report Generation

```markdown
## Validation Report: [Phase X.Y]

### Summary
[Brief overall assessment]

### Matches Plan
- [x] Feature X implemented as specified
- [x] Tests pass for component Y

### Deviations
- [ ] Expected Z, found W instead
  - Impact: [description]
  - Recommendation: [action]

### Potential Issues
- [Issue description with file:line reference]

### Manual Testing Required
- [ ] Verify annotation rendering on dense PDFs
- [ ] Test EPUB roundtrip in reader app
- [ ] Check web preview dark mode toggle

### Verdict
[PASS / FAIL / PARTIAL]
```

## Validation Checklist

Before declaring success:
- [ ] All automated checks pass (`pytest`, `ruff`, `mypy`)
- [ ] No regressions in existing 44 tests
- [ ] Documentation updated if needed
- [ ] Clear testing steps documented
- [ ] Code follows existing patterns (Pydantic models, Click CLI, PyMuPDF rendering)

## Workflow

```
create_plan → implement_plan → validate_plan → [fix issues] → validate_plan
```

$ARGUMENTS
