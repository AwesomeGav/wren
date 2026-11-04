#!/usr/bin/env python3
"""Checks Wren Login's greetd conversation against a fake greetd server."""
import json
import os
import socket
import struct
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rootfs", "usr", "lib", "wren"))
import greeter  # noqa: E402

PASSWORD = "right-password"


def serve(path, log):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(5)

    def handle(conn):
        def recv(n):
            b = b""
            while len(b) < n:
                c = conn.recv(n - len(b))
                if not c:
                    raise EOFError
                b += c
            return b

        def send(obj):
            d = json.dumps(obj).encode()
            conn.sendall(struct.pack("=I", len(d)) + d)
        try:
            while True:
                (n,) = struct.unpack("=I", recv(4))
                msg = json.loads(recv(n))
                log.append(msg)
                t = msg["type"]
                if t == "create_session":
                    send({"type": "auth_message", "auth_message_type": "secret", "auth_message": "Password: "})
                elif t == "post_auth_message_response":
                    if msg["response"] == PASSWORD:
                        send({"type": "success"})
                    else:
                        send({"type": "error", "error_type": "auth_error", "description": "pam"})
                elif t in ("start_session", "cancel_session"):
                    send({"type": "success"})
        except EOFError:
            pass

    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def main():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "greetd.sock")
    log = []
    threading.Thread(target=serve, args=(path, log), daemon=True).start()
    import time
    for _ in range(50):
        if os.path.exists(path):
            break
        time.sleep(0.05)

    client = greeter.Greetd(path)
    wrong = client.login("tester", "nope", ["labwc"])
    assert wrong == "Wrong password. Try again.", wrong
    assert log[-1]["type"] == "cancel_session", log
    right = client.login("tester", PASSWORD, ["labwc"])
    assert right is None, right
    assert log[-1] == {"type": "start_session", "cmd": ["labwc"], "env": []}, log[-1]
    assert any(m == {"type": "create_session", "username": "tester"} for m in log)
    print("Wren Login: greetd conversation OK")


if __name__ == "__main__":
    main()
