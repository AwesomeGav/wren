"""List the app IDs of open windows, straight from the Wayland compositor.

A tiny Wayland client (no extra libraries) that binds the wlr foreign-toplevel
manager, which labwc offers so taskbars can show open windows.

  python3 -m winlist        prints one app id per window
"""
import os
import socket
import struct

IFACE = "zwlr_foreign_toplevel_manager_v1"


def _string(s):
    b = s.encode() + b"\0"
    return struct.pack("=I", len(b)) + b + b"\0" * (-len(b) % 4)


def _msg(obj, opcode, payload=b""):
    return struct.pack("=II", obj, ((8 + len(payload)) << 16) | opcode) + payload


def _read_string(data, off):
    n = struct.unpack_from("=I", data, off)[0]
    s = data[off + 4:off + 4 + n - 1].decode(errors="replace") if n else ""
    return s, off + 4 + n + (-n % 4)


class _Conn:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(2)
        self.sock.connect(path)
        self.buf = b""
        self.next_id = 2

    def new_id(self):
        i = self.next_id
        self.next_id += 1
        return i

    def send(self, data):
        self.sock.sendall(data)

    def events(self):
        while True:
            while len(self.buf) >= 8:
                obj, word = struct.unpack_from("=II", self.buf)
                size, opcode = word >> 16, word & 0xFFFF
                if size < 8 or len(self.buf) < size:
                    break
                body, self.buf = self.buf[8:size], self.buf[size:]
                yield obj, opcode, body
            chunk = self.sock.recv(65536)
            if not chunk:
                return
            self.buf += chunk


def app_ids():
    """App IDs of every open window (empty list if the compositor can't be reached)."""
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
    path = display if display.startswith("/") else os.path.join(runtime, display)
    try:
        conn = _Conn(path)
    except OSError:
        return None
    try:
        registry = conn.new_id()
        conn.send(_msg(1, 1, struct.pack("=I", registry)))
        cb = conn.new_id()
        conn.send(_msg(1, 0, struct.pack("=I", cb)))
        manager_name = manager_ver = None
        stage = "globals"
        handles = {}
        manager = None
        for obj, op, body in conn.events():
            if obj == 1 and op == 0:  # wl_display.error
                return None
            if obj == registry and op == 0:
                name = struct.unpack_from("=I", body)[0]
                iface, off = _read_string(body, 4)
                ver = struct.unpack_from("=I", body, off)[0]
                if iface == IFACE:
                    manager_name, manager_ver = name, min(ver, 3)
            elif obj == cb and op == 0:
                if stage == "globals":
                    if manager_name is None:
                        return None
                    manager = conn.new_id()
                    conn.send(_msg(registry, 0, struct.pack("=I", manager_name) + _string(IFACE)
                                   + struct.pack("=II", manager_ver, manager)))
                    stage = "windows"
                elif stage == "windows":
                    stage = "settle"
                else:
                    break
                cb = conn.new_id()
                conn.send(_msg(1, 0, struct.pack("=I", cb)))
            elif manager is not None and obj == manager and op == 0:
                handles[struct.unpack_from("=I", body)[0]] = {"app_id": "", "closed": False}
            elif obj in handles:
                if op == 1:
                    handles[obj]["app_id"] = _read_string(body, 0)[0]
                elif op == 6:
                    handles[obj]["closed"] = True
        return [h["app_id"] for h in handles.values() if not h["closed"]]
    except (OSError, struct.error):
        return None
    finally:
        conn.sock.close()


if __name__ == "__main__":
    ids = app_ids()
    if ids is None:
        raise SystemExit("Couldn't read the window list")
    print("\n".join(ids))
