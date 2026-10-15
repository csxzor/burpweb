"""Launch Firefox in a dedicated profile that uses the replay proxy and trusts its CA."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TextIO

DEFAULT_PROFILE = Path.home() / ".local" / "share" / "burpweb" / "firefox-profile"
CERT_NICKNAME = "burpweb-mitmproxy"


def user_js(port: int) -> str:
    prefs = {
        # Route everything, including localhost, through the replay proxy.
        "network.proxy.type": 1,
        "network.proxy.http": "127.0.0.1",
        "network.proxy.http_port": port,
        "network.proxy.ssl": "127.0.0.1",
        "network.proxy.ssl_port": port,
        "network.proxy.share_proxy_settings": True,
        "network.proxy.no_proxies_on": "",
        "network.proxy.allow_hijacking_localhost": True,
        "network.trr.mode": 5,
        "network.http.http3.enable": False,
        # Silence Firefox's own background traffic.
        "app.update.auto": False,
        "extensions.update.enabled": False,
        "toolkit.telemetry.enabled": False,
        "datareporting.healthreport.uploadEnabled": False,
        "datareporting.policy.dataSubmissionEnabled": False,
        "browser.safebrowsing.malware.enabled": False,
        "browser.safebrowsing.phishing.enabled": False,
        "browser.safebrowsing.downloads.enabled": False,
        "network.captive-portal-service.enabled": False,
        "network.connectivity-service.enabled": False,
        "network.dns.disablePrefetch": True,
        "network.prefetch-next": False,
        "network.http.speculative-parallel-limit": 0,
        "security.OCSP.enabled": 0,
        "browser.shell.checkDefaultBrowser": False,
        "browser.startup.homepage_override.mstone": "ignore",
        # Always show the snapshot as served, never a stale local copy.
        "browser.cache.disk.enable": False,
    }
    return "".join(f'user_pref("{name}", {json.dumps(value)});\n' for name, value in prefs.items())


def prepare_profile(profile: Path, port: int, ca_pem: Path, certutil: str) -> None:
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "user.js").write_text(user_js(port))
    db = f"sql:{profile}"
    if not (profile / "cert9.db").exists():
        subprocess.run([certutil, "-N", "-d", db, "--empty-password"], check=True, capture_output=True)
    # Re-add every time so a regenerated CA (or another --confdir) replaces the old one.
    subprocess.run([certutil, "-D", "-d", db, "-n", CERT_NICKNAME], capture_output=True)
    subprocess.run(
        [certutil, "-A", "-d", db, "-n", CERT_NICKNAME, "-t", "C,,", "-i", str(ca_pem)],
        check=True,
        capture_output=True,
    )


def manual_instructions(port: int, ca_pem: Path) -> str:
    return (
        "Set up a browser by hand:\n"
        f"  1. Set its HTTP and HTTPS proxy to 127.0.0.1:{port}\n"
        f"  2. Import {ca_pem} as a trusted certificate authority (for websites)"
    )


class FirefoxLauncher:
    """mitmproxy addon: once the proxy is running (so its CA exists), open Firefox."""

    def __init__(self, *, port: int, confdir: Path, start_url: str, profile: Path = DEFAULT_PROFILE, out: TextIO | None = None):
        self.port = port
        self.ca_pem = Path(confdir) / "mitmproxy-ca-cert.pem"
        self.start_url = start_url
        self.profile = profile
        self.out = out or sys.stdout
        self.process: subprocess.Popen | None = None

    def running(self) -> None:
        firefox = shutil.which("firefox")
        certutil = shutil.which("certutil")
        missing = [name for name, found in (("firefox", firefox), ("certutil", certutil)) if not found]
        if missing:
            self._say(f"--browser: {', '.join(missing)} not found on PATH.\n" + manual_instructions(self.port, self.ca_pem))
            return
        try:
            prepare_profile(self.profile, self.port, self.ca_pem, certutil)
        except (OSError, subprocess.CalledProcessError) as e:
            self._say(f"--browser: could not set up the Firefox profile ({e}).\n" + manual_instructions(self.port, self.ca_pem))
            return
        self.process = subprocess.Popen(
            [firefox, "-profile", str(self.profile), "-no-remote", "-new-instance", self.start_url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._say(f"Opened Firefox (profile {self.profile}) at {self.start_url}")

    def _say(self, text: str) -> None:
        print(text, file=self.out, flush=True)
