"""Exercise the Chrome pipe and CLI socket together using a temporary home."""
from contextlib import closing
from pathlib import Path
import os
import select
import socket
import subprocess
import sys
import tempfile
import time
import unittest

APP = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP))
from native_host import receive, send


class NativeHostTest(unittest.TestCase):
    def test_expired_and_abandoned_clients_do_not_poison_next_answer(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as home, subprocess.Popen(
            [sys.executable, str(APP / 'native_host.py')], env=dict(os.environ, HOME=home),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        ) as host:
            try:
                endpoint = Path(home) / '.config/panelize-local/doubao.sock'
                deadline = time.monotonic() + 4
                while not endpoint.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)

                def client():
                    conn = socket.socket(socket.AF_UNIX)
                    conn.settimeout(4)
                    conn.connect(str(endpoint))
                    stream = conn.makefile('rwb')
                    conn.close()
                    return closing(stream)

                def dispatch(stream, name, ttl):
                    job = dict(id=name, query=name, deadline=int((time.time()+ttl)*1000))
                    send(stream, job)
                    self.assertTrue(select.select([host.stdout], [], [], 4)[0])
                    self.assertEqual(receive(host.stdout), job)

                with client():
                    pass  # The caller disconnected before sending a frame.
                with client() as stream:
                    dispatch(stream, 'old', 0.25)
                    self.assertIn('error', receive(stream))
                with client() as stream:
                    dispatch(stream, 'new', 3)
                    send(host.stdin, {'id':'old', 'answer':'stale'})
                    send(host.stdin, {'id':'new', 'answer':'fresh'})
                    self.assertEqual(receive(stream), {'id':'new', 'answer':'fresh'})
            finally:
                host.stdin.close()
                try:
                    host.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    host.kill()
                    raise
            self.assertEqual(host.returncode, 0)
