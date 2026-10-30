# Code review and verification limits

A separate agent reviewed the narrow history fix and adaptive catalogue before
acceptance. It found no history-key/null-ancestry change, unsafe draw inference,
or additional catalogue lifetime/bounds blocker under the existing serialized
provider and immutable-files contract.

Two concrete findings were corrected before the source freeze: directory bounds
must conservatively fold ASCII case on POSIX as well as Windows, and forced
allocation failures must exercise success of one allocation followed by failure
of the other. The final unit covers both allocation sites, recorded/free counts,
hash/cardinality clearing, recovery, case variants and failed listing fallback.

The history proof and recorded 36-ply UCI transcript are separate from position
query equality. Prior repetitions add possible draw endings, so certified WDL2
moves retain nonloss at a WDL2 root. Decisive/cursed/blessed roots and an unsafe
searchmoves-only list still use ordinary history-aware search. This is a narrow
fix, not a certificate for arbitrary history-aware endgame play.

The adaptive reader retains native seven-piece entry/encoding dimensions and
hash size. Six/seven-piece placeholder names exercise discovery only. No real
larger-table correctness claim is added. The inherited decoder behavior for
arbitrarily corrupt aligned/correct-magic table metadata is not hardened here.

GCC AddressSanitizer/UBSan tests are separate from timed builds. LeakSanitizer
cannot run under this environment's ptrace wrapper: the original failed run and
its diagnostic are preserved. ASan/UBSan are retried with only leak detection
disabled; requested allocation/mapping balance is independently checked during
normal teardown and each injected failure. Do not describe this as a successful
LeakSanitizer run.

Raw timing/correctness decisions are recomputed by audit_improvements.py without
importing the experiment controllers. This is a separate implementation by the
same author, not external human peer review. The reviewing agent did not audit
the final timing campaign because its execution limit was reached.
