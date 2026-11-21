#!/usr/bin/env python3
"""Chrome native messaging host. macOS/Linux private Unix socket, no network listener."""
import fcntl
import json
import os
import select
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path.home() / '.config/panelize-local'
SOCKET = ROOT / 'doubao.sock'
LIMIT = 950_000


def exact(stream, count):
    data = bytearray()
    while len(data) < count:
        chunk = stream.read(count - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return data


def receive(stream):
    length, = struct.unpack('=I', exact(stream, 4))
    if length > LIMIT:
        raise ValueError('message too large')
    return json.loads(exact(stream, length))


def send(stream, value):
    data = json.dumps(value, ensure_ascii=False).encode()
    if len(data) > LIMIT:
        raise ValueError('message too large')
    stream.write(struct.pack('=I', len(data)) + data)
    stream.flush()


def handle_client(conn, chrome):
    with conn, conn.makefile('rwb') as io:
        conn.settimeout(10)
        try:
            job = receive(io)
        except (EOFError, ValueError):
            return
        if not isinstance(job, dict):
            return
        if job.get('type') == 'ping':
            send(io, {'ready': True})
            return
        if not isinstance(job.get('id'), str) or not isinstance(job.get('deadline'), (float, int)):
            send(io, {'error': 'invalid job'})
            return
        deadline = job['deadline'] / 1000
        if deadline <= time.time():
            send(io, {'error': 'queued job expired'})
            return
        send(sys.stdout.buffer, job)
        while select.select([chrome], [], [], max(0, deadline - time.time()))[0]:
            result = receive(chrome)
            if result.get('id') == job['id']:
                send(io, result)
                return
        send(io, {'error': '豆包网页超时，请检查已打开的标签页'})


def main():
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Unbuffered reads keep select() in sync with Chrome's native message frames.
    with (ROOT/'host.lock').open('a') as lock, socket.socket(socket.AF_UNIX) as server, \
            os.fdopen(sys.stdin.fileno(), 'rb', buffering=0, closefd=False) as chrome:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        SOCKET.unlink(missing_ok=True)
        server.bind(str(SOCKET))
        server.listen(8)
        try:
            while True:
                ready, _, _ = select.select([server, chrome], [], [])
                if chrome in ready:
                    receive(chrome)  # Discard a late response to an expired request.
                if server in ready:
                    conn, _ = server.accept()
                    try:
                        handle_client(conn, chrome)
                    except (BrokenPipeError, ConnectionResetError, TimeoutError):
                        continue
        except EOFError:
            pass  # Chrome closed its port.
        finally:
            SOCKET.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
