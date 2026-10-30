#!/usr/bin/env python3
"""Publish a completed current-source acceptance run without table data.

Small immutable records enter evidence/tablebases-008. Raw output, source and
binary provenance form a separate checksummed release archive. Historical 007
records are preserved and are used only as the fixed acceptance controllers.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile

from package_evidence import allowed, json_bytes, records
from verify_public_evidence import digest, read_json

COMPONENT = Path(__file__).resolve().parents[1]
P007 = Path('artifacts/investigations/tablebases-007')
PUBLIC = ('protocol/PROTOCOL.md', 'protocol/freeze.json', 'baseline-source.json',
          'candidate-source.json', 'run-source-binding.json', 'correctness-config.json',
          'performance-config002.json', 'verification/correctness-001/result.json',
          'performance/acceptance-002/result.json', 'independent-recomputation.json',
          'runtime-source-match.json', 'final-runtime-binary-equivalence.json')
ASSET = 'skylance-evidence-008.tar.gz'
PREFIX = 'skylance-evidence-008'
RELEASE = 'https://github.com/Aurentium-Technologies/SkyLance_Endgame/releases/download/v0.1.0/'


def select_files(component, run):
    component, run = component.resolve(strict=True), run.resolve(strict=True)
    if not run.is_relative_to(component):
        raise ValueError('acceptance run must be within its component root')
    selected = {}

    def add(path, expected=None):
        path = Path(path)
        if not path.is_absolute() or not path.is_relative_to(component):
            raise ValueError('artifact outside component root: ' + str(path))
        relative = path.relative_to(component)
        if not allowed(relative) or path.is_symlink() or not path.is_file():
            raise ValueError('forbidden or missing acceptance artifact: ' + str(relative))
        if expected and digest(path) != expected:
            raise ValueError('acceptance artifact changed: ' + str(relative))
        selected[relative] = path

    # Keep all completed samples and logs, not just favourable summaries. Only
    # named executables/cache/commands from the hash closure enter build/.
    for path in sorted(run.rglob('*')):
        relative = path.relative_to(run)
        if path.is_file() and 'build' not in relative.parts and allowed(relative):
            add(path)
    pending = [run / name for name in PUBLIC if name.endswith('.json')]
    visited = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        for record in records(read_json(path)):
            target = Path(record['path'])
            if not target.is_absolute():
                continue
            add(target, record['sha256'])
            if target.suffix == '.json' and target not in visited:
                pending.append(target)

    # These originals are templates/controllers for repeating the same gates.
    # Their raw 007 outputs belong to the separate historical evidence asset.
    for name in ('correctness-config.json', 'performance-config002.json', 'reproduce.py',
                 'verify_improvements.py', 'measure_improvements002.py', 'audit_saved_run.py',
                 'audit_improvements002.py', 'protocol/PROTOCOL.md', 'protocol/REPAIR-002.md'):
        add(component / P007 / name)
    for path in sorted((component / P007 / 'baseline-source').rglob('*')):
        if path.is_file() and allowed(path.relative_to(component)):
            add(path)
    for name in ('LICENSE', 'src/chess.cpp', 'tools/tablebase_probe.cpp'):
        add(component / name)
    for directory in ('include', 'external/fathom-upstream'):
        for path in sorted((component / directory).rglob('*')):
            if path.is_file() and allowed(path.relative_to(component)):
                add(path)
    for name in ('experiment.py', 'tablebase_manifest.py', 'download_tablebases.py', 'syzygy345.json',
                 'measure_reader_comparison.py', 'verify_reader_memory.py', 'reproduce_acceptance.py',
                 'verify_public_evidence.py', 'package_evidence.py', 'package_acceptance_evidence.py'):
        add(component / 'tools' / name)
    aborted = run.parent / 'preflight-aborted.json'
    if aborted.is_file():
        add(aborted)
    return selected


def build(component, run, public_root, out, force=False):
    component, run = component.resolve(strict=True), run.resolve(strict=True)
    result = read_json(run / 'performance/acceptance-002/result.json')
    proof = read_json(run / 'verification/correctness-001/result.json')
    audit = read_json(run / 'independent-recomputation.json')
    if result.get('status') != 'passed' or proof.get('status') != 'passed' or audit.get('status') != 'passed':
        raise ValueError('publish only a complete and independently recomputed campaign')
    if result['decision']['adopt'] != audit['adopt']:
        raise ValueError('controller and separate audit disagree')
    out.mkdir(parents=True, exist_ok=True)
    archive = out / ASSET
    if archive.exists() and not force:
        raise ValueError('release asset exists; --force is required to regenerate it')
    selected = select_files(component, run)
    members = [{'path': 'orient-endgame-component/' + relative.as_posix(),
                'size': path.stat().st_size, 'sha256': digest(path),
                'executable': bool(path.stat().st_mode & 0o111)}
               for relative, path in sorted(selected.items())]
    readme = ('''# Current-source acceptance evidence 008\n\nThis is the new frozen pre-007-baseline versus post-review candidate campaign.\nIt preserves every correctness output and timed sample, source/binary bindings,\ncontroller dependencies and the recorded verdict, including any failed gate.\nActual Syzygy tables, external engine opponents and compiler intermediates are\nexcluded. Named historical executables are provenance only; do not execute them.\n\nVerify all archive bytes and independently recompute the recorded raw results\noffline without executing a binary or downloading table data:\n\n    python3 orient-endgame-component/tools/verify_public_evidence.py --bundle-root .\n\nA fresh run needs the separately downloaded and pinned tables. From an ordinary\ncurrent source checkout, select the current component explicitly:\n\n    python3 orient-endgame-component/tools/reproduce_acceptance.py --out /tmp/new-acceptance --evidence-root /path/to/skylance-evidence-008/orient-endgame-component --candidate-source "$PWD/orient-endgame-component" --tables-manifest "$PWD/orient-endgame-component/external/tablebases/syzygy/3-4-5/manifest.json"\n\nOriginal records are not rewritten. Relocation maps old absolute paths in memory.\nThis archive is separate from the historical 007 evidence and makes no competitor\nsuperiority, statistical-confidence, whole-engine strength or Elo claim.\n''').encode()
    members.append({'path': 'README.md', 'size': len(readme), 'sha256': hashlib.sha256(readme).hexdigest(), 'executable': False})
    manifest = {'schema_version': 1, 'kind': 'skylance-acceptance-evidence-bundle',
                'original_component_root': str(component), 'campaign_relative': run.relative_to(component).as_posix(),
                'auditor_relative': (P007 / 'audit_improvements002.py').as_posix(),
                'saved_audit_relative': (run.relative_to(component) / 'independent-recomputation.json').as_posix(),
                'files': members, 'scope': 'complete fixed current-source acceptance audit and reproduction dependencies',
                'excluded': ['actual Syzygy data', 'compiler intermediates', 'Cargo caches', 'external opponent engines']}
    temporary = archive.with_suffix(archive.suffix + '.tmp')
    with temporary.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w') as tar:
        for row in members:
            data = readme if row['path'] == 'README.md' else selected[Path(row['path']).relative_to('orient-endgame-component')].read_bytes()
            if hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('input changed while packaging: ' + row['path'])
            info = tarfile.TarInfo(PREFIX + '/' + row['path'])
            info.size, info.mode, info.mtime = len(data), 0o755 if row['executable'] else 0o644, 0
            tar.addfile(info, io.BytesIO(data))
        data = json_bytes(manifest); info = tarfile.TarInfo(PREFIX + '/EVIDENCE-MANIFEST.json')
        info.size, info.mode, info.mtime = len(data), 0o644, 0
        tar.addfile(info, io.BytesIO(data))
    temporary.replace(archive)
    checksum = digest(archive)
    (out / (ASSET + '.sha256')).write_text(checksum + '  ' + ASSET + '\n')
    descriptor = {'filename': ASSET, 'bytes': archive.stat().st_size, 'sha256': checksum,
                  'url': RELEASE + ASSET, 'checksum_url': RELEASE + ASSET + '.sha256'}
    public = public_root / 'tablebases-008'; rows = []
    for name in PUBLIC:
        source, target = run / name, public / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError('refusing to replace a different completed public campaign record')
        shutil.copyfile(source, target)
        rows.append({'path': name, 'size': target.stat().st_size, 'sha256': digest(target),
                     'original_path': source.relative_to(component).as_posix()})
    statistics_path = public / 'statistics.csv'
    with statistics_path.open('w', newline='') as stream:
        writer = csv.writer(stream); writer.writerow(['metric', 'candidate_over_baseline', 'change_percent', 'regression_gate'])
        ratios = result['decision']['time_ratios_candidate_over_baseline']
        gates = set(result['decision']['regression_gate_keys'])
        for name, ratio in sorted(ratios.items()):
            writer.writerow([name, format(ratio, '.15g'), format(100 * (ratio - 1), '.12g'), name in gates])
    rows.append({'path': 'statistics.csv', 'size': statistics_path.stat().st_size, 'sha256': digest(statistics_path), 'scope': 'derived directly from completed result ratios'})
    (public / 'MANIFEST.json').write_bytes(json_bytes({'schema_version': 1, 'kind': 'skylance-public-evidence',
        'campaign': '008', 'files': rows, 'release': descriptor,
        'scope': 'immutable current-source acceptance records and derived aggregate ratios; all raw samples in release asset'}))
    return {'archive': str(archive), **descriptor, 'files': len(members),
            'uncompressed_bytes': sum(row['size'] for row in members), 'adopt': audit['adopt']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component-root', type=Path, default=COMPONENT)
    parser.add_argument('--run-root', type=Path, default=COMPONENT / 'artifacts/investigations/tablebases-008/run-002')
    parser.add_argument('--public-root', type=Path, default=COMPONENT.parent / 'evidence')
    parser.add_argument('--out', type=Path, default=COMPONENT.parent / 'dist')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.component_root, args.run_root, args.public_root, args.out, args.force), indent=2))
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, 'Acceptance evidence packaging failed: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
