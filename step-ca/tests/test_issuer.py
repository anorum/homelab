"""Verify the deployed CA policy with a disposable issuer and loopback HTTPS.

Requires step 0.30.6 and step-ca 0.30.2 on PATH. Uses no real CA secrets.
"""

import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request


CONFIG = Path(__file__).resolve().parents[1] / "config/ca.json"


class IssuerPolicyTest(unittest.TestCase):
    def test_identity_lifetime_trust_and_replay_survive_database_restore(self):
        os.umask(0o077)
        with tempfile.TemporaryDirectory(prefix="issuer-policy-") as directory:
            home = Path(directory)
            env = dict(os.environ, STEPPATH=str(home))
            password = home / "password"
            password.write_text("disposable-issuer-password\n")
            enrollment_password = home / "enrollment-password"
            enrollment_password.write_text("disposable-enrollment-password\n")

            def step(*args, step_path=home):
                result = subprocess.run(["step", *map(str, args)], env=dict(env, STEPPATH=str(step_path)),
                                        capture_output=True, text=True, timeout=20)
                if result.returncode:
                    raise RuntimeError(result.stderr)
                return result.stdout

            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            url = f"https://127.0.0.1:{port}"
            step("ca", "init", "--deployment-type", "standalone", "--name", "Disposable issuer",
                 "--dns", "127.0.0.1", "--address", f"127.0.0.1:{port}",
                 "--provisioner", "telemetry-enrollment", "--password-file", password,
                 "--provisioner-password-file", enrollment_password)
            generated = json.loads((home / "config/ca.json").read_text())
            provisioner = generated["authority"]["provisioners"][0]
            enrollment_key = home / "enrollment.jwe"
            enrollment_key.write_text(provisioner["encryptedKey"])
            config = json.loads(CONFIG.read_text())
            self.assertNotIn("encryptedKey", config["authority"]["provisioners"][0])
            # Substitute test identity/paths; retain the repository's actual policy.
            for field in ("root", "crt", "key", "db", "address", "dnsNames"):
                config[field] = generated[field]
            config["authority"]["provisioners"][0]["key"] = provisioner["key"]
            runtime = home / "runtime.json"
            runtime.write_text(json.dumps(config))
            trust = ssl.create_default_context(cafile=str(home / "certs/root_ca.crt"))
            log = (home / "server.log").open("w+")
            server = None

            def stop():
                if server is not None and server.poll() is None:
                    server.terminate()
                    server.wait(timeout=10)

            def start():
                nonlocal server
                server = subprocess.Popen(["step-ca", str(runtime), "--password-file", str(password)],
                                          env=env, stdout=log, stderr=log)
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("Disposable issuer exited before becoming healthy")
                    try:
                        with urllib.request.urlopen(url + "/health", context=trust, timeout=1) as response:
                            if response.status == 200:
                                return
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.1)
                raise RuntimeError("Disposable issuer did not become healthy")

            def sign(csr, token, **extra):
                request = urllib.request.Request(url + "/1.0/sign", method="POST",
                    data=json.dumps({"csr": csr.read_text(), "ott": token, **extra}).encode(),
                    headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(request, context=trust, timeout=5) as response:
                        return response.status, json.load(response)
                except urllib.error.HTTPError as error:
                    return error.code, None

            try:
                start()
                with self.assertRaises(urllib.error.URLError):
                    urllib.request.urlopen(url + "/health", context=ssl.create_default_context(), timeout=5)
                for subject in ("pi-test", "pi-other"):
                    step("certificate", "create", subject, home / (subject + ".csr"),
                         home / (subject + ".key"), "--csr", "--no-password", "--insecure")

                def token():
                    # Explicit operator key avoids opening the issuer DB or key.
                    return step("ca", "token", "pi-test", "--offline", "--key", enrollment_key,
                                "--kid", provisioner["key"]["kid"], "--issuer", "telemetry-enrollment",
                                "--ca-url", url, "--root", home / "certs/root_ca.crt",
                                "--password-file", enrollment_password, "--not-after", "5m",
                                step_path=home / "operator").strip()

                status, _ = sign(home / "pi-other.csr", token())
                self.assertEqual(status, 403, "CA accepted a CSR for the wrong device")
                status, _ = sign(home / "pi-test.csr", "invalid-token")
                self.assertIn(status, (400, 401, 403))
                status, _ = sign(home / "pi-test.csr", token(), notAfter="2161h")
                self.assertIn(status, (400, 403), "CA accepted a certificate longer than 90 days")
                used_token = token()
                status, issued = sign(home / "pi-test.csr", used_token)
                self.assertEqual(status, 201)
                leaf = home / "issued.crt"
                leaf.write_text(issued["crt"])
                details = json.loads(step("certificate", "inspect", leaf, "--format", "json"))
                self.assertEqual(details["subject"]["common_name"], ["pi-test"])
                # Ninety days plus the default one-minute backdate.
                self.assertGreaterEqual(details["validity"]["length"], 7_776_000)
                self.assertLessEqual(details["validity"]["length"], 7_776_060)
                self.assertEqual(sign(home / "pi-test.csr", used_token)[0], 401)

                stop()
                restored = home / "restored-db"
                shutil.copytree(config["db"]["dataSource"], restored)
                config["db"]["dataSource"] = str(restored)
                runtime.write_text(json.dumps(config))
                start()
                self.assertEqual(sign(home / "pi-test.csr", used_token)[0], 401,
                                 "Restored database lost enrollment-token replay protection")
                self.assertEqual(sign(home / "pi-test.csr", token())[0], 201)
            finally:
                stop()
                log.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
