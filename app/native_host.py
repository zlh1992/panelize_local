#!/usr/bin/env python3
"""Chrome native messaging host. macOS/Linux private Unix socket, no network listener."""
import fcntl
import json
import os
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path.home() / '.config/panelize-local'
SOCKET = ROOT / 'doubao.sock'
LIMIT = 950_000


def exact(stream, count):
    data = stream.read(count)
    if len(data) != count:
        raise EOFError
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


def main():
    import select
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (ROOT/'host.lock').open('a') as lock, socket.socket(socket.AF_UNIX) as server:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        SOCKET.unlink(missing_ok=True)
        server.bind(str(SOCKET))
        server.listen(8)
        try:
            while True:
                ready, _, _ = select.select([server, sys.stdin.buffer], [], [])
                if sys.stdin.buffer in ready:
                    break
                conn, _ = server.accept()
                with conn, conn.makefile('rwb') as io:
                    conn.settimeout(10)
                    try:
                        job = receive(io)
                        if job.get('type') == 'ping':
                            send(io, {'ready': True})
                            continue
                        if job['deadline'] <= time.time()*1000:
                            send(io, {'error':'queued job expired'})
                            continue
                        send(sys.stdout.buffer, job)
                        result = receive(sys.stdin.buffer)
                        if result.get('id') != job['id']:
                            raise ValueError('mismatched job id')
                        send(io, result)
                    except (BrokenPipeError, ConnectionResetError, TimeoutError):
                        continue
        finally:
            SOCKET.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
