"""Run on Linux with checksum-verified step and step-ca binaries on PATH.

Uses a disposable, loopback-only CA; no AWS account or real device keys.
"""

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "renew-certificate.sh"


class RenewalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.umask(0o077)
        cls.temp = tempfile.TemporaryDirectory(prefix="telemetry-test-ca-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.home = Path(cls.temp.name)
        cls.env = dict(os.environ, STEPPATH=str(cls.home))
        cls.password = cls.home / "password"
        cls.password.write_text("disposable-test-password\n")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.url = f"https://127.0.0.1:{cls.port}"
        cls.run_step("ca", "init", "--deployment-type", "standalone",
                     "--name", "Disposable telemetry test CA", "--dns", "127.0.0.1",
                     "--address", f"127.0.0.1:{cls.port}", "--provisioner", "test",
                     "--password-file", str(cls.password))
        cls.config = cls.home / "config/ca.json"
        config = json.loads(cls.config.read_text())
        config["authority"]["backdate"] = "0s"
        config["authority"]["provisioners"][0]["claims"] = {
            "minTLSCertDuration": "1s", "maxTLSCertDuration": "2160h",
            "defaultTLSCertDuration": "10m", "allowRenewalAfterExpiry": False,
        }
        cls.config.write_text(json.dumps(config))
        cls.log = (cls.home / "ca.log").open("w+")
        cls.addClassCleanup(cls.log.close)
        cls.start_ca()
        cls.addClassCleanup(cls.stop_ca)

    @classmethod
    def run_step(cls, *args):
        return subprocess.run(["step", *args], env=cls.env, check=True,
                              capture_output=True, text=True, timeout=20).stdout

    @classmethod
    def start_ca(cls):
        cls.ca = subprocess.Popen(
            ["step-ca", str(cls.config), "--password-file", str(cls.password)],
            env=cls.env, stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            if cls.ca.poll() is not None:
                raise RuntimeError("test CA exited; inspect test setup")
            result = subprocess.run(
                ["step", "ca", "health", "--ca-url", cls.url,
                 "--root", str(cls.home / "certs/root_ca.crt")],
                env=cls.env, capture_output=True, timeout=3)
            if result.returncode == 0:
                return
            time.sleep(0.1)
        raise RuntimeError("test CA never became healthy")

    @classmethod
    def stop_ca(cls):
        if cls.ca.poll() is None:
            cls.ca.terminate()
            cls.ca.wait(timeout=10)

    def setUp(self):
        self.device = Path(tempfile.mkdtemp(dir=self.home))
        self.cert = self.device / "device.crt"
        self.key = self.device / "device.key"
        self.env = dict(type(self).env, CERTIFICATE=str(self.cert),
                        PRIVATE_KEY=str(self.key), CA_URL=self.url,
                        ROOT_CERTIFICATE=str(self.home / "certs/root_ca.crt"),
                        INTERMEDIATE_CERTIFICATE=str(self.home / "certs/intermediate_ca.crt"),
                        DEVICE_CN="pi-test", RENEW_BEFORE="599s")
        self.enroll()

    def enroll(self, duration="10m", subject="pi-test"):
        self.run_step("ca", "certificate", subject, str(self.cert), str(self.key),
                      "--ca-url", self.url, "--root", self.env["ROOT_CERTIFICATE"],
                      "--provisioner", "test", "--provisioner-password-file",
                      str(self.password), "--not-after", duration, "--force")

    def renew(self, **overrides):
        return subprocess.run(["bash", str(SCRIPT)], env=dict(self.env, **overrides),
                              capture_output=True, text=True, timeout=20)

    def inspect(self):
        return json.loads(self.run_step("certificate", "inspect", str(self.cert),
                                        "--format", "json"))

    def test_renewal_publishes_valid_cert_without_changing_identity_or_key(self):
        before = self.inspect()
        key = self.key.read_bytes()
        time.sleep(1.1)
        result = self.renew()
        self.assertEqual(result.returncode, 0, result.stderr)
        after = self.inspect()
        self.assertNotEqual(before["serial_number"], after["serial_number"])
        self.assertGreater(after["validity"]["end"], before["validity"]["end"])
        self.assertEqual(after["subject"]["common_name"], ["pi-test"])
        self.assertEqual(before["subject_key_info"], after["subject_key_info"])
        self.assertEqual(self.key.read_bytes(), key)
        self.assertEqual(self.cert.stat().st_mode & 0o777, 0o600)

    def test_early_check_keeps_existing_certificate(self):
        before = self.cert.read_bytes()
        result = self.renew(RENEW_BEFORE="1s")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.cert.read_bytes())

    def test_issuer_outage_keeps_certificate_and_next_attempt_recovers(self):
        before = self.cert.read_bytes()
        time.sleep(1.1)
        self.stop_ca()
        try:
            self.assertNotEqual(self.renew().returncode, 0)
            self.assertEqual(before, self.cert.read_bytes())
        finally:
            self.start_ca()
        time.sleep(1.1)
        result = self.renew()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(before, self.cert.read_bytes())

    def test_wrong_device_identity_cannot_replace_certificate(self):
        before = self.cert.read_bytes()
        self.assertNotEqual(self.renew(DEVICE_CN="pi-other").returncode, 0)
        self.assertEqual(before, self.cert.read_bytes())

    def test_expired_certificate_requires_reenrollment(self):
        self.enroll(duration="2s")
        before = self.cert.read_bytes()
        time.sleep(3)
        self.assertNotEqual(self.renew().returncode, 0)
        self.assertEqual(before, self.cert.read_bytes())

    def test_partial_client_output_never_replaces_live_certificate(self):
        # Inject a failed client write, keeping the wrapper/filesystem real.
        shim = self.device / "bin"
        shim.mkdir()
        command = shim / "step"
        command.write_text('''#!/bin/bash
while (($#)); do
  if [[ $1 == --out ]]; then shift; echo partial > "$1"; fi
  shift
done
exit 1
''')
        command.chmod(0o700)
        before = self.cert.read_bytes()
        self.assertNotEqual(self.renew(PATH=f"{shim}:{os.environ['PATH']}").returncode, 0)
        self.assertEqual(before, self.cert.read_bytes())
        self.assertEqual(list(self.device.glob(".renew-*")), [])

    def test_invalid_successful_client_output_is_rejected_before_publication(self):
        shim = self.device / "bin"
        shim.mkdir()
        command = shim / "step"
        command.write_text('''#!/bin/bash
while (($#)); do
  if [[ $1 == --out ]]; then shift; cp "$CANDIDATE" "$1"; fi
  shift
done
''')
        command.chmod(0o700)
        candidate = self.device / "candidate.crt"
        before = self.cert.read_bytes()
        for invalid in ("malformed", "wrong_subject", "wrong_key", "ca_true", "server_only", "no_signing"):
            with self.subTest(invalid=invalid):
                if invalid == "malformed":
                    candidate.write_text("partial certificate\n")
                else:
                    key = self.key
                    if invalid == "wrong_key":
                        key = self.device / "wrong.key"
                        subprocess.run(["openssl", "genpkey", "-algorithm", "EC",
                                        "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(key)],
                                       check=True, capture_output=True)
                    csr = self.device / "request.csr"
                    subject = "pi-other" if invalid == "wrong_subject" else "pi-test"
                    subprocess.run(["openssl", "req", "-new", "-key", str(key),
                                    "-subj", f"/CN={subject}", "-out", str(csr)],
                                   check=True, capture_output=True)
                    extensions = self.device / "extensions"
                    extensions.write_text(
                        "basicConstraints=CA:" + ("TRUE" if invalid == "ca_true" else "FALSE") + "\n"
                        + "keyUsage=" + ("keyEncipherment" if invalid == "no_signing" else "digitalSignature") + "\n"
                        + "extendedKeyUsage=" + ("serverAuth" if invalid == "server_only" else "clientAuth") + "\n")
                    subprocess.run(["openssl", "x509", "-req", "-in", str(csr), "-days", "1",
                                    "-CA", self.env["INTERMEDIATE_CERTIFICATE"],
                                    "-CAkey", str(self.home / "secrets/intermediate_ca_key"),
                                    "-passin", f"file:{self.password}", "-set_serial", "42",
                                    "-extfile", str(extensions), "-out", str(candidate)],
                                   check=True, capture_output=True)
                result = self.renew(PATH=f"{shim}:{os.environ['PATH']}", CANDIDATE=str(candidate))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.cert.read_bytes())

    def test_interrupted_client_retains_live_certificate_and_next_run_recovers(self):
        shim = self.device / "bin"
        shim.mkdir()
        command = shim / "step"
        ready = self.device / "ready"
        command.write_text('''#!/bin/bash
while (($#)); do
  if [[ $1 == --out ]]; then shift; echo partial > "$1"; fi
  shift
done
touch "$READY"
sleep 60
''')
        command.chmod(0o700)
        before = self.cert.read_bytes()
        process = subprocess.Popen(["bash", str(SCRIPT)], start_new_session=True,
                                   env=dict(self.env, PATH=f"{shim}:{os.environ['PATH']}", READY=str(ready)),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(ready.exists(), "client never reached the interrupted write")
            self.assertNotEqual(self.renew().returncode, 0, "concurrent renewal escaped the lock")
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
                raise
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(before, self.cert.read_bytes())
        self.assertEqual(list(self.device.glob(".renew-*")), [])
        time.sleep(1.1)
        result = self.renew()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
