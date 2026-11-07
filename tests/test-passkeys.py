#!/usr/bin/env python3
"""Checks Floe Passkeys with an independent FIDO2 client (python-fido2): saving a
passkey, signing in, wrong PIN, other sites, PIN change, and long messages."""
import hashlib, os, struct, sys, tempfile, queue
home = tempfile.mkdtemp()
os.environ["HOME"] = home
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rootfs", "usr", "lib", "wren"))
import passkeys as pk
from fido2.ctap2 import Ctap2
from fido2.ctap import CtapDevice, CtapError

answers = queue.Queue()
asked = []
def ask(req):
    asked.append(req)
    return answers.get()

# real HID framing in between, packets round-trip through CtapHid
class Dev(CtapDevice):
    def __init__(self):
        self.out = queue.Queue()
        self.hid = pk.CtapHid(pk.Authenticator(ask), self.out.put)
        # INIT handshake
        self.hid.packet(struct.pack(">IBH", 0xFFFFFFFF, 0x86, 8) + b"12345678".ljust(57, b"\0"))
        r = self.out.get(timeout=2)
        assert r[7:15] == b"12345678"
        self.cid = struct.unpack(">I", r[15:19])[0]
    @property
    def capabilities(self): return 0x04 | 0x08
    def close(self): pass
    @classmethod
    def list_devices(cls): return []
    def call(self, cmd, data=b"", event=None, on_keepalive=None):
        data = bytes(data)
        pkts = [struct.pack(">IBH", self.cid, 0x80 | cmd, len(data)) + data[:57]]
        rest, seq = data[57:], 0
        while rest:
            pkts.append(struct.pack(">IB", self.cid, seq) + rest[:59]); rest = rest[59:]; seq += 1
        for p in pkts: self.hid.packet(p.ljust(64, b"\0"))
        while True:
            r = self.out.get(timeout=30)
            c, rc = struct.unpack(">IB", r[:5])
            if rc == 0xBB:
                continue
            n = struct.unpack(">H", r[5:7])[0]
            buf = bytearray(r[7:7+n]); seq = 0
            while len(buf) < n:
                r = self.out.get(timeout=5); buf += r[5:5+n-len(buf)]
            assert rc == 0x80 | cmd, hex(rc)
            return bytes(buf)

assert pk.set_pin("4821")
dev = Dev()
ctap = Ctap2(dev)
print("info versions:", ctap.info.versions, "options:", ctap.info.options)

cdh = hashlib.sha256(b"clientdata").digest()
answers.put({"pin": "4821"})
att = ctap.make_credential(cdh, {"id": "google.com", "name": "Google"},
                           {"id": b"user-123", "name": "gavin@gmail.com", "displayName": "Gavin"},
                           [{"type": "public-key", "alg": -7}], options={"rk": True, "uv": True})
ad = att.auth_data
print("make_credential fmt:", att.fmt, "flags:", hex(ad.flags), "rpIdHash ok:", ad.rp_id_hash == hashlib.sha256(b"google.com").digest())
cred = ad.credential_data
pub = cred.public_key

# discoverable sign-in (no allow list)
cdh2 = hashlib.sha256(b"clientdata2").digest()
answers.put({"pin": "4821", "choice": 0})
assertion = ctap.get_assertion("google.com", cdh2, options={"uv": True})
pub.verify(bytes(assertion.auth_data) + cdh2, assertion.signature)
print("assertion verified; user:", assertion.user, "count:", assertion.auth_data.counter)

# wrong PIN is refused
answers.put({"pin": "0000"})
try:
    ctap.get_assertion("google.com", cdh2); sys.exit("wrong PIN was accepted")
except CtapError as e:
    print("wrong PIN refused:", e.code)

# other site has no passkeys
try:
    ctap.get_assertion("example.com", cdh2); sys.exit("another site got a passkey")
except CtapError as e:
    print("no passkeys for other site:", e.code)

# allow list + PIN change keeps keys usable
assert pk.set_pin("998877", "4821")
answers.put({"pin": "998877"})
a2 = ctap.get_assertion("google.com", cdh2, allow_list=[{"type": "public-key", "id": cred.credential_id}])
pub.verify(bytes(a2.auth_data) + cdh2, a2.signature)
print("after PIN change: verified, count", a2.auth_data.counter)
print("list:", [(x["site"], x["user"]) for x in pk.list_passkeys()])
# a long credential payload (multi-packet) round trip
assert dev.call(0x01, b"x" * 300) == b"x" * 300
print("Floe Passkeys: all checks passed")

# The way the system service answers: one request per helper run, as the person
import subprocess
lib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rootfs", "usr", "lib", "wren")
env = dict(os.environ, PYTHONPATH=lib, FLOE_PASSKEY_TEST_PIN="998877")
def helper(req):
    return subprocess.run([sys.executable, "-m", "passkeys", "--handle"], input=req, capture_output=True, env=env,
                          timeout=60).stdout
info = helper(b"\x04")
assert info[0] == 0 and pk.loads(info[1:])[1] == ["FIDO_2_0"], info
mc = pk.cbor_enc({1: hashlib.sha256(b"x").digest(), 2: {"id": "github.com", "name": "GitHub"},
                  3: {"id": b"u1", "name": "gavin", "displayName": "Gavin"}, 4: [{"type": "public-key", "alg": -7}],
                  7: {"rk": True}})
r = helper(b"\x01" + mc)
assert r[0] == 0, r[:1]
ga = helper(b"\x02" + pk.cbor_enc({1: "github.com", 2: hashlib.sha256(b"y").digest()}))
assert ga[0] == 0, ga[:1]
assert pk.answer_as_user(b"\x04")[0] == 0
print("Floe Passkeys: service helper path works")
