# Third-party notices

SkyLance was developed under the Orient working name. Existing copyright and
licence notices in the component and historical material are retained.

The maintained Syzygy reader in `orient-endgame-component/third_party/fathom/`
uses the [Fathom MIT licence](orient-endgame-component/third_party/fathom/LICENSE).
Its [upstream pin](orient-endgame-component/third_party/fathom/UPSTREAM.json),
[fork record](orient-endgame-component/third_party/fathom/FORK.json), attribution
and sequential patches describe the imported reader and local changes. Fathom's
README discloses its probing-code ancestry. The unchanged comparison copy in
`orient-endgame-component/external/fathom-upstream/` retains its own notices.

The optional Rust comparison client under
`orient-endgame-component/tools/shakmaty_reader_compare/` uses
[GPL-3.0-or-later](orient-endgame-component/tools/shakmaty_reader_compare/COPYING).
Its separate Shakmaty checkout and registry cache are local research dependencies
excluded from this source repository. The comparison client is not linked into
the C++ engine. Historical raw artifacts and external measurement opponents also
remain local. No weights or external engine evaluation labels are shipped.

The table downloader records publisher URLs and SHA-256 values in
`orient-endgame-component/tools/syzygy345.json`. Downloaded solved-position data
is optional, attributed separately and excluded from Git.
