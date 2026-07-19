# Codex read-only strategy opinion — P3-T5 (2026-07-19)

> Source: `codex exec --sandbox read-only -m gpt-5.6-sol -c model_reasoning_effort=high`.
> Prompt: options a/b/c/d + honest trade-off + GO build sketch. Codex made no file changes.
> Preserved verbatim alongside the decision it informed (`stroke-assets.md`, NO-GO).

---

## Recommendation: (d) NO-GO for this milestone

The clearest reason: procedural handwriting is not worth five substantial downstream tasks unless the letter source is genuinely better than the fonts already in use—and Hershey is not.

Hershey Script is cursive, but it remains a regular 1960s plotter/typeface design. Pressure and jitter can make its lines less perfect; they cannot give it the letterform variety and spontaneous character of authentic marginalia. The original NIST specimens support that assessment: it is competent plotted script, not a convincing personal scrawl. [NIST Hershey repertoire](https://www.govinfo.gov/content/pkg/GOVPUB-C13-a73d50f2294c93f29e5bdd9c05baf50a/pdf/GOVPUB-C13-a73d50f2294c93f29e5bdd9c05baf50a.pdf)

## Honest trade-off

The current handwriting fonts plus irregular marks are good enough for scrawled marginalia. Procedural letters would be a premium visual refinement, not a necessary product capability.

P3-T6–T10 add asset validation, a contextual word-shaping engine, caching, a new default PDF renderer, and permanent visual/performance regression maintenance. That is disproportionate to fixing the relatively subtle problem that repeated letters share an outline. The content, placement, ink color, rotation, crossings, circles, arrows, and doodles will carry much more of the “Prince’s notes” illusion.

Do not choose Hershey merely because it makes the licensing gate easy. Under the existing acceptance criteria, Hershey is not actually a ready-made low-effort asset: a typical package supplies fonts and stroke iterators, but not the required 3–5 alternates, contextual forms, ligatures, anchors, and natural joining behavior. [Hershey-Fonts package description](https://pypi.org/project/Hershey-Fonts/) Those missing pieces would push option (a) toward the human-design cost of option (b), while retaining the weaker plotter aesthetic.

If this is reopened later, choose **(b)**: commission an artist and capture actual tablet pen trajectories, including timing and pressure. Do that only after side-by-side tests at real margin size demonstrate that customers notice and value the difference.

## Important risks and overlooked option

- The repository currently contradicts the premise that rough marks are shipping through PDF. The rough generator exists, but the inspected renderer still inserts typeset text, native PDF circles/underlines/strikeouts, and the older bowed connector: [document_processor.py](/mnt/c/Users/Trey/Downloads/half-blood-prince/src/halfblood/document_processor.py:605), [native marks](/mnt/c/Users/Trey/Downloads/half-blood-prince/src/halfblood/document_processor.py:886), [connector](/mnt/c/Users/Trey/Downloads/half-blood-prince/src/halfblood/document_processor.py:1127). P3-T9 is where scene/PDF integration is planned, but it is currently blocked by T5. Consider rough-mark PDF integration as a separate, asset-free scope decision; it should not require procedural letters.

- The four TTF files are present locally but are not tracked by Git; only `fonts/README.md` is tracked, and that README says font files are not committed. Therefore “current fonts ship” should be verified against the actual wheel/release experience. Otherwise users may receive Helvetica fallback rather than the demonstrated aesthetic.

- Before any future GO, run a small blind visual bake-off: current fonts versus Hershey Script versus a few human-captured words, rendered at actual PDF margin size. This is cheaper and more decision-useful than approving an engine based on enlarged font specimens.

- The latent geometry defect is real: [`_douglas_peucker`](/mnt/c/Users/Trey/Downloads/half-blood-prince/src/halfblood/ink/geometry.py:332) evaluates only command endpoints and ignores Bézier control points. It can remove intermediate `CubicTo` commands and materially change curve shape. Any future P3-T7 work must first use cubic-aware simplification—such as adaptive curve flattening with controlled reconstruction or direct Bézier-aware error measurement—before accepting multi-cubic handwriting paths.

No provenance record or P3-T6–T10 implementation sketch is needed for the recommended NO-GO. No files were changed.