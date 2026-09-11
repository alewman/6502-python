# Immutable refactor baseline

This baseline was captured before refactor work. Later phases must preserve every
test that passed in this baseline; they must not hard-code these counts into tests.

- **Commit:** `5fcbb28ee3db5f1fd7ef4d022220ba802f090e88`
- **Collected tests:** 683
- **Full pytest summary:** `================== 682 passed, 1 skipped in 231.37s (0:03:51) ==================`

The one skipped test is the Dormann decimal exerciser. This skip is expected
when the `cc65` toolchain (`ca65` and `ld65`) is unavailable, because its
external decimal test image cannot then be built. The independently available
Dormann functional exerciser remains part of the full suite.

This record is a comparison baseline, not an assertion fixture: later phases
must retain all baseline-passing tests and must not encode the collected,
passed, or skipped counts in test expectations.
