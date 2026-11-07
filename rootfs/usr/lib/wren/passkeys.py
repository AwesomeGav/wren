#!/usr/bin/env python3
"""Floe Passkeys: a passkey authenticator built into Floe.

It shows up to the computer as a USB security key (through the kernel's
/dev/uhid, from a small system service), so Firefox, Chrome and other apps can
use it without add-ons. Each request is answered as the person at the screen.
Passkeys are kept in ~/.local/share/floe/passkeys, each private key encrypted
with a key made from your passkey PIN; every sign-in asks for that PIN.

  python3 -m passkeys --system    run the security key (system service, as root)
  python3 -m passkeys --handle    answer one request read from stdin (as the person)
  python3 -m passkeys status      check that browsers can reach it
  python3 -m passkeys list        print saved passkeys as JSON
  python3 -m passkeys delete ID   remove one
"""
import base64
import hashlib
import json
import os
import secrets
import struct
import subprocess
import sys
import threading
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

STORE = os.path.join(os.path.expanduser("~"), ".local", "share", "floe", "passkeys")
CREDS = os.path.join(STORE, "passkeys.json")
LOCK = os.path.join(STORE, "pin.json")
AAGUID = bytes.fromhex("f10e0000a5c04f1e9c0d1f10e0000001")  # identifies "Floe Passkeys"
PROMPT = [sys.executable, "-m", "passkey_prompt"]
COMMANDS = {0x01: "save a passkey", 0x02: "sign in", 0x04: "getInfo", 0x06: "clientPIN", 0x08: "next sign-in",
            0x0B: "selection"}


def log(*parts):
    """Goes to the system journal: journalctl -u floe-passkeys"""
    print("floe-passkeys:", *parts, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- tiny CBOR
def cbor_enc(v):
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for size, code in ((1, 24), (2, 25), (4, 26), (8, 27)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | code]) + n.to_bytes(size, "big")
        raise ValueError("too big")
    if isinstance(v, bool):
        return b"\xf5" if v else b"\xf4"
    if v is None:
        return b"\xf6"
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, (bytes, bytearray)):
        return head(2, len(v)) + bytes(v)
    if isinstance(v, str):
        b = v.encode()
        return head(3, len(b)) + b
    if isinstance(v, (list, tuple)):
        return head(4, len(v)) + b"".join(cbor_enc(x) for x in v)
    if isinstance(v, dict):
        # canonical order: shorter encodings first, then bytewise
        items = sorted(((cbor_enc(k), cbor_enc(x)) for k, x in v.items()), key=lambda kv: (len(kv[0]), kv[0]))
        return head(5, len(v)) + b"".join(k + x for k, x in items)
    raise TypeError(type(v))


def cbor_dec(data, i=0):
    ib = data[i]
    major, info = ib >> 5, ib & 31
    i += 1
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        n = int.from_bytes(data[i:i + size], "big")
        i += size
    else:
        raise ValueError("unsupported CBOR")
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major == 2:
        return bytes(data[i:i + n]), i + n
    if major == 3:
        return data[i:i + n].decode(), i + n
    if major == 4:
        out = []
        for _ in range(n):
            x, i = cbor_dec(data, i)
            out.append(x)
        return out, i
    if major == 5:
        out = {}
        for _ in range(n):
            k, i = cbor_dec(data, i)
            x, i = cbor_dec(data, i)
            out[k] = x
        return out, i
    if major == 7:
        return {20: False, 21: True, 22: None}.get(info), i
    raise ValueError("unsupported CBOR")


def loads(b):
    return cbor_dec(b, 0)[0]


# ---------------------------------------------------------------- the store
def b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _read(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def has_pin():
    return "salt" in _read(LOCK, {})


def _key_from_pin(pin, salt):
    return hashlib.scrypt(pin.encode(), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)


def unlock(pin):
    """The encryption key for this PIN, or None if the PIN is wrong."""
    lock = _read(LOCK, {})
    if "salt" not in lock:
        return None
    key = _key_from_pin(pin, unb64(lock["salt"]))
    try:
        AESGCM(key).decrypt(unb64(lock["nonce"]), unb64(lock["check"]), b"floe-pin")
        return key
    except Exception:
        return None


def set_pin(new_pin, old_pin=None):
    """Set the PIN (first time), or change it and re-lock every passkey."""
    salt = secrets.token_bytes(16)
    new_key = _key_from_pin(new_pin, salt)
    creds = _read(CREDS, {})
    if has_pin():
        old_key = unlock(old_pin or "")
        if old_key is None:
            return False
        for c in creds.values():
            priv = AESGCM(old_key).decrypt(unb64(c["nonce"]), unb64(c["key"]), c["rp"].encode())
            nonce = secrets.token_bytes(12)
            c["nonce"], c["key"] = b64(nonce), b64(AESGCM(new_key).encrypt(nonce, priv, c["rp"].encode()))
    nonce = secrets.token_bytes(12)
    _write(CREDS, creds)
    _write(LOCK, {"salt": b64(salt), "nonce": b64(nonce),
                  "check": b64(AESGCM(new_key).encrypt(nonce, b"floe", b"floe-pin"))})
    return True


def list_passkeys():
    creds = _read(CREDS, {})
    out = [{"id": cid, "site": c.get("rp_name") or c["rp"], "rp": c["rp"], "user": c.get("user_name", ""),
            "display": c.get("display", ""), "created": c.get("created", 0), "used": c.get("used", 0)}
           for cid, c in creds.items()]
    return sorted(out, key=lambda x: (x["rp"], x["user"]))


def delete_passkey(cid):
    creds = _read(CREDS, {})
    if creds.pop(cid, None) is None:
        return False
    _write(CREDS, creds)
    return True


# ---------------------------------------------------------------- CTAP2 authenticator
OK, ERR_INVALID_CBOR, ERR_MISSING_PARAMETER = 0x00, 0x12, 0x14
ERR_UNSUPPORTED_ALGORITHM, ERR_OPERATION_DENIED, ERR_CREDENTIAL_EXCLUDED = 0x26, 0x27, 0x19
ERR_NO_CREDENTIALS, ERR_PIN_NOT_SET, ERR_INVALID_COMMAND, ERR_KEEPALIVE_CANCEL = 0x2E, 0x35, 0x01, 0x2D


def cose_key(pub):
    nums = pub.public_numbers()
    return {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}


class Authenticator:
    """CTAP 2.0 commands. `ask(request)` shows Floe's prompt and returns
    {"pin": ..., "choice": index} or None if the person said no."""

    def __init__(self, ask):
        self.ask = ask

    def handle(self, data):
        if not data:
            return bytes([ERR_INVALID_COMMAND])
        cmd, body = data[0], data[1:]
        try:
            params = loads(body) if body else {}
        except Exception:
            return bytes([ERR_INVALID_CBOR])
        if cmd == 0x04:
            return bytes([OK]) + cbor_enc(self.get_info())
        if cmd == 0x01:
            return self.make_credential(params)
        if cmd == 0x02:
            return self.get_assertion(params)
        if cmd == 0x0B:  # authenticatorSelection: "is this the key you want?"
            return bytes([OK])
        if cmd == 0x07:  # reset: never from a web page
            return bytes([ERR_OPERATION_DENIED])
        return bytes([ERR_INVALID_COMMAND])

    @staticmethod
    def get_info():
        return {1: ["FIDO_2_0"], 3: AAGUID, 4: {"rk": True, "up": True, "uv": True, "plat": False},
                5: 1200, 9: ["usb"], 10: [{"alg": -7, "type": "public-key"}]}

    def make_credential(self, p):
        if not all(k in p for k in (1, 2, 3, 4)):
            return bytes([ERR_MISSING_PARAMETER])
        if 8 in p and len(p[8]) == 0:  # a browser checking whether a PIN is set
            return bytes([ERR_PIN_NOT_SET])
        if not any(a.get("alg") == -7 for a in p[4]):
            return bytes([ERR_UNSUPPORTED_ALGORITHM])
        rp, user = p[2], p[3]
        rp_id = rp["id"]
        if rp_id == "make.me.blink":
            # Firefox's "which security key do you want to use?" check: a throwaway answer
            # (nothing saved, no prompt) so Floe Passkeys counts as chosen straight away.
            priv = ec.generate_private_key(ec.SECP256R1())
            cred_id = secrets.token_bytes(32)
            auth_data = (hashlib.sha256(rp_id.encode()).digest() + bytes([0x01 | 0x40]) + struct.pack(">I", 0)
                         + AAGUID + struct.pack(">H", len(cred_id)) + cred_id + cbor_enc(cose_key(priv.public_key())))
            return bytes([OK]) + cbor_enc({1: "none", 2: auth_data, 3: {}})
        creds = _read(CREDS, {})
        for ex in p.get(5) or []:
            if b64(ex.get("id", b"")) in creds and creds[b64(ex["id"])]["rp"] == rp_id:
                self.ask({"kind": "exists", "rp": rp_id})
                return bytes([ERR_CREDENTIAL_EXCLUDED])
        answer = self.ask({"kind": "create", "rp": rp_id, "rp_name": rp.get("name") or rp_id,
                           "user": user.get("name", ""), "display": user.get("displayName", ""),
                           "has_pin": has_pin()})
        if not answer:
            return bytes([ERR_OPERATION_DENIED])
        key = unlock(answer["pin"])
        if key is None:
            return bytes([ERR_OPERATION_DENIED])

        priv = ec.generate_private_key(ec.SECP256R1())
        cred_id = secrets.token_bytes(32)
        der = priv.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption())
        nonce = secrets.token_bytes(12)
        creds = _read(CREDS, {})
        creds[b64(cred_id)] = {
            "rp": rp_id, "rp_name": rp.get("name") or rp_id, "user_id": b64(user["id"]),
            "user_name": user.get("name", ""), "display": user.get("displayName", ""),
            "nonce": b64(nonce), "key": b64(AESGCM(key).encrypt(nonce, der, rp_id.encode())),
            "created": int(time.time()), "used": 0, "count": 0,
        }
        _write(CREDS, creds)
        auth_data = (hashlib.sha256(rp_id.encode()).digest() + bytes([0x01 | 0x04 | 0x40]) + struct.pack(">I", 0)
                     + AAGUID + struct.pack(">H", len(cred_id)) + cred_id + cbor_enc(cose_key(priv.public_key())))
        return bytes([OK]) + cbor_enc({1: "none", 2: auth_data, 3: {}})

    def get_assertion(self, p):
        if 1 not in p or 2 not in p:
            return bytes([ERR_MISSING_PARAMETER])
        if 6 in p and len(p[6]) == 0:
            return bytes([ERR_PIN_NOT_SET])
        rp_id, cdh = p[1], p[2]
        creds = _read(CREDS, {})
        allow = [b64(c["id"]) for c in (p.get(3) or []) if "id" in c]
        if allow:
            found = [cid for cid in allow if cid in creds and creds[cid]["rp"] == rp_id]
        else:
            found = [cid for cid, c in creds.items() if c["rp"] == rp_id]
        if not found:
            return bytes([ERR_NO_CREDENTIALS])
        if (p.get(5) or {}).get("up") is False:
            # A browser's silent check ("does this key have one of these?"), done before asking
            # the person. Answer without a prompt; nothing here can be used to sign in.
            auth_data = hashlib.sha256(rp_id.encode()).digest() + bytes([0x00]) + struct.pack(">I", 0)
            return bytes([OK]) + cbor_enc({1: {"id": unb64(found[0]), "type": "public-key"}, 2: auth_data,
                                           3: bytes.fromhex("3006020101020101")})
        answer = self.ask({"kind": "signin", "rp": rp_id,
                           "accounts": [{"user": creds[c].get("user_name", ""),
                                         "display": creds[c].get("display", "")} for c in found]})
        if not answer:
            return bytes([ERR_OPERATION_DENIED])
        key = unlock(answer["pin"])
        if key is None:
            return bytes([ERR_OPERATION_DENIED])
        cid = found[min(max(int(answer.get("choice", 0)), 0), len(found) - 1)]
        c = creds[cid]
        der = AESGCM(key).decrypt(unb64(c["nonce"]), unb64(c["key"]), rp_id.encode())
        priv = serialization.load_der_private_key(der, None)
        c["count"] = int(c.get("count", 0)) + 1
        c["used"] = int(time.time())
        _write(CREDS, creds)
        auth_data = hashlib.sha256(rp_id.encode()).digest() + bytes([0x01 | 0x04]) + struct.pack(">I", c["count"])
        sig = priv.sign(auth_data + cdh, ec.ECDSA(hashes.SHA256()))
        resp = {1: {"id": unb64(cid), "type": "public-key"}, 2: auth_data, 3: sig}
        user = {"id": unb64(c["user_id"])}
        if c.get("user_name"):
            user["name"] = c["user_name"]
        if c.get("display"):
            user["displayName"] = c["display"]
        resp[4] = user
        return bytes([OK]) + cbor_enc(resp)


# ---------------------------------------------------------------- CTAPHID over a virtual USB device
CTAPHID_PING, CTAPHID_MSG, CTAPHID_INIT, CTAPHID_WINK = 0x81, 0x83, 0x86, 0x88
CTAPHID_CBOR, CTAPHID_CANCEL, CTAPHID_KEEPALIVE, CTAPHID_ERROR = 0x90, 0x91, 0xBB, 0xBF
BROADCAST = 0xFFFFFFFF
REPORT = bytes.fromhex("06d0f10901a1010920150026ff007508954081020921150026ff00750895409102c0")


class CtapHid:
    """Splits and joins 64-byte HID packets, and runs one request at a time."""

    def __init__(self, auth, send):
        self.auth, self.send = auth, send
        self.next_cid = 1
        self.partial = {}
        self.busy = None

    def _reply(self, cid, cmd, payload):
        first = struct.pack(">IBH", cid, cmd, len(payload)) + payload[:57]
        self.send(first.ljust(64, b"\0"))
        rest, seq = payload[57:], 0
        while rest:
            self.send((struct.pack(">IB", cid, seq) + rest[:59]).ljust(64, b"\0"))
            rest, seq = rest[59:], seq + 1

    def packet(self, pkt):
        cid = struct.unpack(">I", pkt[:4])[0]
        if pkt[4] & 0x80:
            cmd, n = pkt[4], struct.unpack(">H", pkt[5:7])[0]
            if cmd == CTAPHID_CANCEL:  # the site gave up: close Floe's prompt
                if self.busy == cid and hasattr(self.auth, "cancel"):
                    self.auth.cancel()
                return
            self.partial[cid] = [cmd, n, bytearray(pkt[7:7 + n]), 0]
        else:
            st = self.partial.get(cid)
            if st is None or pkt[4] != st[3]:
                return self._reply(cid, CTAPHID_ERROR, b"\x04")  # invalid sequence
            st[2] += pkt[5:5 + st[1] - len(st[2])]
            st[3] += 1
        cmd, n, data, _ = self.partial[cid]
        if len(data) < n:
            return
        del self.partial[cid]
        self.request(cid, cmd, bytes(data))

    def request(self, cid, cmd, data):
        if cmd == CTAPHID_INIT:
            if cid == BROADCAST:
                new, self.next_cid = self.next_cid, self.next_cid % 0xFFFFFFFE + 1
            else:
                new = cid
            caps = 0x04 | 0x08  # CBOR, no old-style U2F messages
            return self._reply(cid, CTAPHID_INIT, data[:8] + struct.pack(">IBBBBB", new, 2, 1, 0, 0, caps))
        if cmd == CTAPHID_PING:
            return self._reply(cid, CTAPHID_PING, data)
        if cmd == CTAPHID_WINK:
            return self._reply(cid, CTAPHID_WINK, b"")
        if cmd == CTAPHID_MSG:
            return self._reply(cid, CTAPHID_ERROR, b"\x01")
        if cmd != CTAPHID_CBOR:
            return self._reply(cid, CTAPHID_ERROR, b"\x01")
        if self.busy is not None:
            return self._reply(cid, CTAPHID_ERROR, b"\x06")  # busy
        self.busy = cid

        def run():
            done = threading.Event()

            def keepalive():  # "waiting for the person" every 100 ms
                while not done.wait(0.1):
                    self._reply(cid, CTAPHID_KEEPALIVE, b"\x02")
            threading.Thread(target=keepalive, daemon=True).start()
            try:
                result = self.auth.handle(data)
            except Exception as e:  # never leave the browser hanging
                log("error:", repr(e))
                result = bytes([0x7F])
            done.set()
            self._reply(cid, CTAPHID_CBOR, result)
            self.busy = None
        threading.Thread(target=run, daemon=True).start()


UHID_CREATE2, UHID_DESTROY, UHID_OUTPUT, UHID_INPUT2 = 11, 1, 6, 12
EVENT_SIZE = 4380


def run_device(handler):
    """The virtual USB security key. Runs as a system service (root), so it works
    from the moment the computer starts; each request is answered by
    `handler(request_bytes) -> response_bytes`."""
    fd = os.open("/dev/uhid", os.O_RDWR)
    lock = threading.Lock()

    def send(pkt):
        with lock:
            os.write(fd, struct.pack("<IH", UHID_INPUT2, len(pkt)) + pkt)

    create = struct.pack("<I", UHID_CREATE2)
    create += b"Floe Passkeys".ljust(128, b"\0") + b"floe-passkeys".ljust(64, b"\0") + b"floe".ljust(64, b"\0")
    create += struct.pack("<HHIIII", len(REPORT), 0x03, 0x1209, 0xF10E, 1, 0) + REPORT.ljust(4096, b"\0")
    os.write(fd, create)
    threading.Thread(target=open_up_node, daemon=True).start()

    class Router:
        handle = staticmethod(handler)
        cancel = staticmethod(cancel_request)
    hid = CtapHid(Router(), send)
    try:
        while True:
            ev = os.read(fd, EVENT_SIZE)
            if len(ev) < 4 or struct.unpack("<I", ev[:4])[0] != UHID_OUTPUT:
                continue
            size = struct.unpack("<H", ev[4 + 4096:4 + 4098])[0]
            data = ev[4:4 + size]
            if size == 65:  # report number in front
                data = data[1:]
            if len(data) >= 64:
                hid.packet(data[:64])
    finally:
        os.write(fd, struct.pack("<I", UHID_DESTROY))
        os.close(fd)


def find_node():
    """/dev/hidrawN of the Floe Passkeys device, or None."""
    import glob
    for d in glob.glob("/sys/class/hidraw/hidraw*"):
        try:
            uevent = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        if "HID_ID=0003:00001209:0000F10E" in uevent:
            return "/dev/" + os.path.basename(d)
    return None


def open_up_node():
    """Browsers open the security key as the signed-in person. The udev rule allows that;
    this does the same in case the rule hasn't applied (requests still need the PIN)."""
    for _ in range(50):
        node = find_node()
        if node and os.path.exists(node):
            time.sleep(0.5)  # let udev finish with it first
            try:
                os.chmod(node, 0o666)
            except OSError as e:
                log("couldn't open up", node, repr(e))
            log("ready as", node, oct(os.stat(node).st_mode & 0o777))
            return
        time.sleep(0.1)
    log("the security key didn't appear (is the uhid module loaded?)")


_current = {"proc": None}


def cancel_request():
    proc = _current["proc"]
    if proc and proc.poll() is None:
        log("the site cancelled; closing the prompt")
        proc.kill()


def active_desktop():
    """(user name, uid, home, runtime dir, wayland socket name) of the person using the screen."""
    import pwd
    try:
        out = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        sid = line.split()[0] if line.split() else ""
        if not sid:
            continue
        props = {}
        try:
            info = subprocess.run(["loginctl", "show-session", sid, "-p", "Active", "-p", "Type", "-p", "Name",
                                   "-p", "User", "-p", "Class", "-p", "Remote"],
                                  capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for kv in info.splitlines():
            k, _, v = kv.partition("=")
            props[k] = v
        if props.get("Active") != "yes" or props.get("Class") != "user" or props.get("Remote") == "yes":
            continue
        try:
            pw = pwd.getpwnam(props.get("Name", ""))
        except KeyError:
            continue
        run = f"/run/user/{pw.pw_uid}"
        socks = sorted((f for f in os.listdir(run) if f.startswith("wayland-") and not f.endswith(".lock")),
                       key=lambda f: os.path.getmtime(os.path.join(run, f)), reverse=True) if os.path.isdir(run) else []
        if socks:
            return pw.pw_name, pw.pw_uid, pw.pw_dir, run, socks[0]
    return None


def answer_as_user(data):
    """Root side: hand the request to the person at the screen, running as them
    (their passkeys, their PIN, the prompt on their screen)."""
    what = COMMANDS.get(data[0], hex(data[0])) if data else "empty"
    if data[:1] == b"\x04":  # getInfo needs nobody
        log("a browser found the security key")
        return bytes([OK]) + cbor_enc(Authenticator.get_info())
    if data[:1] == b"\x0b":  # "is this the key you want?"
        return bytes([OK])
    if os.environ.get("FLOE_PASSKEY_DIRECT"):  # automated tests: no desktop to route to
        return Authenticator(ask_person).handle(data)
    who = active_desktop()
    if not who:
        log(what, "- no one is signed in at the screen; refused")
        return bytes([ERR_OPERATION_DENIED])
    name, uid, home, run, sock = who
    if os.path.exists(os.path.join(home, ".config", "wren", "passkeys-off")):
        log(what, "- passkeys are turned off in Settings for", name)
        return bytes([ERR_OPERATION_DENIED])
    log(what, "- asking", name, "on", sock)
    env = {"HOME": home, "USER": name, "LOGNAME": name, "XDG_RUNTIME_DIR": run, "WAYLAND_DISPLAY": sock,
           "DBUS_SESSION_BUS_ADDRESS": f"unix:path={run}/bus", "XDG_CONFIG_DIRS": "/etc/xdg/wren:/etc/xdg",
           "PYTHONPATH": "/usr/lib/wren", "PATH": "/usr/local/bin:/usr/bin", "LANG": os.environ.get("LANG", "C.UTF-8"),
           "PYTHONUNBUFFERED": "1"}
    try:
        proc = subprocess.Popen(["setpriv", f"--reuid={uid}", f"--regid={pwd_gid(uid)}", "--init-groups",
                                 sys.executable, "-m", "passkeys", "--handle"], cwd=home if os.path.isdir(home) else "/",
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        _current["proc"] = proc
        try:
            out, err = proc.communicate(data, timeout=200)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        _current["proc"] = None
        if err:
            log(err.decode(errors="replace")[-800:].strip())
        if proc.returncode < 0:
            return bytes([0x2D])  # cancelled
        log(what, "- answered", hex(out[0]) if out else "nothing")
        return out or bytes([0x7F])
    except (OSError, subprocess.SubprocessError) as e:
        log(what, "- couldn't ask:", repr(e))
        return bytes([0x7F])


def pwd_gid(uid):
    import pwd
    return pwd.getpwuid(uid).pw_gid


def ask_person(request):
    """Shows Floe's passkey prompt (a separate small app) and waits for the answer."""
    if os.environ.get("FLOE_PASSKEY_TEST_PIN"):  # automated tests only
        return {"pin": os.environ["FLOE_PASSKEY_TEST_PIN"], "choice": 0}
    try:
        env = dict(os.environ, PYTHONPATH="/usr/lib/wren")
        proc = subprocess.run(PROMPT, input=json.dumps(request), capture_output=True, text=True, timeout=180, env=env)
        if proc.stderr.strip():
            log("prompt:", proc.stderr[-600:].strip())
        out = proc.stdout.strip()
        return json.loads(out) if out else None
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        log("prompt failed:", repr(e))
        return None


def status():
    """What `wren-passkeys status` prints: is everything in place?"""
    node = find_node()
    print("security key:", node or "not present (is floe-passkeys.service running?)")
    if node:
        st = os.stat(node)
        print("permissions:", oct(st.st_mode & 0o777), "ok" if st.st_mode & 0o006 == 0o006 or os.access(node, os.R_OK | os.W_OK)
              else "- browsers can't open it")
    who = active_desktop()
    print("person at the screen:", f"{who[0]} on {who[4]}" if who else "none found")
    print("passkey PIN set:", "yes" if has_pin() else "no (it's chosen the first time you save a passkey)")
    print("saved passkeys:", len(list_passkeys()))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in ("--system", "--daemon"):
        run_device(answer_as_user)
    elif cmd == "--handle":  # one request, answered as the signed-in person
        req = sys.stdin.buffer.read()
        sys.stdout.buffer.write(Authenticator(ask_person).handle(req))
    elif cmd == "status":
        status()
    elif cmd == "list":
        print(json.dumps(list_passkeys(), indent=1))
    elif cmd == "delete" and len(sys.argv) > 2:
        sys.exit(0 if delete_passkey(sys.argv[2]) else 1)
    else:
        print(__doc__)
