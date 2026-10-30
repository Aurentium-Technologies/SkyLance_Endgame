"""Negative integrity cases for independently downloadable evidence indexes."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from verify_public_evidence import audit_bundle, read_json, verify_manifest


class PublicEvidenceIntegrity(unittest.TestCase):
    def fixture(self, root):
        data = b'frozen result\n'
        (root / 'result.json').write_bytes(data)
        manifest = {'schema_version': 1, 'kind': 'skylance-public-evidence',
                    'files': [{'path': 'result.json', 'size': len(data),
                               'sha256': hashlib.sha256(data).hexdigest()}]}
        (root / 'MANIFEST.json').write_text(json.dumps(manifest))
        return manifest

    def test_intact_index_passes_and_changed_payload_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            _, result = verify_manifest(root, 'MANIFEST.json', 'skylance-public-evidence')
            self.assertEqual(result['files'], 1)
            (root / 'result.json').write_bytes(b'changed value\n')
            with self.assertRaisesRegex(ValueError, 'checksum/size mismatch'):
                verify_manifest(root, 'MANIFEST.json', 'skylance-public-evidence')

    def test_empty_or_duplicate_inventory_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.fixture(root)
            for rows in ([], manifest['files'] * 2):
                with self.subTest(rows=rows):
                    (root / 'MANIFEST.json').write_text(json.dumps({**manifest, 'files': rows}))
                    with self.assertRaises(ValueError):
                        verify_manifest(root, 'MANIFEST.json', 'skylance-public-evidence')

    def test_manifest_rejects_noncanonical_and_parent_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.fixture(root)
            for name in ('../result.json', './result.json', '/result.json', 'sub/../result.json', 'a\\b'):
                row = {**manifest['files'][0], 'path': name}
                (root / 'MANIFEST.json').write_text(json.dumps({**manifest, 'files': [row]}))
                with self.subTest(path=name), self.assertRaises(ValueError):
                    verify_manifest(root, 'MANIFEST.json', 'skylance-public-evidence')

    def test_symlink_is_not_accepted_as_frozen_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'result.json').rename(root / 'original.json')
            try:
                (root / 'result.json').symlink_to(root / 'original.json')
            except OSError:
                self.skipTest('host does not permit symlinks')
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                verify_manifest(root, 'MANIFEST.json', 'skylance-public-evidence')

    def test_wrong_scope_and_boolean_size_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.fixture(root)
            for changes in ({'kind': 'unrelated'}, {'files': [{**manifest['files'][0], 'size': True}]}):
                (root / 'MANIFEST.json').write_text(json.dumps({**manifest, **changes}))
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    verify_manifest(root, 'MANIFEST.json', 'skylance-public-evidence')

    def test_auditor_and_saved_result_must_both_be_listed_before_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = 'orient-endgame-component/artifacts/investigations/tablebases-007/'
            campaign = root / prefix
            campaign.mkdir(parents=True)
            (campaign / 'audit_improvements002.py').write_text(
                "raise RuntimeError('unverified auditor code ran')\n")
            (campaign / 'independent-recomputation.json').write_text('{}')
            for listed in ([], [{'path': prefix + 'audit_improvements002.py'}]):
                manifest = {'original_component_root': '/historical/component', 'files': listed}
                with self.subTest(listed=listed), self.assertRaisesRegex(ValueError, 'absent from verified inventory'):
                    audit_bundle(root, manifest)

    def test_manifest_cannot_substitute_another_audit_algorithm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = 'orient-endgame-component/artifacts/investigations/tablebases-007/'
            campaign = root / prefix
            campaign.mkdir(parents=True)
            (campaign / 'audit_improvements002.py').write_text('def run(): return {}\n')
            (campaign / 'independent-recomputation.json').write_text('{}')
            manifest = {'original_component_root': '/historical/component', 'files': [
                {'path': prefix + n} for n in ('audit_improvements002.py', 'independent-recomputation.json')]}
            with self.assertRaisesRegex(ValueError, 'unrecognized frozen acceptance auditor'):
                audit_bundle(root, manifest)

    def test_frozen_auditor_cannot_read_an_unlisted_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            component = root / 'orient-endgame-component'
            prefix = 'artifacts/investigations/tablebases-007/'
            campaign = component / prefix
            campaign.mkdir(parents=True)
            source = ("import json\nfrom pathlib import Path\n"
                      "def run(): return json.loads(Path('/historical/component/secret.json').read_text())\n")
            (campaign / 'audit_improvements002.py').write_text(source)
            (campaign / 'independent-recomputation.json').write_text('{}')
            (component / 'secret.json').write_text('{}')
            manifest = {'original_component_root': '/historical/component', 'files': [
                {'path': 'orient-endgame-component/' + prefix + n}
                for n in ('audit_improvements002.py', 'independent-recomputation.json')]}
            with patch('verify_public_evidence.FROZEN_AUDITOR_SHA256', hashlib.sha256(source.encode()).hexdigest()):
                with self.assertRaisesRegex(ValueError, 'absent from verified inventory'):
                    audit_bundle(root, manifest)

    def test_duplicate_keys_and_nonfinite_numbers_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'value.json'
            for value in ('{"result":1,"result":2}', '{"result":NaN}'):
                path.write_text(value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    read_json(path)


if __name__ == '__main__':
    unittest.main()
