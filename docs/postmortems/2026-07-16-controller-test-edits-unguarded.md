---
date: 2026-07-16
severity: A-SEV3
status: closed
owner: Trey Lupo
project: half-blood-prince
task_tier: T2
incident_window: 2026-07-15 21:30 EDT – 2026-07-16 10:00 EDT
detected_by: advisor (out-of-band reviewer), on a second pass after the gate + Opus review passed
---

# Controller-authored test defects escaped the loop's guards twice; nothing reviews the controller's own tests

## Summary
The `/goal` loop makes the controller author the failing tests that define "correct," while
Codex only implements against them. Twice this session a controller-authored test was itself
defective. On P1-T9a a non-hermetic test **merged to `main`** after both the gate and a CLEAN
Opus review passed; on P2-T1 a regression test asserted a *mathematically impossible* property
during the fix loop. Both were caught by the out-of-band advisor, not by any loop mechanism.
Actual loss was small (both caught the same session, no external harm), but the guard gap is
real and recurred, which is why this is a postmortem rather than a retro.

## Impact and severity
- Human time lost / recovery time: ~20 min (two focused corrections). No hours lost.
- Delivered/merged impact: the P1-T9a non-hermetic font test **reached `main`** (commit `351ec98`);
  fixed post-merge at `8c60708`. It never flaked in practice — it passed only because
  `cwd/halfblood.toml` and the user config happened not to exist on this machine.
- Files/artifacts affected: `tests/test_font_selection.py`, `tests/test_text_index.py`.
- Potential impact if a guard had not held: a latent machine-dependent flake would have failed
  for any developer who created the spec's own documented example `halfblood.toml` at the repo
  root; the impossible-property test would have driven Codex to contort a correct offset map.
- Why A-SEV3: a defect escaped the full gate + review to `main` (the P1-T9a case fits the
  "reviewer clean, defect later escaped" trigger), and the underlying guard gap recurred within
  one session — but no external harm and recovery was cheap.

## Evidence
- Loop playbook: `.claude/skills/goal/SKILL.md` (tripwire guards `tests/` against *Codex*, not
  against the controller).
- P1-T9a handoff: `thoughts/shared/handoffs/2026-07-15_21-44-57_session18-p1-t9a-merged-t9b-next.md`
  (Learnings — the font-test hermeticity hole, "caught only on a second pass, AFTER the Opus
  review returned CLEAN").
- P2-T1 handoff: `thoughts/shared/handoffs/2026-07-16_09-55-56_session18-p2-t1-merged-p2-t2-next.md`
  (the impossible-property regression test).
- Fix commits: `8c60708` (font-test hermeticity), `6b4a262` (P2-T1 test correction).
- Model/mode: builder = Codex gpt-5.6-sol (`workspace-write`); reviewer = Opus subagent; the
  loop's tripwire is a sha256 manifest over `tests/`.
- Unknowns: none material.

## Timeline
| Time | Evidence-backed event or decision |
|---|---|
| 07-15 21:30 | P1-T9a merged to `main` (`351ec98`) after gate green + Opus review CLEAN. |
| 07-15 21:40 | Advisor pass flags the font test reads `cwd/halfblood.toml` off the real machine. |
| 07-15 21:44 | Hermeticity fix committed post-merge (`8c60708`); proven load-bearing by planting the config. |
| 07-16 09:20 | P2-T1 fix loop: controller regression test asserts per-slice reversibility for `o+U+0301+U+0323`. |
| 07-16 09:30 | Advisor + a proof show the property is impossible; test corrected (`6b4a262`). |

## Trigger, detection, and recovery
- Trigger: a controller-authored test encoding a wrong contract (non-hermetic; then impossible).
- Why the loop did not detect it sooner: the tripwire proves *Codex* did not touch `tests/`; it
  says nothing about whether the controller's *own* test edits are correct. The gate runs the
  tests (they passed) and the Opus review reads the *diff vs. brief* (the test looked reasonable).
  Neither is designed to catch "the test itself asserts the wrong thing."
- Recovery: differential fuzz (font hermeticity) and an exhaustive/impossibility proof (P2-T1).
- What worked: the out-of-band advisor; empirical verification once suspicion was raised.
- Where luck limited impact: the non-hermetic test passed only because two machine files were
  absent; on another machine it would have failed loudly.

## Contributing conditions
1. **Intent/acceptance:** the acceptance contract is the controller's tests; there is no
   *second* contract to check them against, so a wrong test is self-ratifying.
2. **Context/state:** the resolver's `or`-fallbacks read machine paths; a test reaching the real
   resolver without injected paths is non-hermetic by construction — not visible in the diff.
3. **Capability/routing:** fine — Codex built correctly against the tests it was given.
4. **Tools/permissions:** the tripwire's scope is *change-detection* on `tests/`, not
   *correctness-review* of controller edits. Correct for its purpose; a gap for this class.
5. **Verification/review/human gate:** the Opus review was scoped to *Codex's diff vs. the
   brief*, not to *the controller's test delta*. The one reviewer that reads the tests
   adversarially (the advisor) is out-of-band and not part of the loop.

## Corrective decisions
| Type | Action | Contributing condition | Owner | Home/link | Due/priority | Verification | Status |
|---|---|---|---|---|---|---|---|
| detect | On any controller `tests/` edit, run a discriminating empirical check appropriate to the claim — byte-identity vs. pre-refactor for delegate/refactor tests; exhaustive or randomized fuzz for a claimed invariant — *before* dispatching Codex | cond. 1, 2 | Trey | `.claude/skills/goal/SKILL.md` step 3 | done 2026-07-16 | the clause is in step 3 | **done** |
| detect | Scope the Opus review prompt to also read the *controller's test delta* adversarially ("could any of these tests assert the wrong contract, be non-hermetic, or pass vacuously?"), not only Codex's src diff | cond. 5 | Trey | `.claude/skills/goal/SKILL.md` step 7 | done 2026-07-16 | the clause is in step 7 | **done** |
| prevent | Standing rule already applied: a test that reaches the real resolver without injectable config paths is non-hermetic — inject paths or pin `chdir` + `XDG_CONFIG_HOME` | cond. 2 | Trey | memory `tests-reaching-real-resolver-are-nonhermetic` | done | rule recorded | done |

## Harness learning
- LEARNINGS.md summary to add (harness repo): below.
- Prior incidents with the same shape: this is the 2nd and 3rd occurrence in one session — the
  gap is structural, not a one-off.
- Candidate harness/skill change: the two `detect` controls above are project-local (`/goal`
  skill). No global `HARNESS.md` change proposed yet — one session's pattern feeds LEARNINGS.md
  and waits for the repeat-and-approval gate.

## Closure
- [x] Facts and causal claims reviewed against evidence
- [x] Accepted actions moved to the normal tracker/plan (`/goal` skill steps 3 and 7)
- [x] Each declined action has a reason (no global HARNESS change — overfitting guard)
- [x] LEARNINGS.md summary added
- [x] Sensitive information handled (none present)
- [x] All actions done or explicitly declined — both `detect` controls wired into `/goal`
      steps 3 and 7 on 2026-07-16; the `prevent` rule was already recorded. Status: closed.
