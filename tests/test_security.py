"""Security boundaries: fail closed on role/configuration, tampering and fixed CVEs."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


entrypoint = module('entrypoint', 'container/entrypoint.py')
gate = module('gate', 'scripts/vulnerability-gate.py')


class ConfigurationTests(unittest.TestCase):
    def config(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text(text)
            return entrypoint.load_config(path)

    def test_defaults(self):
        self.assertEqual(entrypoint.load_config('container/config.json')['bind'], '127.0.0.1')

    def test_remote_requires_opt_out(self):
        for address in ['0.0.0.0', '::', '192.0.2.1']:
            config = dict(bind=address, port=50051, allow_unauthenticated_remote=False)
            with self.assertRaisesRegex(ValueError, 'non-loopback bind requires'):
                self.config(json.dumps(config))
            config['allow_unauthenticated_remote'] = True
            self.config(json.dumps(config))

    def test_invalid_configuration(self):
        for text in ['{', '{}', '[]', '{"bind":"127.0.0.1","bind":"0.0.0.0"}',
                     '{"bind":"localhost","port":50051,"allow_unauthenticated_remote":false}',
                     '{"bind":"127.0.0.1","port":80,"allow_unauthenticated_remote":false}',
                     '{"bind":"127.0.0.1","port":true,"allow_unauthenticated_remote":false}',
                     '{"bind":"127.0.0.1","port":50051,"allow_unauthenticated_remote":"false"}']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.config(text)

    def test_missing_configuration(self):
        with self.assertRaisesRegex(ValueError, 'cannot read configuration'):
            entrypoint.load_config('/absent-sail-config')

    def test_no_arbitrary_command(self):
        for args in [[], ['sh'], ['worker'], ['spark-connect', '--ip', '0.0.0.0']]:
            with self.assertRaisesRegex(ValueError, 'only the spark-connect role'):
                entrypoint.validate_runtime(args, {})

    def test_no_root_or_upstream_overrides(self):
        with patch.object(entrypoint.os, 'getuid', return_value=0):
            with self.assertRaisesRegex(ValueError, 'non-root'):
                entrypoint.validate_runtime(['spark-connect'], {})
        with patch.object(entrypoint.os, 'getuid', return_value=10001), patch.object(entrypoint.os, 'geteuid', return_value=10001):
            with self.assertRaisesRegex(ValueError, 'upstream SAIL_'):
                entrypoint.validate_runtime(['spark-connect'], {'SAIL_MODE': 'kubernetes-cluster'})


class GateTests(unittest.TestCase):
    def test_fixed_and_unfixed(self):
        for severity in ['HIGH', 'CRITICAL']:
            trivy = {'Results': [{'Vulnerabilities': [{'Severity': severity, 'VulnerabilityID': 'CVE-test',
                                                      'PkgName': 'test', 'FixedVersion': '2'}]}]}
            self.assertTrue(any(row[4] for row in gate.findings(trivy, {})))
            trivy['Results'][0]['Vulnerabilities'][0].pop('FixedVersion')
            rows = gate.findings(trivy, {})
            self.assertEqual(len(rows), 1)
            self.assertFalse(any(row[4] for row in rows))
            grype = {'matches': [{'artifact': {'name': 'test'}, 'vulnerability': {'id': 'CVE-test',
                      'severity': severity, 'fix': {'state': 'fixed', 'versions': []}}}]}
            self.assertTrue(any(row[4] for row in gate.findings({}, grype)))
            grype['matches'][0]['vulnerability']['fix']['state'] = 'not-fixed'
            self.assertFalse(any(row[4] for row in gate.findings({}, grype)))


if __name__ == '__main__':
    unittest.main()

class GateExitTests(unittest.TestCase):
    def test_cli_blocks_either_scanner_and_preserves_unfixed(self):
        import subprocess
        import sys
        script = str(Path('scripts/vulnerability-gate.py').resolve())
        for scanner in ['trivy', 'grype']:
            for fixed in [False, True]:
                with self.subTest(scanner=scanner, fixed=fixed), tempfile.TemporaryDirectory() as tmp:
                    trivy = {'Results': []}
                    grype = {'matches': []}
                    if scanner == 'trivy':
                        trivy['Results'] = [{'Vulnerabilities': [{'Severity': 'CRITICAL', 'VulnerabilityID': 'CVE-test',
                                          'PkgName': 'test', 'FixedVersion': '2' if fixed else ''}]}]
                    else:
                        grype['matches'] = [{'artifact': {'name': 'test'}, 'vulnerability': {'id': 'CVE-test',
                                              'severity': 'High', 'fix': {'state': 'fixed' if fixed else 'not-fixed',
                                              'versions': ['2'] if fixed else []}}}]
                    for name, report in [('trivy', trivy), ('grype', grype)]:
                        Path(tmp, name + '.json').write_text(json.dumps(report))
                    result = subprocess.run([sys.executable, script, 'trivy.json', 'grype.json'], cwd=tmp,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, int(fixed), result.stderr)
                    self.assertIn('CVE-test', Path(tmp, 'evidence/vulnerabilities.md').read_text())
