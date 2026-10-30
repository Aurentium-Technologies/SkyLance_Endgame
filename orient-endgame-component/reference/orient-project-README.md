# Orient

An original C++20 chess engine and a reproducible engine-development project by Orient Technologies.

**Status: under active development; no validated Elo rating yet.** The target is a local CCRL-Blitz-anchored estimate with a lower 95% confidence bound of at least 3000, verified in a frozen 6,000-game campaign. Passing correctness tests or finishing a playable version does not establish that rating.

The latest [96-game diagnostic](benchmarks/current-strength-001.md) scored
6 wins, 3 draws and 87 losses against saved reference opponents around 3000.
Its exploratory anchored fit is about 2570 under the test conditions, with
substantial transfer limitations; it does not certify the target.

## Build and run

Requires a C++20 compiler, CMake 3.20+, Ninja, and pthreads. Python 3.10+ runs the
experiment and black-box test tools. The build includes the MIT-licensed Fathom
tablebase reader; ordinary search and evaluation remain Orient's own code.
Endgame table files are optional local data and are not needed to start the
engine or run its existing searches.

```sh
cmake --preset release
cmake --build --preset release
ctest --preset release
./build/release/orient
```

The executable speaks UCI over stdin/stdout and can be loaded in a UCI-compatible chess GUI. For example:

```text
uci
isready
position startpos moves e2e4 e7e5
go movetime 1000
```

Send `stop` to interrupt a search and `quit` to exit. Search information includes depth, score, nodes, elapsed time, and a principal variation. `Threads` currently supports one search thread. `Hash` defaults to 256 MiB. Selective pruning remains disabled by default until controlled matches establish its value.

The current retained classical baseline explicitly sends
`setoption name Null Move value true`: this change passed both declared match
stages. Its compiled default remains false for checkpoint reproducibility.
NNUE and the other unretained experimental options stay disabled.

Additional command-line tools:

```sh
./build/release/orient --help
./build/release/orient perft 6
./build/release/orient legal startpos
./build/release/orient fen startpos e2e4 e7e5
./build/release/orient eval '8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1'
./build/release/orient bench 6
```

Use the `debug`, `sanitize`, and `native` CMake presets for debugging, address/undefined-behaviour checks, and local CPU optimization. Native binaries may require instructions unavailable on other CPUs. Compile with at most three build jobs on the development laptop.

## Original learning

An optional original compact neural evaluator, CPU self-play generator and
CPU/CUDA training pipeline are implemented. Neural evaluation is disabled by default. The first network
prototype was trained solely from Orient's own games; it has no demonstrated
strength improvement. See the
[learning workflow](learning/README.md) for provenance, architecture and export
verification. Self-play generation remains tablebase-free; training dependencies
are separate.

`Hash Move Hints` is an experimental move-ordering option, disabled by default.
Its move-only cache shares the Hash budget with history-qualified score entries;
it never supplies cached score bounds. See [search correctness](docs/search.md).
`Direct Legal Moves` independently tests king safety using hypothetical occupancy
and retains make/unmake generation as its reference. It also remains disabled
until measured. Both experimental options can be selected through UCI.

## Research process

The [current development plan](docs/development-plan.md) keeps original
alpha-beta search with a compact original neural evaluator, and prioritizes
deeper own-game data and measured learning alongside search improvements.
It includes the architecture review and current interrupted-experiment status.

The chess rules, attack generation, search, position evaluation, and eventual learned networks are implemented independently. Known algorithms such as alpha-beta, principal-variation search, transposition tables, and NNUE are concepts, not imported engine implementations. See [originality and provenance](docs/originality.md), [search correctness](docs/search.md) and [evaluation](docs/evaluation.md).

Existing playing engines are used as external test opponents. Orient does not
import their search, evaluation, weights or training labels. The owner explicitly
allows shared solved-position data and a declared Fathom reader fork for five-piece
endgames. Fastchess remains a separate tournament tool. Opponent executables
live outside the source distribution.

## Five-piece endgames

Orient can use complete three-, four- and five-piece Syzygy tables, including both
kings and any pawns. Set `SyzygyPath` to the verified local collection and keep
`SyzygyProbeLimit` at 5. An empty path or limit 0 disables probing. The optional
`SyzygyCache` is measured in MiB, separately from `Hash`; its initial default is
0. Search output includes `tbhits`. Tablebase results do not imply a mate distance.
See [download, setup, provenance and bot preflight](docs/endgame-tablebases.md).
The [probe/cache optimization experiment](docs/endgame-tablebase-optimization-002.md)
records exact eight-byte-cache and root-reuse prototypes. Neither passed its
adoption gate; their build options default off and candidate 015 remains intact.

Development matches and final validation are distinct experiments. The final test freezes the binary, opponents, opening set, settings, and sample size before play. It preserves full game records and reports uncertainty, hardware differences, and failures. A local estimate is not an official CCRL listing. See [benchmarking](docs/benchmarking.md).

The active objective and verified milestones are tracked in [GOAL.md](GOAL.md). The current benchmark report is [benchmarks/REPORT.md](benchmarks/REPORT.md); incomplete experiments cannot certify the target.

## Lichess preparation

For a new BOT account, follow the [account and private-token setup](docs/lichess-account-setup.md).
The local helper `python3 tools/configure_lichess.py` asks for the token without
echoing it and writes private, Git-ignored files. Do not send the token in chat.

The original [Lichess bridge and setup guide](docs/lichess.md) prepare frozen
Orient for one explicitly selected casual standard game. Offline engine preflight
and a read-only BOT account check precede live play. Keep credentials private;
the example configuration has no token. The bridge uses only Orient's own moves.
The Aurentium BOT account completed its first casual live integration game,
losing to Lichess AI level 8 after 26 moves. Its saved PGN, full move history and
26 own move confirmations pass audit. See [live integration status](docs/lichess-live-status.md).
The site's displayed 3000 is provisional; a validated strength rating remains
unestablished. The current bridge runs one selected game per invocation.

MIT licensed. Lichess play runs on this computer. No online hosting, automatic
public submissions, or paid computing services are part of this project.
