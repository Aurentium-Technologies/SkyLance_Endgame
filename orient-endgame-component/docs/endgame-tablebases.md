# Five-piece endgame setup

Orient's endgame integration uses a pinned local Fathom fork and public Syzygy
WDL and DTZ files. The ordinary search, evaluator and primary legal-move
generator remain Orient's own implementations. Both kings and all pawns count
toward the limit of five pieces. See [originality and provenance](originality.md).

## Data and engine settings

The complete collection contains 290 files: WDL outcomes and DTZ progress
information for 145 material classes. It occupies approximately one gigabyte in
its already compressed format. The downloader supports resuming partial files,
checks published hashes before publishing a completed file and creates a
manifest containing every file's name, size, source and SHA-256 digest. A
collection is usable by the pinned bot profile only after the complete manifest
verifies. The files are not packaged into the executable or loaded wholly into
RAM. Tablebase files remain under ignored `external/` storage.

For a downloaded collection at the workspace's default location, send these UCI
commands, replacing the example path with the absolute path on your computer:

```text
uci
setoption name SyzygyPath value /absolute/workspace/external/tablebases/syzygy/3-4-5
setoption name SyzygyProbeLimit value 5
setoption name SyzygyCache value 0
isready
position fen 6k1/8/8/8/8/8/8/K2Q4 w - - 0 1
go movetime 100
```

An empty `SyzygyPath` or `SyzygyProbeLimit=0` disables probing. `SyzygyCache`
accepts 0–256 MiB and is additional to the advertised `Hash` allocation. The
initial default is zero; cache settings are retained only after the declared
correctness and performance comparison. No service is queried during play.
Changing the dataset or cache settings waits for the active search and
invalidates affected caches. Search information reports `tbhits`.

## Search behavior and limitations

Root probes use both outcomes and DTZ progress information, with the actual
halfmove counter. Returned moves must match Orient's legal moves, including
promotions and en passant; `searchmoves` is respected. Mate, stalemate and
claimable draws retain the existing rule handling. Repetition-sensitive
histories keep ordinary history-aware search rather than accepting an
unconditional decisive tablebase result.

Among equally decisive root moves, wins prefer the smaller DTZ and losses
prefer the larger DTZ. Orient checks actual mate and draw results itself before
selecting a move. The original DTZ encoding can round by one ply, so a quiet
alternative exactly at `DTZ + halfmove = 100` triggers ordinary search rather
than an unconditional tablebase result.

Inside search, WDL shortcuts apply only to supported positions with a reset
halfmove counter, no castling rights and no synthetic null-move ancestry.
Proven wins and losses lie outside ordinary evaluation scores and below the
mate band. A tablebase win is not reported as a known mate distance. Unsupported
positions and unavailable tables fall back to regular search. Missing files are
never interpreted as draws.

The fork keeps the existing Syzygy format. Its optional WDL cache verifies full
position identity and dataset identity, stores only successful raw results and
does not replace game-history checks. Benchmark and correctness evidence must
separate comparison with unchanged upstream Fathom from playing-strength tests.
Neither the presence of tablebases nor a faster probe establishes an Elo gain.

The [follow-up optimization experiment](endgame-tablebase-optimization-002.md)
implements an exact eight-byte cache and root legal-list reuse as research
prototypes. They preserve results but do not pass the declared adoption gates.
Their compile-time options default to OFF; the previous 015 candidate and
zero-cache setting remain the baseline for that experiment.

The [reader optimization experiment 003](endgame-reader-optimization-003.md)
subsequently retains exact eight-bit Huffman length hints in candidate 016.
Final paired trials reduce complete-probe time by 34.60% and covered root-search
time by 31.04% on the measured workloads, preserving all compared results.
The added header storage is bounded at 246 KiB for this collection; table files
and the zero-cache default are unchanged. The earlier experimental options
remain OFF. Existing profiles still target their original checkpoints; the 016
profile is verified separately offline.

The [fixed playing diagnostic](endgame-playing-001-2026-10-28.md) records 64
paired games with that same frozen binary. It improves conversion on the
selected five-piece wins, but also exposes a drawn ending lost after a repeated
position triggers ordinary search. That history-preserving regression target
takes priority over further probe optimization; the result is not an Elo claim.

The local reader fork also propagates memory-mapping failure as an unavailable
probe instead of terminating the process, and releases its file/mapping handles.
An injected-failure regression checks this path. Installation still requires
verified immutable files: this is not a decoder for arbitrary damaged data.
Stop and clock checks surround probes; an arbitrary operating-system storage
stall cannot be given a hard latency guarantee by this synchronous reader.

## Frozen checkpoint and offline bot profile

Create a new checkpoint with the existing checkpoint command plus
`--tablebase-manifest /absolute/path/manifest.json --syzygy-cache 0`. The tool
verifies the full collection, includes the Fathom source and licence in its
source archive, and records the dataset manifest and effective settings. The
large table files remain outside the archive. Existing checkpoints are not
rewritten.

The optional `tablebase_manifest` field in schema-version-1 bot configurations
must refer to the same manifest pinned by the configured checkpoint. Omitting
the field, or setting it to null, preserves the existing tablebase-disabled
profile. A configured manifest is verified against the complete published set
before the bot proceeds. The bridge passes the pinned `SyzygyPath`,
`SyzygyProbeLimit` and `SyzygyCache` settings and requires Orient to acknowledge
the loaded five-piece collection. It records these settings and the manifest in
session evidence.

Run the existing offline preflight command with the new profile:

```sh
python3 tools/lichess_bot.py preflight --config /absolute/path/endgame-profile.json
```

This verifies the frozen engine and files, performs a real tablebase probe with
a legal returned move and nonzero `tbhits`, and runs the existing bounded start
position search. It does not read a token, contact Lichess or start a game.
Live play remains a separate explicitly selected invocation. Tablebase use in
play does not enable tablebases in self-play generation or neural training.
