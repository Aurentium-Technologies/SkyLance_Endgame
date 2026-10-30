# Orient's original evaluator

All terms below were defined for Orient. There are no imported piece-square
tables, network weights, opponent labels, or opponent move decisions. Values
are initial engineering hypotheses, not measured optimal parameters.

The evaluator returns centipawns from the side to move, adds an eight-centipawn
tempo bonus, and clamps to +/-20000 (below the mate-score range). White and Black
use identical formulas with Black's ranks reflected. Let `r` be the rank from
the piece's home side (0..7), `f` its file (0..7), and
`c = 14 - abs(2*f-7) - abs(2*r-7)` the centrality.

| Piece | Midgame material / positional term | Endgame material / positional term |
|---|---|---|
| Pawn | 100 / `5*r + 2*(7-abs(2*f-7))` | 120 / `10*r+c` |
| Knight | 325 / `5*c - 18*(r==0)` | 305 / `4*c` |
| Bishop | 335 / `3*c+2*r` | 330 / `3*c` |
| Rook | 505 / `2*r+c` | 525 / `2*c` |
| Queen | 970 / `c` | 940 / `2*c` |
| King | 0 / `-4*c-5*r` | 0 / `6*c` |

Each extra pawn on a file costs 13/20 (mid/end); isolated pawns cost 12/10;
pawn support adds 7/9. A passed pawn has no enemy pawn ahead on its own or an
adjacent file and gains `2*r*r` / `5*r*r`. The bishop pair adds 28/40.
An own-pawn-free rook file adds 15 midgame, plus 10 if enemy-pawn-free.

Mobility counts attacked squares excluding own pieces and enemy pawn attacks.
Knight/bishop/rook/queen weights are 4/4/2/1 in the midgame and 3/4/4/2 in the
endgame. Enemy knight/bishop/rook/queen attacks on the king and its neighbours
carry weights 3/3/4/5; twice their sum is subtracted in the midgame. Each of the
king's three adjacent files adds 12 if an own pawn is within two ranks ahead,
or subtracts 10 otherwise (only existing files count).

Phase is `N+B+2*R+4*Q` over both sides, capped at 24. The final white-relative
score is `(mid*phase + end*(24-phase))/24`, truncated toward zero.

Static exchange evaluation independently simulates captures on one square,
recomputes sliding attacks as occupancy changes, rejects pinned and illegal
king recaptures, and resolves promotion/en-passant effects. It assumes the
least valuable legal attacker at each exchange step and allows either side to
stop exchanging. SEE orders captures; the default search never prunes based on
SEE. The classical evaluator remains the baseline. An optional original compact
neural evaluator is integrated but disabled by default; no trained playing network
has been established. See [original learning](../learning/README.md) for architecture,
integer format and the data/export verification workflow.

Search-cache correctness: root searches with UCI `searchmoves` do not store a
root score in the transposition table, because that score describes an
incomplete legal move set. Fully searched descendants remain cacheable. This
guard follows from the table-key contract; no numeric failure reproduction is
claimed for the previous implementation. Regression checks exercise restricted
then unrestricted searches, including a restricted stalemate when an
unrestricted mate in one is available.
