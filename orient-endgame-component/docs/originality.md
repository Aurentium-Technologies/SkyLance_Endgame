# Originality and provenance

This historical report names supporting files from the wider local research archive. Available public records and separate downloads are listed in the [evidence index](../../evidence/README.md); local-only paths below are not GitHub download links.


Orient's search, position evaluation, primary move generator and learned networks
are developed independently for this project. The goal is to develop our own
playing algorithm, with the longer-term ambition of surpassing Stockfish under
controlled comparison. Neither that ambition nor a tablebase integration is
evidence that Orient is stronger.

The owner clarified the originality boundary on 27 October 2026: shared solved
endgame data and a declared tablebase reader are allowed. Orient therefore
includes a pinned, MIT-licensed local fork of Fathom and can read public Syzygy
tables for positions with up to five pieces, counting both kings. The reader is
a separate library; its internal probing and helper routines are third-party
code. Its historical relationship to Stockfish/Cfish is recorded explicitly in
[the fork metadata](../third_party/fathom/UPSTREAM.json). Orient's ordinary search,
evaluation and primary legal-move generation are not replaced with Stockfish's
implementation. No competing pretrained weights or opening book are imported.

## Boundary between ideas and implementation

Published algorithmic ideas and documented standards are allowed. Orient independently implements bitboard attacks, reversible moves, Zobrist hashing, tapered evaluation, alpha-beta/PVS, quiescence, transposition storage, move ordering, and subsequent measured pruning experiments. Initial evaluation values and positional formulas are documented with their rationale, rather than copied from a competing engine.

The opening sampler uses Orient's own legal moves and seeded random choices;
it imports no opening games or engine labels. The paired development-test
calculator and its local Monte Carlo calibrator are independently written from
the normalized-Elo constrained-likelihood equations in Michel Van den Bergh's
[practical note](https://cantate.be/Fishtest/normalized_elo_practical.pdf),
section 4.1. The note is an algorithm reference, not an engine implementation or
training corpus. Python/C++ crosschecks and finite synthetic operating-error
tests are preserved separately from actual chess experiments. They establish
no playing-strength rating.

The [UCI protocol](https://backscattering.de/chess/uci/) defines text communication. Canonical perft positions and counts are correctness fixtures: they are not move decisions or training labels. FEN and PGN are interchange formats.

## External tools and opponents

Fastchess runs external engine matches. It is not included or linked in Orient's engine target. Benchmark opponents run as separate processes. We may read their published rating entries, licences, release metadata and UCI option descriptions to pin lawful, reproducible tests, but do not inspect or copy their chess implementation.

Keep downloaded tool/opponent binaries in `external/`, excluded by `.gitignore`, with source URLs, version identities, archive and binary hashes, and applicable licence files. Do not redistribute these binaries under Orient's licence.

The Fathom exception is source-vendored in `third_party/fathom` with its own MIT
licence and upstream identity. Syzygy files remain in ignored local storage;
their published checksums, local SHA-256 hashes and sizes are recorded in a
manifest. Checkpoint archives include the reader sources and licence, and pin
the tablebase manifest and effective settings when endgames are enabled. See
[endgame setup and limitations](endgame-tablebases.md).

## Training provenance

The optional neural evaluator, self-player, CPU trainer and integer export are original implementations. Every training run initializes weights randomly and accepts only verified Orient self-play manifests. Positions, search labels and completed-game outcomes come exclusively from Orient. Match games against external opponents are measurement evidence, not training data. Whole opening groups split across training and validation, and shared model-equivalent positions are removed from validation. Development, confirmation and holdout opening positions are excluded from training, together with entire games starting at those positions and their model-equivalent reflections. Generator binary/source hashes, options, seeds, data hashes, training configuration and network export agreement are retained. PyTorch is an optional numerical training dependency. See the learning workflow (local archive: `../learning/README.md`).

For this release, self-play generation never attaches a tablebase provider and
neural training remains Orient-only. Tablebase test positions, probe outcomes
and games using external opponents are not admitted into training. Allowing
shared endgame data during play does not change the training-data policy.

Every claimed improvement must identify the candidate and baseline builds, settings, game records, statistical test, outcome, and any reliability failure. Ratings remain explicitly unmeasured until supported by a completed experiment.
