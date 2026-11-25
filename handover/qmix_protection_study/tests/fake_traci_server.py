"""A minimal stand-in for SUMO's TraCI server, for tests/test_resume_b.py (no simulation at all).

    python fake_traci_server.py <mode> <state file> ... --remote-port <port>

Modes:
  ok        answers getVersion and close, then exits;
  short     accepts the connection and answers the first request with a 2-byte payload: the real traci client then
            fails in getVersion with struct.error('unpack requires a buffer of 3 bytes'), as in the B incident;
  flaky:N   behaves as "short" for the first N launches (counted in the state file), then as "ok";
  exit      exits at once without listening (SUMO's "Address already in use ... Quitting (on error)").
"""
import os
import socket
import struct
import sys

CMD_GETVERSION, CMD_CLOSE = 0x00, 0x7F


def recv_exact(conn, n):
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def read_message(conn):
    head = recv_exact(conn, 4)
    if head is None:
        return None
    return recv_exact(conn, struct.unpack("!i", head)[0] - 4)


def command_id(payload):
    length = payload[0]
    return payload[5] if length == 0 else payload[1]


def status(cmd):
    return struct.pack("!BBB", 7, cmd, 0) + struct.pack("!i", 0)


def send(conn, payload):
    conn.sendall(struct.pack("!i", len(payload) + 4) + payload)


def main(argv):
    mode, state = argv[1], argv[2]
    port = int(argv[argv.index("--remote-port") + 1])
    if mode.startswith("flaky:"):
        n = int(mode.split(":")[1])
        count = 0
        if os.path.exists(state):
            with open(state, encoding="utf-8") as f:
                count = int(f.read() or 0)
        with open(state, "w", encoding="utf-8") as f:
            f.write(str(count + 1))
        mode = "short" if count < n else "ok"
    if mode == "exit":
        return 1
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("localhost", port))
    server.listen(1)
    conn, _ = server.accept()
    server.close()
    try:
        while True:
            payload = read_message(conn)
            if payload is None:
                return 0
            if mode == "short":
                send(conn, b"\x00\x00")
                return 0
            cmd = command_id(payload)
            if cmd == CMD_GETVERSION:
                version = b"fake SUMO for tests"
                body = struct.pack("!BBi", 1 + 1 + 4 + 4 + len(version), CMD_GETVERSION, 21)
                send(conn, status(cmd) + body + struct.pack("!i", len(version)) + version)
            elif cmd == CMD_CLOSE:
                send(conn, status(cmd))
                return 0
            else:
                send(conn, status(cmd))
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
