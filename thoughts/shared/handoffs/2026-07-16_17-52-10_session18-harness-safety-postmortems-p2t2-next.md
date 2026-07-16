---
date: 2026-07-16T17:52:10-04:00
researcher: Claude (Opus 4.8) — controller session
git_commit: 8ca6ead11a9cae298e49801862869a8f2fbc39cf
branch: main
repository: half-blood-prince
topic: "Session 18 (final) — Codex safety locked down; dev-harness generalized to a private repo with a postmortem system; P2-T1 merged; P2-T2 next"
tags: [session-checkpoint, phase2, p2-t1, p2-t2, codex-safety, dev-harness, postmortems, goal-loop]
status: complete
last_updated: 2026-07-16
type: handoff
---

# Session 18 final — Codex sandboxed; harness → private repo + postmortems; hbp P2-T1 merged, P2-T2 next

> Supersedes the `16-58-46` checkpoint (it predates the harness/safety/postmortem work).
> Two repos are now in play: **half-blood-prince** (`main` @ `8ca6ead`, 642 green) and a new
> **`~/dev-harness`** (pushed to a private GitHub repo). **Read "⚠️ On-disk-only state" below —
> the `/goal` skill hardening is NOT in git.**

## Task(s)

1. ✅ **hbp P2-T1** — normalized text index — merged earlier this session (`d2f5d23`, 642 green).
   Unchanged since; see the per-task handoff `2026-07-16_09-55-56_...p2-t1-merged-p2-t2-next.md`.
2. ✅ **Codex safety locked down** (owner directive: confine Codex to the repo; never let it
   delete). Enforced by a reusable wrapper + hardened `/goal` loop.
3. ✅ **`fs-dev-harness` generalized → `~/dev-harness`**, pushed to
   **https://github.com/robertlupo1997/dev-harness** (PRIVATE).
4. ✅ **Postmortem system built into the harness** (Codex researched it; I distilled + wired it)
   and **proven with hbp's first postmortem (closed)**.
5. ⏳ **hbp P2-T2** — quote selectors + contextual evidence — NOT started. Next hbp task.
6. ⏳ **`~/dev-harness/docs/design/harness-vision.md`** — Codex's broader roadmap — written but
   NOT yet critically reviewed. Next harness step if continuing the harness buildout.
7. ⏳ **OPEN DECISION (carried):** the "versioned" model id (arch §4.4:308) — blocks hbp v0.1.0.

## ⚠️ On-disk-only state (read before resuming — this is the easy thing to lose)

- **`.claude/skills/goal/SKILL.md` is hardened but UNCOMMITTED by design.** `.claude/` is in
  hbp's never-commit set (loop step 8 forbids committing it; the SDD session reverts `.claude/`
  edits). So this session's `/goal` changes live only on local disk — a `git clean -xfd` or a
  fresh clone would lose them. What changed: step 3 (discriminating check on the controller's own
  test edits before dispatch), step 4 (NO-DELETE contract + confined `codex-safe.sh` dispatch,
  no bypass flags), step 5 (whole-tree deletion/rename sweep), step 7 (Opus review also reads the
  controller's test delta adversarially). If these are gone next session, reapply from this
  handoff + the postmortem's corrective controls.
- **`.superpowers/sdd/LEARNINGS.md`** (hbp retro log) and **`.superpowers/sdd/*.testsums`** are
  gitignored scratch — on disk, not in git. Expected.
- The **canonical, durable copies** of the safety mechanism live in the *dev-harness* repo
  (committed + pushed): `scripts/codex-safe.sh` and the postmortem system. hbp's `/goal` skill is
  a project-local fork of that discipline.

## Critical References

1. `~/dev-harness/scripts/codex-safe.sh` — the confined, non-destructive Codex dispatch wrapper
   (committed + pushed). The safety guarantee's durable home.
2. `~/dev-harness/skills/postmortem/SKILL.md` + `references/template.md`;
   `~/dev-harness/docs/research/postmortems.md` (Codex research, cited); `HARNESS.md §9`.
3. `half-blood-prince/docs/postmortems/2026-07-16-controller-test-edits-unguarded.md` — the first
   postmortem (A-SEV3, **closed**); its two controls are now in `/goal` steps 3 and 7.
4. `docs/superpowers/plans/2026-07-11-phase2-3-implementation-plan.md` — Phase 2 plan; **P2-T2
   line 31** is next.
5. hbp per-task handoff for P2-T1: `thoughts/shared/handoffs/2026-07-16_09-55-56_...`.

## Recent changes

**half-blood-prince (committed on `main`):**
- `docs/postmortems/2026-07-16-controller-test-edits-unguarded.md` — NEW, `fa0a49b` (written) →
  `8ca6ead` (closed after wiring its controls).
- (uncommitted, on-disk) `.claude/skills/goal/SKILL.md` steps 3/4/5/7 hardened; see above.
- (gitignored) `.superpowers/sdd/LEARNINGS.md` — NEW retro log seeded with this session's lessons.

**~/dev-harness (committed + pushed; `71b0121`):**
- Generalized from `fs-dev-harness`; `git init` + private GitHub repo.
- `scripts/codex-safe.sh` — NEW confined dispatch wrapper.
- `skills/postmortem/` (SKILL.md + references/template.md), `docs/postmortems/README.md`,
  `HARNESS.md §7 + §9`, `skills/harness-retro/SKILL.md` (escalation pointer + stale-path fix).
- `docs/research/postmortems.md`, `docs/design/harness-vision.md` — Codex deliverables.

## Learnings

- **Codex safety is two separate problems.** (1) *Confinement* is OS-enforced for free:
  `--sandbox workspace-write -C <dir>` with no bypass flags confines writes to the workspace via
  Landlock/seccomp — Codex physically cannot write to a sibling/parent folder, and the "trusted"
  entries in `~/.codex/config.toml` only affect approval prompts, not the write boundary.
  (2) *No-delete* is NOT provided by the sandbox (workspace-write permits `rm` inside) — so it
  needs a real backstop: a NO-DELETE brief preamble + a post-run `git`-restore of any tracked
  file Codex removed (tested; `codex-safe.sh` does both). Limit: only *tracked* files are
  auto-restored → commit before dispatch.
- **Network access ≠ file-write escape.** Enabling network for a research dispatch does NOT widen
  file access; confinement holds. The harness-research run used `--net` and still wrote only
  inside `~/dev-harness` and deleted nothing (verified).
- **Codex produced genuinely worthy research** (postmortems.md: real citations, a sound severity
  scale, ceremony-creep guards). Reviewed critically before building on it, per "don't trust
  Codex blind."
- **A postmortem's honesty test is its trigger policy.** Most of this session was the guards
  *working* (Opus caught the P2-T1 blocker pre-merge = A-SEV4 = retro only). Forcing a postmortem
  there would model the ceremony-creep anti-pattern. The one honest fit: P1-T9a's Opus review
  returned CLEAN, a non-hermetic test *merged*, caught later — the "reviewer clean, defect
  escaped" trigger. Wrote that; its product is controls, not prose, so I wired them and closed it.
- **The loop's standing blind spot, now mitigated:** nothing reviewed the *controller's own* test
  edits (they are the acceptance contract). `/goal` steps 3 and 7 now cover it.

## Verification

| Claim | Command run this session | Result |
|---|---|---|
| hbp gate green (re-run from repo root) | `.venv/bin/pytest tests/ -q` | `642 passed, 22 warnings` |
| hbp HEAD (stale handoff was `bf34c13`) | `git rev-parse HEAD` | `8ca6ead11a9cae298e49801862869a8f2fbc39cf` |
| commits since stale handoff | `git log --oneline bf34c13..HEAD` | `8ca6ead`, `fa0a49b`, `48448cd` |
| `/goal` hardening is on-disk, uncommitted | `git status --porcelain` | ` M .claude/skills/goal/SKILL.md` (never-commit set) |
| `/goal` steps 3/4/5/7 carry the new controls | `grep -nE "discriminating empirical\|NO-DELETE contract\|deletion sweep\|controller's OWN test delta" …SKILL.md` | 4 hits at lines 114/121/133/159 |
| codex-safe wrapper present + executable | `ls -la ~/dev-harness/scripts/codex-safe.sh` | `-rwxr-xr-x … codex-safe.sh` |
| codex-safe restores tracked deletions | throwaway-repo test (delete tracked file → `git ls-files --deleted \| xargs git checkout --`) | file restored — PASS |
| codex-safe refuses bypass flags | `codex-safe.sh --dangerously-bypass-approvals-and-sandbox` | "refusing unknown/possibly-unsafe arg" |
| dev-harness committed + pushed | `git -C ~/dev-harness log --oneline -2`; `git remote get-url origin` | `71b0121`; `github.com/robertlupo1997/dev-harness` |
| Codex research stayed confined + deleted nothing | `git -C ~/dev-harness status --porcelain \| grep -E '^( ?D\|D \|R )'` | empty; writes only under `docs/` |
| first postmortem closed | `grep '^status:' docs/postmortems/2026-07-16-...md` | `status: closed` |
| its controls are DONE (wired) | postmortem corrective table | both `detect` rows → **done** (`/goal` steps 3, 7) |
| repo private | `gh repo view --json visibility` (dev-harness) | `PRIVATE` |
| Nothing pushed from hbp | `git remote -v` | empty (hbp has no remote) |

## Artifacts

- hbp: `docs/postmortems/2026-07-16-controller-test-edits-unguarded.md` (committed); hardened
  `.claude/skills/goal/SKILL.md` (on-disk); `.superpowers/sdd/LEARNINGS.md` (gitignored).
- dev-harness: full repo at `~/dev-harness`, pushed to the private GitHub repo. Codex deliverables
  `docs/research/postmortems.md`, `docs/design/harness-vision.md`. Confined-dispatch report was
  written inline (no separate `_codex-harness-report.md`).
- Rollback tags (hbp): `pre-phase2-2026-07-16` @ `7ade9cd`, `pre-overnight-2026-07-15` @ `8b58383`.
- Merged hbp branches (safe to delete): `phase1-t9a/b`, `phase2-t1`.

## Action Items & Next Steps

1. **Two workstreams — pick one to resume:**
   - **(a) hbp Phase 2 → P2-T2** (quote selectors + contextual evidence; plan line 31; depends
     P2-T1). Now runs under the hardened `/goal` (the controller-test controls are active).
     Attended task-by-task was the chosen cadence.
   - **(b) Continue the harness buildout** — critically review `~/dev-harness/docs/design/
     harness-vision.md` (cross-domain packs for ML/DS/DE, safe multi-task builder orchestration,
     adoption roadmap), adopt minimal-first.
2. **Apply the Codex CLI update** (0.144.1 → 0.144.5) — safe now, between dispatches:
   `npm install -g @openai/codex`. Re-verify `codex-safe.sh` still works after.
3. **hbp known P2-T1 limitation (deferred to P2-T3):** clusters whose NFC retains 3+/duplicate
   combining marks may return a covering (not exact) span. Grapheme-cluster match precision → P2-T3.
4. **OPEN DECISION — the "versioned" model id** (arch §4.4:308); verify against live Anthropic
   docs (`claude-api` skill) before acting. Blocks hbp v0.1.0.
5. **Consider committing the `/goal` hardening somewhere durable.** It's intentionally not in hbp
   git, but its safety value argues for a durable copy — the canonical mechanism IS in dev-harness
   (`codex-safe.sh`); decide whether hbp's project-local `/goal` fork should be snapshotted too.

## Other Notes

- **Two-repo hygiene:** hbp is local-only (never push). dev-harness IS pushed (private). Don't
  cross them — a `codex exec` for hbp uses `-C <hbp>`; for the harness uses `-C ~/dev-harness`.
- Codex dispatch is now **always** via `codex-safe.sh` (or the raw form with the NO-DELETE
  preamble + post-run deletion sweep). NEVER `--dangerously-bypass-*` or `--add-writable-dir`.
- Repo on `/mnt/c` under WSL: `.venv/bin/…`; `git show --stat HEAD` after every merge.
  `.claude/settings.local.json` bypass is intentional. `git reset --hard` on main is hook-blocked
  (use `--mixed`). `thoughts/` gitignored (needs `git add -f`).
- **A bare `/goal` next session** advances hbp Phase 2 (it reads the active plan) — but it will
  now also run the controller-test check + confined Codex dispatch. For the harness work, do NOT
  use `/goal` (it's the hbp SDD loop); drive the harness via its own tiered process.
