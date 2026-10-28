# Phase 4 Implementation Plan: From Accepted Findings to Parser Fixes

**Status:** draft for maintainer review (2026-10-28). Nothing in this plan is
implemented yet. Phase 4 starts only after the Phase 3 gate (below) passes.

**One-line scope:** Phase 4 turns *accepted* Phase 3 root-cause findings
into deterministic parser/rule fixes — each fix shipped as code + fixture +
regression test. AI never writes parser code and never applies anything.

**Caveat:** this plan builds on Phase 3 outputs (accepted findings in the
review file, "ai_review.json", clusters, suggested fixtures). File names and
the review-file format follow the Phase 3 plan's WP9; if Phase 3 changes
them, update this plan before starting.

---

## Scope and hard invariants

- **Analysis → decision → fix.** Phase 3 produces hypotheses; Alfred decides
  ("accept"); Phase 4 implements. Nothing skips the decision step.
- **AI never writes parser code.** A finding may propose a rule
  ("proposed_rule", text only). A human turns it into code. Every fix PR is
  reviewed like any other code PR.
- **Fixes are deterministic.** The fix must be a rule/module change that the
  existing deterministic parser executes. No model calls in the fix path.
- **Never write a second parser.** Coordinate validation reuses
  shared/utils.py ("parse_coordinates"); geometry logic reuses the shared
  classifier. A fix that needs a new parser is rejected at review.
- **Fixtures come from real texts.** Each fix ships a failing test first,
  with a fixture derived from the cluster's raw snippets (the Phase 3
  "suggested_fixture"). Never reformat existing fixtures.
- **No hemisphere guessing.** If a fix cannot derive a hemisphere from the
  text, the warning stays unresolved — same rule as everywhere else in the
  project.
- **DB untouched by the fix process.** Fixes change parser code; the next
  audit/sync naturally re-derives the data. No manual row edits in Phase 4.

---

## Entry condition (Gate 3 → 4)

All Phase 3 gate items pass, specifically:

- [ ] Deterministic report complete with Gemini off (tested)
- [ ] WP8 correlated-error rates recorded; Alfred judged them useful
- [ ] Alfred reviewed findings and recorded accept / reject / investigate
      in the review file ("ai_review.json" or the PR)
- [ ] At least one finding is "accept" with a concrete proposed rule

If **zero** findings are accepted, Phase 4 does not start — the auditor is
healthy, and the next Phase 2/3 audit run re-checks that conclusion.

---

## Work packages

### WP1: Fix intake and triage (deterministic, no code)

1. Read the review file; take only "accept" entries with a note.
2. Per accepted finding, open a **fix ticket** (GitHub issue or a section in
   the agent ledger): cluster_id, affected warning IDs, suspected module,
   proposed rule, suggested fixture.
3. Triage order: critical severity first, then active-warning count, then
   cluster size (Phase 3's ranking carries over).
4. Group findings that point at the **same module + same rule** into one fix
   PR; unrelated accepted findings never share a PR.
5. "Investigate" entries stay open — they are Phase 3 leftovers, not Phase 4
   work, unless Alfred promotes them to "accept" later.

*Why one PR per rule: a revert must ever undo exactly one behavior change.*

### WP2: Fix development protocol (per fix PR)

Every fix PR follows the same sequence — test first, minimal change, prove
no regression:

1. **Reproduce:** add the new fixture + a failing test asserting the
   *expected* result (coordinates derivable from the fixture text; hemisphere
   resolved only if the text states it). The suite must be red on the fix
   branch before the rule change.
2. **Locate:** confirm the suspected module is actually where the defect
   lives. The AI's "suspected_module" is a hint, not truth — if inspection
   shows the defect is elsewhere, record that in the PR body (the hypothesis
   was wrong; the finding is still fixed).
3. **Fix minimally:** smallest rule/pattern change that turns the failing
   test green. No drive-by refactors. If the proposed rule is wrong, say so
   in the PR body and implement the corrected rule.
4. **Prove no regression:** full suite green, including the 15
   tests/fixtures/navarea_*_sample.txt files (never reformatted), the
   universal-format fixtures, and the gold sample (Phase 2 WP9) — the fix
   must convert its known-wrong cases to known-correct **without breaking
   any known-correct case**.
5. **Evidence trail:** PR body links the cluster_id, quotes the accepted
   finding and Alfred's note, and shows before/after test results for the
   affected warnings.

### WP3: Verification harness (gold-sample based)

- **Before/after rule:** a fix is verified by re-running the deterministic
  audit on the gold sample. Metrics recorded in the PR: known-wrong →
  correct (must be ≥ 1 per targeted cluster), known-correct → wrong
  (**must be 0**; any such case blocks the merge), catch-rate delta.
- **Canary set:** the gold sample's known-correct warnings act as canaries;
  a fix that improves one cluster but perturbs another is rejected and
  returned to triage.
- **No live-data verification in the fix PR.** Live verification happens
  after merge via the next scheduled audit run: the targeted issue code
  should shrink in the report. If it does not, the hypothesis was wrong or
  incomplete — reopen, do not stack another guess on top.

### WP4: Traceability and ledger

- Every merged fix appends a line to the agent ledger: cluster_id, PR,
  module, rule changed, fixtures added, gold-sample delta.
- The next audit report is diffed against the previous one (issue counts by
  code); the delta is posted back to the fix ticket. This closes the loop:
  hypothesis → decision → fix → measured outcome.
- A finding that turns out to be a false alarm *after* acceptance (fix
  merged, counts unchanged) is recorded as such — it feeds the Phase 3 WP8
  false-alarm rate and tunes future review skepticism.

### WP5: Housekeeping (batched, last)

- README/agent-doc sync: fixture counts, rule-inventory changes.
- Any new fixture files added to the universal-format suite's expectations.
- Retire fix tickets that three consecutive audits show as resolved.

---

## PR sequence

| # | PR | Depends on |
|---|---|---|
| 1 | WP1 fix intake + triaged ticket list (doc/issue only) | Phase 3 gate |
| 2..n | One fix PR per accepted rule group (WP2 protocol) | 1 |
| n+1 | WP3 harness wiring if the gold-sample runner needs a flag/report mode | 1 (can precede fixes if useful) |
| n+2 | WP4/WP5 ledger + docs batch | fix merges |

All fix PRs hold unmerged until Alfred approves, same as every other PR in
this project. Maintainer merges everything.

## Gate 4 → done (per fix)

- [ ] Failing test existed before the rule change (red → green shown)
- [ ] Full suite green; existing fixtures untouched byte-exact
- [ ] Gold sample: known-wrong → correct for the target cluster;
      known-correct regressions = 0
- [ ] No second parser introduced (reviewed explicitly)
- [ ] PR body carries the evidence trail (cluster_id, finding, note, deltas)
- [ ] Post-merge audit shows the targeted issue code shrinking

## Open decisions for Alfred

1. **Batching:** one PR per accepted finding, or grouped per module? (Plan
   suggests: grouped per module+rule, never more than one rule per PR.)
2. **Fix tickets:** GitHub issues, or sections in the agent ledger? (Issues
   give search + closing semantics; the ledger keeps everything in-repo.)
3. **Promotion rule for "investigate" entries:** require a second audit
   run's evidence before promotion, or Alfred's judgement alone?
4. **Cadence:** fixes merged one-by-one as accepted, or batched after a full
   review cycle?

## Common mistakes

1. **Trusting the hypothesis.** The suspected module is a hint; verify by
   reproduction, not by narrative.
2. **Fixing the symptom in the data.** A DB row edit "fixes" one warning and
   leaves the parser blind spot; the next ingest re-breaks it.
3. **Bundling.** Two accepted findings in one PR make reverts and bisects
   ambiguous.
4. **Skipping the red test.** A fix PR without its failing-first test cannot
   prove it fixed anything.
5. **Accepting a hemisphere guess.** If the text does not state it, the
   result is unresolved — a fix that "completes" the coordinate by
   inference repeats the original defect class.
6. **Measuring on live data before the suite.** Live counts move on their
   own (new warnings daily); only the gold sample is a fixed yardstick.

---

*Prepared by the auditor agent for maintainer review. Update this file as
Phase 3 lands and real finding shapes become known.*
