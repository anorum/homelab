#!/usr/bin/env python3
"""Linux acceptance tests for public status output using disposable certificates."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "certificate-status.sh"


class CertificateStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.metrics = self.root / "metrics"
        self.metrics.mkdir()
        self.cert = self.root / "cert.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
                        "ec_paramgen_curve:prime256v1", "-nodes", "-subj", "/CN=test",
                        "-days", "90", "-keyout", str(self.root / "key.pem"),
                        "-out", str(self.cert)], check=True, capture_output=True)
        self.env = dict(os.environ, CERTIFICATE=str(self.cert),
                        ROOT_CERTIFICATE=str(self.cert), INTERMEDIATE_CERTIFICATE=str(self.cert),
                        METRICS_DIRECTORY=str(self.metrics), SERVICE_RESULT="success")
        self.output = self.metrics / "certificate.prom"

    def publish(self, **changes):
        return subprocess.run(["bash", str(SCRIPT)], env=self.env | changes,
                              capture_output=True, text=True)

    def test_success_is_public_and_contains_only_numeric_status(self):
        self.assertEqual(self.publish().returncode, 0)
        content = self.output.read_text()
        self.assertIn("telemetry_certificate_check_success 1\n", content)
        samples = [line for line in content.splitlines() if not line.startswith("#")]
        self.assertEqual(len(samples), 5)
        for sample in samples:
            float(sample.split()[-1])
        self.assertNotIn("test", content)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o644)
        self.assertEqual(list(self.metrics.iterdir()), [self.output])

    def test_failure_timeout_and_unknown_result_are_unsuccessful(self):
        for result in ("exit-code", "timeout", "signal", ""):
            with self.subTest(result=result):
                self.assertEqual(self.publish(SERVICE_RESULT=result).returncode, 0)
                self.assertIn("telemetry_certificate_check_success 0\n", self.output.read_text())
        self.assertEqual(self.publish().returncode, 0)
        self.assertIn("telemetry_certificate_check_success 1\n", self.output.read_text())

    def test_missing_or_invalid_certificate_cannot_leave_healthy_status(self):
        self.assertEqual(self.publish().returncode, 0)
        for path in (self.root / "missing", self.root / "key.pem"):
            self.assertEqual(self.publish(CERTIFICATE=str(path)).returncode, 0)
            content = self.output.read_text()
            self.assertIn('telemetry_certificate_expires_at_seconds{certificate="device"} 0\n', content)
            self.assertIn("telemetry_certificate_check_success 0\n", content)

    def test_failed_publication_preserves_previous_file(self):
        self.assertEqual(self.publish().returncode, 0)
        previous = self.output.read_bytes()
        self.metrics.chmod(0o555)
        self.addCleanup(self.metrics.chmod, 0o755)
        self.assertNotEqual(self.publish(SERVICE_RESULT="timeout").returncode, 0)
        self.assertEqual(self.output.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main(verbosity=2)
