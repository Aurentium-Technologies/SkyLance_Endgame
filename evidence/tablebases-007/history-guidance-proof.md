# History-safe drawing-root guidance

The change in `src/search.cpp` fixes the recorded game53 first loss without
making history-free decisive outcomes unconditional. It is deliberately narrow:
only a successful root whose five-valued WDL is exactly2 may regain direct draw
guidance when earlier positions have repeated.

The engine still checks its actual current terminal/draw state first. It probes
the complete legal alternatives, retains the existing clock-rounding ambiguity
guard, and considers only user-permitted `searchmoves`. Each candidate move is
made with the complete actual history and then unmade. Checkmate has precedence.
A repeated-history root accepts a move only when its score is zero and either:

- the move itself has tablebase WDL2; or
- Orient's own rules establish an actual immediate draw after that move.

A losing-labelled move can therefore remain usable when it actually creates a
third repetition. If the allowed root moves contain no certified draw, the
function returns to ordinary history-aware search without pruning that list or
declaring a history-free loss exact. Repeated roots with WDL0/1/3/4 also retain
ordinary search. The handling of fresh-history roots is unchanged.

The safety argument is that prior repetitions add possible draw endings to the
same board/clock game. An existing strategy avoiding loss remains nonlosing:
every continuation either follows its old nonlosing outcome or ends earlier in
a draw. At a WDL2 root both players have such a strategy, so adding repetitions
cannot turn that root into a forced win or loss. The same argument applies after
an individually WDL2-labelled move. An actual immediate draw is certified by
Orient's full-history rule evaluation instead of by this argument.

This argument does not justify treating a history-free win or loss as exact:
new repetition opportunities can change either to a draw. Cursed/blessed outcomes
and clock-rounding boundaries stay conservative. The patch does not alter the
transposition key, cached bounds, null-search ancestry, descendant WDL eligibility,
or repetition/move-count adjudication, and it saves no additional table entry.

## Recorded regression and tests

`test_endgame_search.cpp` now reconstructs the actual initial FEN and all36 plies
before19.Kc1 in the saved game. It verifies the exact final FEN, halfmove26,
37 retained history keys and current-position occurrence count1. Prior repeated
positions remain in the reversible window. With either legal generator and with
Null Move OFF/ON, the corrected search selects Ka1 or Ka2 with certified draw
score0, zero searched nodes and a root-tablebase hit. Restricting to Ka2 works;
restricting only to losing Kc1 returns to ordinary search with the same score and
node count as the no-table reference at the tested depth.

Other regressions cover a losing-labelled move which actually creates its third
repetition, decisive repeated roots, current-root threefold precedence, blessed/
cursed clock99 roots, already-stopped analysis and an already-expired budget.
Existing mate, rule50, en-passant, promotion, missing-table and disabled-table
checks remain present.

The native focused CTest run passes all5 groups: endgame_search, search,
search_pruning_regression, tablebase_uci and uci_lifecycle. Build settings retain
prefix ON, catalogue/diagnostics/adapter-fastpath/compact-cache/root-reuse/profiling
OFF. Reader compilation completed before the separate memory experiments began.

`history_uci_regression.py` additionally exercises the actual UCI binary with the
recorded complete history. Finite depth8 selects a drawing king move; infinite
analysis withholds bestmove until stop; an unsafe-only searchmoves request uses
ordinary search; and Clear Hash/ucinewgame preserves the safe decision. These four
stages pass and are saved in `history-uci-proof.json` with the executable digest.

This is a fix for the demonstrated drawing-root weakness, not a claim of perfect
history-aware endgame play or an Elo gain. Uncertain decisive roots remain a
separate conservative fallback boundary.
