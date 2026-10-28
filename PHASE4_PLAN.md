# Phase 4 Implementation Plan: Fix, Test, Validate

**Status:** maintainer's plan (2026-10-28), grounded against the live repo the
same day by the auditor agent. Nothing here is implemented yet; Phase 4
starts only after the Gate 3→4 entry condition below passes.

**Scope:** turn *accepted* findings into small parser fixes and reviewed DB
corrections. No auto-commit, merge, deploy, or unapproved data write.

## Grounding notes (placeholders resolved 2026-10-28, verified on main)

- Candidate modules — ALL EXIST: "shared/utils.py", "shared/navarea_universal_text.py",
  "shared/splitter.py", "shared/geometry_classifier.py", "shared/triage.py",
  "shared/gemini_navarea_parser.py", "scripts/navarea_universal_parser.py".
- Test framework: this repo runs unittest discovery ("python -m unittest
  discover tests -v"), NOT pytest, and the tests.yml env installs NOTHING —
  all tests must be stdlib-only. The example below is converted to unittest.
- Real regression suites: "tests/test_golden_corpus.py" (golden corpus),
  "tests/test_universal_formats.py" (+ 15 fixtures under "tests/fixtures/",
  never reformatted), "tests/test_geometry_classifier.py",
  "tests/test_supabase_parsing_audit.py". A dedicated "property-based" suite
  is NOT confirmed in this repo — treat that line as "the full discovered
  suite" unless one is added before Phase 4 starts.
- Real parse entry points: "shared.utils.parse_coordinates(raw_text)"
  (returns parsed_coords, primary_lat, primary_lon, spatial GeoJSON) and the
  universal parser in "scripts/navarea_universal_parser.py" for full
  bulletins. "parse_warning" below is realized as these.
- Correction workflow: the modes are real — "audit_only",
  "propose_corrections", "apply_approved" in
  "scripts/audit_supabase_parsing.py", applying ONLY via the
  "admin_save_nav_warning" RPC, gated by the "production-corrections"
  environment and "confirm_apply". No direct SQL.

## Entry condition (Gate 3→4)

Gate 3→4 passed and Alfred has marked each finding accept / reject /
investigate. Only "accept" enters this phase.

---

## Step 0: Prepare (once)

1. Freeze the **before** state:
   - latest audit report (the "before" report)
   - test results: full discovered suite (golden corpus, universal formats,
     geometry, audit)
   - gold sample results from Phase 2
2. Create a tracking file "phase4_findings.md" (or a table in the PR) with
   one row per finding: ID, category, status, PR link, fixture path,
   before/after counts.
3. Work on a branch per fix, never on "main".

---

## Step 1: Classify every accepted finding

| Category | Action | Goes to |
|---|---|---|
| Parser rule missing or wrong | Fix rule + fixture | Step 2 |
| DB row wrong, parser correct | Correction proposal | Step 3 |
| Ambiguous source text | Manual review, **no guess**, mark unresolved | Step 4 list |
| Scraper, splitter or sync defect | Fix upstream cause | Step 2 (different module) |
| Duplicate or lifecycle issue | Separate investigation, keep history | Own ticket |

Decision test for parser vs data: re-parse the stored raw_text with the
*current* parser.

- Parser gives the right answer, DB is wrong: data issue (old parser
  version, or an admin edit).
- Parser gives the wrong answer: parser issue.
- Raw text itself is cut off or garbled: scraper/splitter issue.
- Even a human can't tell the hemisphere or position: ambiguous. Stop.

Many fixes will be a mix (parser fixed, then old rows corrected). Do the
parser first.

---

## Step 2: Parser fix (one finding = one PR)

Edit only the module the evidence points to (see the verified list above).

### 2.1 Reproduce first
- Take the minimal raw text from the finding (trim to the smallest string
  that still fails).
- Run the current parser on it and record the actual wrong output. If you
  can't reproduce, the finding isn't confirmed. Stop and reclassify.

### 2.2 Write the failing test first

New file: "tests/test_parser_regressions.py" (unittest, stdlib-only —
tests.yml installs nothing):

    import os
    import sys
    import unittest

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

    from shared.utils import parse_coordinates

    # One fixture per confirmed bug. Keep raw text exactly as published.
    CASES = [
        {
            "id": "F-012",                     # finding ID from the tracking file
            "raw": "<minimal original text>",  # never paraphrase the source
            "expected_type": "Polygon",        # geometry type a human confirmed
            "expected_coords": [[0.0, 0.0]],   # human-confirmed [lon, lat] only
        },
    ]

    class TestParserRegressions(unittest.TestCase):
        def test_regression(self):
            for case in CASES:
                with self.subTest(case=case["id"]):
                    _coords, _lat, _lon, spatial = parse_coordinates(case["raw"])
                    self.assertEqual(spatial["type"], case["expected_type"])
                    self.assertEqual(spatial["coordinates"], case["expected_coords"])
                    # also checks ORDER and hemisphere — expected values must
                    # come from a human reading the source, never from Gemini
                    # and never from the parser's own output.

    if __name__ == "__main__":
        unittest.main()

Rules:
- Expected values come from a **human reading the source**, not from Gemini
  and not from the parser's own output.
- Test coordinate values, hemisphere, ordering, and geometry type.
- Confirm the test **fails** before the fix. Paste the real failure output
  into the PR.

### 2.3 Minimal fix
- Change the smallest rule that explains the failure.
- Reuse existing coordinate parsing ("shared/utils.py"). No second parser.
- No hemisphere inference from numbers. If the text doesn't state it, the
  result stays unresolved (and the test for that case asserts unresolved —
  e.g. spatial is None and tier stays C via the "shared/triage.py"
  blockers).
- No threshold loosening just to make a test pass.

### 2.4 Negative tests (often skipped, important)
Add cases the new rule must **not** change:
- a similar-looking text where the old behaviour was correct
- a text with a genuinely missing hemisphere (must stay unresolved)
- an invalid value like 91°00'N (must stay invalid, never clamped —
  "convert_to_decimal" returns NaN today; keep it that way)

### 2.5 Full regression run

    python -m unittest discover tests -v 2>&1 | tee after_fix_F-012.txt

- All existing suites green: golden corpus, universal formats (15 fixtures,
  never reformatted), geometry, audit — i.e. the full discovered suite.
- **Golden corpus diff:** compare parsed output before vs after for the
  whole corpus. Any changed row must be explained by the fix. **Zero
  unintended changes.**
- Also parse the raw_text of all stored warnings with old vs new parser,
  offline, and diff. This shows the blast radius: how many existing rows
  would change. Don't write anything; only report the diff.

### 2.6 PR contents
- fixture + tests + the fix
- before/after test output (real, pasted)
- the corpus/stored-rows diff summary
- link to the finding and category
- note which stored rows will differ if re-parsed (feeds Step 3)

Alfred reviews and merges. Nobody merges automatically.

---

## Step 3: Correct existing database rows

Path stays: "propose_corrections" → human approval → "apply_approved" (the
existing modes of "scripts/audit_supabase_parsing.py").

### 3.1 Build the candidate list (read-only)
From the offline old-vs-new diff in 2.5, select rows where the new parser
output differs from the stored value. For each, classify:
- **Safe-looking correction:** new parser value is explicit in the raw text
- **Ambiguous:** needs human judgement, no proposal
- **Protected:** human-verified or admin-frozen (qa_flags elements
  "edited_by_admin" / "verified_by_admin", or status "superseded"), so
  conflict report only, no proposal

### 3.2 Generate proposals
Use the existing "propose_corrections" flow. Confirm it still enforces:
- approved proposals only
- field allowlist
- raw-evidence grounding (the correction must be supported by the row's
  own raw text)
- optimistic locking and stale-record detection

Don't loosen any of these to push more rows through.

### 3.3 Snapshot before apply (new safeguard)
Before "apply_approved" runs, export for every row to be changed: id, the
fields being changed, their **old** values, updated_at. Save as
"rollback_snapshot_<date>.json" (write it into the audit-report directory
so it rides the existing artifact upload) and attach to the PR/run. *Why:
the existing flow has no documented rollback.*

### 3.4 Small batches
- Start with 3–5 rows. Alfred checks each against the source bulletin.
- Then a larger batch only if the first is clean.
- Never apply the whole candidate list in one go.

### 3.5 Apply
- Through the "admin_save_nav_warning" RPC only, via the existing
  "production-corrections" environment gate and "confirm_apply".
- No direct SQL updates, no deletes.
- Record apply run URL and row IDs in the tracking file.

### 3.6 Verify each batch
- Re-run "audit_only" on the changed rows (or whole table).
- Spot-check on the map for a few corrected warnings: the position should
  match the source text.

### 3.7 Rollback procedure (write it before you need it)
If a batch is wrong: use the snapshot to build a reversing set of proposals
and run them through the **same** approval path. No ad-hoc SQL. Test this
procedure on one row first.

---

## Step 4: Unresolved and ambiguous items
- Keep a list: warning ID, why unresolved, what evidence would settle it
  (e.g. original bulletin from the hydrographic office).
- They stay visible, flagged for review. Never auto-resolved, never
  deleted.
- Re-examine only when new source evidence appears.

---

## Step 5: Re-audit and compare (after deploy)

1. Confirm the merged parser is the deployed version (check the commit
   actually deployed).
2. Run "audit_only" again; save as "after_report_<date>.json".
3. Build a before/after table:

| Code | Before | After | Explained by |
|---|---|---|---|
| e.g. COORDINATE_OUT_OF_BOUNDS | n | m | F-012 fix |

4. Check three things:
   - target issue count dropped for the intended reason
   - **no new issue codes or count increases** without explanation
   - previously correct rows (gold sample) still correct
5. Re-run the gold sample; compare catch and false-alarm rates with Phase 2.
6. Optional: re-run Phase 3 on the *remaining* clusters only.

Per finding, status becomes one of: "fixed (verified)", "partially fixed",
"not fixed", "unresolved/ambiguous". Say it plainly; don't mark fixed without
the after-report evidence.

---

## Suggested PR order

| # | Work | Notes |
|---|---|---|
| 1 | Highest-severity parser fix (active warnings, position-affecting) | One finding each |
| 2+ | Next findings, one PR each | Don't bundle |
| n | Correction batch 1 (3–5 rows) | After its parser fix is deployed |
| n+1 | Larger correction batches | Only if batch 1 verified |
| last | Final re-audit and summary | |

Never bundle a parser fix and a data correction in one PR.

---

## Final gate (end of Phase 4)

- [ ] Every accepted finding has: category, fixture, failing-then-passing
      test, PR
- [ ] All existing tests green; golden corpus shows **zero unintended
      changes**
- [ ] Offline old-vs-new diff reviewed for blast radius
- [ ] Every DB correction went through the approved path, with rollback
      snapshot and Alfred's approval
- [ ] No auto commit, merge, deploy, delete
- [ ] After-report shows the original issues fixed, and no unexplained new
      ones
- [ ] Gold sample rates not worse than Phase 2
- [ ] Ambiguous rows listed as unresolved, not guessed
- [ ] Before/after table complete

## Open decisions for Alfred

1. Fix order: by severity, or by number of affected rows.
2. First correction batch size.
3. Who verifies corrected rows against the source (you, by hand).
4. Whether old rows get re-parsed in bulk at all, or only corrected case by
   case. Bulk re-parse is higher risk; avoid it.

## Common mistakes

1. Using Gemini's expected result as the test's truth. Only a human reading
   the source counts.
2. Fixing the parser and correcting rows in the same PR.
3. Skipping negative tests, so a fix for one format breaks another.
4. Declaring "fixed" from passing tests alone. The re-audit is the evidence.
5. Applying corrections to frozen or human-verified rows.
6. No rollback snapshot.

**Next step:** when Phase 3 findings exist, bring the first accepted one
(raw text, current parser output, what a human reads from the source). We
write the failing test together before touching any parser code.
