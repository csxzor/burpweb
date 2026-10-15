import io
import shutil
import stat
import subprocess

import pytest
from mitmproxy.certs import CertStore

from burpweb import browser
from burpweb.browser import CERT_NICKNAME, FirefoxLauncher, prepare_profile, user_js

CERTUTIL = shutil.which("certutil")
needs_certutil = pytest.mark.skipif(CERTUTIL is None, reason="NSS certutil not installed")


@pytest.fixture
def confdir(tmp_path):
    d = tmp_path / "conf"
    CertStore.from_store(d, "mitmproxy", 2048)
    return d


def test_user_js_sets_proxy_and_quiets_firefox():
    js = user_js(9123)
    for line in [
        'user_pref("network.proxy.type", 1);',
        'user_pref("network.proxy.http", "127.0.0.1");',
        'user_pref("network.proxy.http_port", 9123);',
        'user_pref("network.proxy.ssl_port", 9123);',
        'user_pref("network.proxy.no_proxies_on", "");',
        'user_pref("network.proxy.allow_hijacking_localhost", true);',
        'user_pref("network.http.http3.enable", false);',
        'user_pref("browser.safebrowsing.malware.enabled", false);',
        'user_pref("network.captive-portal-service.enabled", false);',
    ]:
        assert line in js


@needs_certutil
def test_prepare_profile_imports_ca_idempotently(tmp_path, confdir):
    profile = tmp_path / "profile"
    ca = confdir / "mitmproxy-ca-cert.pem"
    prepare_profile(profile, 8081, ca, CERTUTIL)
    prepare_profile(profile, 8082, ca, CERTUTIL)  # second run must not fail
    assert 'user_pref("network.proxy.http_port", 8082);' in (profile / "user.js").read_text()
    listing = subprocess.run([CERTUTIL, "-L", "-d", f"sql:{profile}"], capture_output=True, text=True, check=True).stdout
    assert listing.count(CERT_NICKNAME) == 1


@needs_certutil
def test_launcher_starts_firefox_with_profile(tmp_path, confdir, monkeypatch):
    args_file = tmp_path / "args.txt"
    fake = tmp_path / "firefox"
    fake.write_text(f'#!/bin/sh\necho "$@" > "{args_file}"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(browser.shutil, "which", lambda name: {"firefox": str(fake), "certutil": CERTUTIL}.get(name))
    out = io.StringIO()
    profile = tmp_path / "profile"
    launcher = FirefoxLauncher(port=8081, confdir=confdir, start_url="https://shop.invalid/", profile=profile, out=out)
    launcher.running()
    launcher.process.wait(timeout=10)
    assert args_file.read_text().split() == ["-profile", str(profile), "-no-remote", "-new-instance", "https://shop.invalid/"]
    assert "Opened Firefox" in out.getvalue()


def test_launcher_prints_manual_steps_when_firefox_missing(tmp_path, confdir, monkeypatch):
    monkeypatch.setattr(browser.shutil, "which", lambda name: None)
    out = io.StringIO()
    launcher = FirefoxLauncher(port=8081, confdir=confdir, start_url="https://x.invalid/", profile=tmp_path / "p", out=out)
    launcher.running()
    assert launcher.process is None
    text = out.getvalue()
    assert "firefox, certutil not found" in text
    assert "127.0.0.1:8081" in text
    assert str(confdir / "mitmproxy-ca-cert.pem") in text
