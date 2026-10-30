#!/usr/bin/env python3
"""Curate immutable 007 evidence records and a portable 007 release bundle.

Run from the full local research workspace. Actual table files, Cargo caches,
compiler intermediates and external measurement opponents are never bundled.
Only named hash-bound historical Orient/Fathom executables are retained as
non-executed provenance, together with their licences and compiler records.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile

from verify_public_evidence import digest, read_json

COMPONENT = Path(__file__).resolve().parents[1]
P007 = Path('artifacts/investigations/tablebases-007')
P006 = Path('artifacts/investigations/tablebases-006')
ASSET = 'skylance-evidence-007.tar.gz'
PREFIX = 'skylance-evidence-007'
RELEASE = 'https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/'
PUBLIC007 = ('protocol/PROTOCOL.md', 'protocol/freeze.json', 'protocol/REPAIR-002.md',
             'performance/acceptance-002/result.json', 'verification/correctness-001/result.json',
             'independent-recomputation.json', 'retained-source.json', 'baseline-source.json',
             'history-guidance-proof.md', 'code-review.md')
PUBLIC006 = ('PROTOCOL.md', 'protocol/freeze.json', 'performance/run001/result.json',
             'performance/run001/statistics.json', 'performance/run001/per-material.csv',
             'performance/run001/latency-distributions.json', 'independent-audit-final.json')


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def allowed(relative):
    return (relative.suffix not in ('.rtbw', '.rtbz', '.rtbm', '.pyc')
            and '__pycache__' not in relative.parts
            and 'cargo-cache' not in relative.parts
            and 'reader-comparison' not in relative.parts)


def records(value):
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
            yield value
        for child in value.values():
            yield from records(child)
    elif isinstance(value, list):
        for child in value:
            yield from records(child)


def select_files(component):
    component = component.resolve(strict=True)
    selected, substitutions = {}, []

    def add(path, expected=None):
        path = Path(path)
        relative = path.relative_to(component)
        required_frozen_bytecode = (expected is not None and relative.suffix == '.pyc'
                                    and relative.is_relative_to(P007 / 'candidates/acceptance-source'))
        if (not allowed(relative) and not required_frozen_bytecode) or not path.is_file() or path.is_symlink():
            raise ValueError('forbidden or missing package input: ' + str(relative))
        source = path
        if expected and digest(source) != expected:
            for snapshot in ('baseline-source', 'candidates/acceptance-source'):
                candidate = component / P007 / snapshot / relative
                if candidate.is_file() and digest(candidate) == expected:
                    source = candidate
                    substitutions.append({'path': relative.as_posix(),
                                          'source': source.relative_to(component).as_posix(),
                                          'sha256': expected})
                    break
            else:
                raise ValueError('historical artifact no longer matches: ' + str(relative))
        previous = selected.get(relative)
        if previous and digest(previous) != digest(source):
            # A hash-bound record takes precedence over the current root helper.
            if expected is None:
                return
            if digest(previous) != expected:
                selected[relative] = source
        else:
            selected[relative] = source

    # Preserve successful, rejected and interrupted 007 records. Exclude whole
    # compiler trees; the recursive hash closure below selects named provenance.
    for path in sorted((component / P007).rglob('*')):
        relative = path.relative_to(component / P007)
        if path.is_file() and 'build' not in relative.parts and allowed(relative):
            add(path)
    for relative in PUBLIC006:
        add(component / P006 / relative)
    for investigation, subpaths in (
        ('002', ('comparison/positions.fen', 'comparison/special.fen')),
        ('005', ('fixtures/continuity-shared-valid.fen', 'fixtures/holdout-shared-valid.fen',
                 'fixtures/special-shared-valid.fen', 'fixtures/startup.fen', 'fixtures/search48.fen', 'fixtures/hot145.fen')),
        ('006', ('fixtures/primary.fen',))):
        for relative in subpaths:
            add(component / ('artifacts/investigations/tablebases-' + investigation) / relative)

    # Complete the original native source/build/controller and raw-output hash
    # bindings without following the table manifest's individual data records.
    seeds = [component / P007 / name for name in
             ('correctness-config.json', 'performance-config002.json', 'protocol/freeze.json',
              'verification/correctness-001/result.json', 'performance/acceptance-002/result.json')]
    pending, visited = list(seeds), set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        for record in records(read_json(path)):
            target = Path(record['path'])
            if not target.is_absolute():
                continue
            if not target.is_relative_to(component):
                raise ValueError('artifact is outside the component: ' + str(target))
            add(target, record['sha256'])
            if target.suffix == '.json' and target not in visited:
                pending.append(target)

    # Historical controller imports and the unchanged upstream comparison build
    # need these small root dependencies. Keep old versions where hash-bound.
    frozen = component / P007 / 'baseline-source'
    for relative in ('LICENSE', 'src/chess.cpp', 'tools/tablebase_probe.cpp'):
        add(component / relative)
    for directory in ('include', 'external/fathom-upstream'):
        for path in sorted((component / directory).rglob('*')):
            if path.is_file() and allowed(path.relative_to(component)):
                add(path)
    for name in ('experiment.py', 'tablebase_manifest.py', 'download_tablebases.py', 'syzygy345.json',
                 'measure_reader_comparison.py', 'verify_reader_memory.py'):
        relative = Path('tools') / name
        add(component / relative)
        if relative not in selected and (frozen / relative).is_file():
            selected[relative] = frozen / relative
    for name in ('package_evidence.py', 'verify_public_evidence.py', 'reproduce_acceptance.py'):
        path = component / 'tools' / name
        if path.is_file():
            add(path)
    return selected, substitutions


def write_public(component, public_root, campaign, names):
    destination = public_root / ('tablebases-' + campaign)
    rows = []
    for name in names:
        source = component / ('artifacts/investigations/tablebases-' + campaign) / name
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError('refusing to replace changed public original: ' + str(target))
        shutil.copyfile(source, target)
        rows.append({'path': name, 'size': target.stat().st_size, 'sha256': digest(target),
                     'original_path': source.relative_to(component).as_posix()})
    return destination, rows


def build(component, public_root, out, force=False):
    component = component.resolve(strict=True)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / ASSET
    if archive.exists() and not force:
        raise ValueError('release archive already exists; use --force to rebuild this generated asset')
    selected, substitutions = select_files(component)
    members = []
    for relative, source in sorted(selected.items()):
        members.append({'path': 'orient-endgame-component/' + relative.as_posix(),
                        'size': source.stat().st_size, 'sha256': digest(source),
                        'executable': bool(source.stat().st_mode & 0o111)})
    readme = ('''# Frozen 007 evidence bundle\n\nThis archive preserves the historical 007 campaign, raw correctness outputs,\nquery/search/startup/memory records, source snapshots, controller dependencies\nand only named original Orient/Fathom binary provenance. Actual Syzygy table\nfiles and external opponent engines are excluded. It does not measure HEAD.\n\nVerify and independently recompute all 007 raw results offline, without running\nany included executable or downloading table data:\n\n    python3 orient-endgame-component/tools/verify_public_evidence.py --bundle-root .\n\nThe verifier maps old absolute paths in memory; original records stay unchanged.\nFor a fresh timing run, use the source checkout's tools/reproduce_acceptance.py\nand download the separately pinned tables. The old reproduce.py rebuilds only\nthe original frozen baseline/candidate. Source/engine licences remain included.\n\nSelected 006 summary/protocol records are included as context. Complete 006 raw\nlatency/reproduction dependencies are not included here; no new independent\n006 raw-statistics verification is claimed for this archive.\n''').encode()
    members.append({'path': 'README.md', 'size': len(readme), 'sha256': hashlib.sha256(readme).hexdigest(), 'executable': False})
    manifest = {'schema_version': 1, 'kind': 'skylance-007-evidence-bundle',
                'original_component_root': str(component), 'files': members,
                'historical_source_substitutions': substitutions,
                'scope': 'complete frozen 007 raw acceptance audit and reproduction dependencies; selected 006 summaries only',
                'excluded': ['actual Syzygy data', 'compiler intermediates', 'Cargo caches', 'external measurement opponent engines']}
    temporary = archive.with_suffix(archive.suffix + '.tmp')
    with temporary.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w') as tar:
        for row in members:
            relative = row['path']
            if relative == 'README.md':
                data = readme
            else:
                data = selected[Path(relative).relative_to('orient-endgame-component')].read_bytes()
            if hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('input changed while packaging: ' + relative)
            info = tarfile.TarInfo(PREFIX + '/' + relative)
            info.size, info.mode, info.mtime = len(data), 0o755 if row['executable'] else 0o644, 0
            tar.addfile(info, io.BytesIO(data))
        data = json_bytes(manifest)
        info = tarfile.TarInfo(PREFIX + '/EVIDENCE-MANIFEST.json')
        info.size, info.mode, info.mtime = len(data), 0o644, 0
        tar.addfile(info, io.BytesIO(data))
    temporary.replace(archive)
    checksum = digest(archive)
    (out / (ASSET + '.sha256')).write_text(checksum + '  ' + ASSET + '\n', encoding='utf-8')
    descriptor = {'filename': ASSET, 'bytes': archive.stat().st_size, 'sha256': checksum,
                  'url': RELEASE + ASSET, 'checksum_url': RELEASE + ASSET + '.sha256'}
    for campaign, names in (('007', PUBLIC007),):
        destination, rows = write_public(component, public_root, campaign, names)
        public = {'schema_version': 1, 'kind': 'skylance-public-evidence', 'campaign': campaign,
                  'files': rows, 'release': descriptor,
                  'scope': 'immutable selected historical records; raw 007 audit in release archive' if campaign == '007'
                  else 'selected historical 006 summaries; complete 006 raw reproduction archive not published'}
        (destination / 'MANIFEST.json').write_bytes(json_bytes(public))
    return {'archive': str(archive), **descriptor, 'files': len(members),
            'uncompressed_bytes': sum(row['size'] for row in members)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component-root', type=Path, default=COMPONENT)
    parser.add_argument('--public-root', type=Path, default=COMPONENT.parent / 'evidence')
    parser.add_argument('--out', type=Path, default=COMPONENT.parent / 'dist')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.component_root, args.public_root, args.out, args.force), indent=2))
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, 'Evidence packaging failed: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
