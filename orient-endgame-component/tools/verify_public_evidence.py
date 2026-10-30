#!/usr/bin/env python3
"""Verify published evidence bytes and recompute recorded acceptance results offline.

Historical absolute paths are resolved in memory. Original JSON and scripts are
never rewritten; no binary is executed and no table data or network is required.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

# Preserve the actual separately authored 007 raw-audit algorithm. A manifest
# cannot nominate new executable Python merely by hashing it itself.
FROZEN_AUDITOR_SHA256 = '70ac55e1630aea6875bfce21a889f0dc1861372ee8d1fccdad56205f9ccdf96e'


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def read_json(path):
    def reject(value):
        raise ValueError('non-finite JSON number: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      object_pairs_hook=unique, parse_constant=reject)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def local_file(root, name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise ValueError('expected a canonical relative POSIX evidence path')
    relative = PurePosixPath(name)
    if (relative.is_absolute() or relative.as_posix() != name
            or not relative.parts or any(p in ('.', '..') for p in relative.parts)):
        raise ValueError('unsafe evidence path: ' + name)
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('symlinks are not evidence files: ' + name)
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('missing ordinary evidence file: ' + name)
    return path


def verify_manifest(root, filename, expected_kind):
    root = Path(root).resolve(strict=True)
    manifest = read_json(local_file(root, filename))
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1
            or manifest.get('kind') not in (expected_kind if isinstance(expected_kind, tuple) else (expected_kind,))):
        raise ValueError('unexpected evidence manifest schema or scope')
    rows = manifest.get('files')
    if not isinstance(rows, list) or not rows:
        raise ValueError('evidence manifest must list nonempty file records')
    seen, total = set(), 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid evidence file record')
        name = row.get('path')
        path = local_file(root, name)
        if name in seen or name == filename:
            raise ValueError('duplicate or self-referencing evidence file')
        seen.add(name)
        if type(row.get('size')) is not int or row['size'] < 0:
            raise ValueError('invalid evidence file size: ' + name)
        if not isinstance(row.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
            raise ValueError('invalid evidence SHA-256: ' + name)
        if path.stat().st_size != row['size'] or digest(path) != row['sha256']:
            raise ValueError('evidence checksum/size mismatch: ' + name)
        total += row['size']
    return manifest, {'files': len(rows), 'bytes': total, 'hashes': 'passed'}


def equal_results(actual, expected):
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and set(actual) == set(expected)
                and all(equal_results(actual[k], v) for k, v in expected.items()))
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected)
                and all(equal_results(a, b) for a, b in zip(actual, expected)))
    if type(expected) is float:
        return type(actual) in (int, float) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-15)
    return type(actual) is type(expected) and actual == expected


def audit_bundle(bundle_root, manifest):
    bundle_root = Path(bundle_root).resolve(strict=True)
    component = bundle_root / 'orient-endgame-component'
    listed = {row['path'] for row in manifest['files']}

    def listed_file(path):
        relative = path.relative_to(bundle_root).as_posix()
        if relative not in listed:
            raise ValueError('auditor input is absent from verified inventory: ' + relative)
        return path

    original_root = Path(manifest.get('original_component_root', ''))
    if not original_root.is_absolute():
        raise ValueError('bundle must identify its original component path')
    campaign_relative = manifest.get('campaign_relative', 'artifacts/investigations/tablebases-007')
    directory = PurePosixPath(campaign_relative)
    if (directory.is_absolute() or directory.as_posix() != campaign_relative
            or not directory.parts or any(p in ('.', '..') for p in directory.parts)):
        raise ValueError('invalid campaign directory')
    campaign = component / directory
    if not campaign.is_dir() or not campaign.resolve().is_relative_to(component):
        raise ValueError('campaign directory is absent or outside the bundle')
    auditor = local_file(component, manifest.get('auditor_relative',
        'artifacts/investigations/tablebases-007/audit_improvements002.py'))
    saved_audit = local_file(component, manifest.get('saved_audit_relative',
        'artifacts/investigations/tablebases-007/independent-recomputation.json'))
    listed_file(auditor)
    listed_file(saved_audit)
    if digest(auditor) != FROZEN_AUDITOR_SHA256:
        raise ValueError('unrecognized frozen acceptance auditor')
    spec = importlib.util.spec_from_file_location('skylance_frozen_007_auditor', auditor)
    if spec is None or spec.loader is None:
        raise ValueError('cannot load frozen independent auditor')
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous

    def relocated_path(*parts):
        path = Path(*parts)
        if path.is_absolute():
            if path.is_relative_to(original_root):
                path = component / path.relative_to(original_root)
            if not path.is_relative_to(bundle_root):
                raise ValueError('unmapped path outside evidence bundle: ' + str(path))
        return listed_file(path)

    # The original code uses its Path global for every file read and hash. Only
    # the resolver is replaced; dictionaries and hash-bound source bytes remain
    # untouched. Recomputed values and gates are compared with the saved audit.
    module.Path = relocated_path
    module.P = campaign
    result = module.run()
    expected = read_json(saved_audit)
    if not equal_results(result, expected):
        raise ValueError('raw recomputation differs from original independent audit')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--public-dir', type=Path, help='Small committed evidence index directory')
    group.add_argument('--bundle-root', type=Path, help='Extracted acceptance evidence directory')
    args = parser.parse_args()
    try:
        if args.public_dir:
            _, checked = verify_manifest(args.public_dir, 'MANIFEST.json', 'skylance-public-evidence')
            result = {'status': 'passed', 'scope': 'published index files; raw recomputation requires the release bundle', **checked}
        else:
            manifest, checked = verify_manifest(args.bundle_root, 'EVIDENCE-MANIFEST.json',
                ('skylance-007-evidence-bundle', 'skylance-acceptance-evidence-bundle'))
            result = {'status': 'passed', **checked, 'raw_recomputation': audit_bundle(args.bundle_root, manifest),
                      'scope': 'all listed bytes plus recorded acceptance raw correctness/timing/memory/startup recomputation; no binaries executed'}
    except (OSError, ValueError, TypeError, KeyError, ImportError) as error:
        print('Evidence verification failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
