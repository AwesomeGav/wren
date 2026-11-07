#!/usr/bin/env python3
"""Runs Floe Passkeys the way a Floe computer does (root service, real /dev/uhid)
and talks to it like a browser: through /dev/hidraw, as an ordinary user.
Needs root and the uhid kernel module (run on the CI host, not in a container)."""
import glob, hashlib, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "rootfs", "usr", "lib", "wren")
home = tempfile.mkdtemp()
os.chmod(home, 0o755)
subprocess.run(["modprobe", "uhid"], check=False)
env = dict(os.environ, PYTHONPATH=LIB, PYTHONUNBUFFERED="1", HOME=home,
           FLOE_PASSKEY_DIRECT="1", FLOE_PASSKEY_TEST_PIN="2468")
log = open(os.path.join(home, "service.log"), "w")
svc = subprocess.Popen([sys.executable, "-m", "passkeys", "--system"], env=env, stdout=log, stderr=log)

def node():
    for d in glob.glob("/sys/class/hidraw/hidraw*"):
        if "0000F10E" in open(d + "/device/uevent").read():
            return "/dev/" + os.path.basename(d)

try:
    for _ in range(60):
        n = node()
        if n and os.stat(n).st_mode & 0o006 == 0o006:
            break
        time.sleep(0.2)
    print("device:", n, oct(os.stat(n).st_mode & 0o777) if n else "")
    assert n and os.stat(n).st_mode & 0o006 == 0o006, "security key missing or not usable by browsers"

    # the "browser": an ordinary user (nobody), finding the key by its FIDO usage page
    client = r'''
import hashlib, json, sys
from fido2.hid import CtapHidDevice
from fido2.ctap2 import Ctap2
from fido2.ctap import CtapError
devs = [d for d in CtapHidDevice.list_devices() if d.descriptor.vid == 0x1209 and d.descriptor.pid == 0xF10E]
assert devs, "browser can't see Floe Passkeys"
ctap = Ctap2(devs[0])
print("getInfo:", ctap.info.versions, dict(ctap.info.options))
cdh = hashlib.sha256(b"c").digest()
# Firefox's device-selection check answers at once
ctap.make_credential(cdh, {"id": "make.me.blink"}, {"id": b"\x01", "name": "make.me.blink"},
                     [{"type": "public-key", "alg": -7}])
att = ctap.make_credential(cdh, {"id": "google.com", "name": "Google"},
                           {"id": b"user-1", "name": "gavin@gmail.com", "displayName": "Gavin"},
                           [{"type": "public-key", "alg": -7}], options={"rk": True, "uv": True})
cred = att.auth_data.credential_data
# silent check before sign-in: answered without asking
pre = ctap.get_assertion("google.com", cdh, allow_list=[{"type": "public-key", "id": cred.credential_id}],
                         options={"up": False})
assert pre.credential["id"] == cred.credential_id
a = ctap.get_assertion("google.com", cdh, options={"uv": True})
cred.public_key.verify(bytes(a.auth_data) + cdh, a.signature)
print("saved and signed in through the kernel device; user:", a.user)
'''
    r = subprocess.run(["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", sys.executable, "-c", client],
                       capture_output=True, text=True, timeout=120, env={"PATH": os.environ["PATH"], "HOME": "/tmp"})
    print(r.stdout, r.stderr)
    assert r.returncode == 0, "browser-side checks failed"
    print("Floe Passkeys: kernel device checks passed")
finally:
    svc.terminate()
    log.close()
    print("--- service log ---")
    print(open(os.path.join(home, "service.log")).read())
