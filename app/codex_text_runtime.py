"""Adapted from wechat-people-graph/backend/codex_text_runtime.py.

Persistent locked homes; authentication and runtime paths must be explicit.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import threading
import time

FEATURES = ('plugins', 'remote_plugin', 'plugin_discovery_prefetch')
CONFIG = '[features]\nplugins = false\nremote_plugin = false\nplugin_discovery_prefetch = false\n'
DISABLE_ARGS = [arg for name in FEATURES for arg in ('--disable', name)]
_CACHE = set()
_CACHE_LOCK = threading.Lock()


def _directory(path):
    path = Path(path).absolute()
    for p in reversed((path, *path.parents)):
        if p.is_symlink(): raise RuntimeError('runtime path contains a symlink')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink(): raise RuntimeError('invalid runtime directory')
    os.chmod(path, 0o700)


def _atomic_private(path, data):
    if path.is_symlink(): raise RuntimeError('runtime file is a symlink')
    fd, name = tempfile.mkstemp(prefix='.update-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as f: f.write(data)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def _preflight(home, executable=None):
    executable = executable or shutil.which('codex')
    if not executable: raise RuntimeError('Codex CLI unavailable')
    executable = str(Path(executable).resolve(strict=True)); stat = os.stat(executable)
    signature = (executable, stat.st_ino, stat.st_size, stat.st_mtime_ns, str(home), hashlib.sha256(CONFIG.encode()).hexdigest())
    with _CACHE_LOCK:
        if signature in _CACHE: return
        env = clean_env(home)
        try:
            version = subprocess.run([executable, '--version'], env=env, capture_output=True, text=True, timeout=15, check=True)
            features = subprocess.run([executable, 'features', 'list', *DISABLE_ARGS], env=env, capture_output=True, text=True, timeout=15, check=True)
        except (OSError, subprocess.SubprocessError) as exc: raise RuntimeError('Codex local feature preflight failed') from exc
        found = {}
        for line in features.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0] in FEATURES: found[parts[0]] = parts[-1].lower()
        if not version.stdout.strip() or found != {name:'false' for name in FEATURES}:
            raise RuntimeError('Codex plugin feature preflight failed')
        _atomic_private(home/'.preflight.json', json.dumps({'cli_version':version.stdout.strip(), 'cli_signature':hashlib.sha256(repr(signature).encode()).hexdigest(), 'disabled_features':list(FEATURES)}, sort_keys=True).encode())
        _CACHE.add(signature)


def _check_blocked(slot_root):
    marker = slot_root / '.blocked'
    if marker.is_symlink() or marker.exists():
        raise RuntimeError('Codex batch runtime blocked; inspect preserved plugin cache')


def _block(slot_root):
    marker = slot_root / '.blocked'
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, 'w') as f:
        f.write('Unexpected plugin content or unsafe plugin path; inspection required.\n')


def _check_plugins(home, slot_root):
    plugins = home / 'plugins'
    try:
        if plugins.is_symlink(): raise ValueError('plugin symlink')
        if not plugins.exists(): return
        if not plugins.is_dir(): raise ValueError('invalid plugin root')
        pending = [plugins]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode): raise ValueError('plugin symlink')
                    if stat.S_ISDIR(info.st_mode): pending.append(entry.path)
                    elif stat.S_ISREG(info.st_mode):
                        if info.st_size: raise ValueError('nonempty plugin file')
                    else: raise ValueError('invalid plugin entry')
    except (OSError, ValueError) as exc:
        _block(slot_root)
        raise RuntimeError('Codex plugin content detected; batch runtime blocked') from exc


@contextmanager
def worker_home(auth_source, slot_root, executable=None, lock_timeout=30):
    auth_source = Path(auth_source).absolute()
    slot_root = Path(slot_root).absolute()
    deadline = time.monotonic() + lock_timeout
    _directory(slot_root)
    _check_blocked(slot_root)
    if auth_source.is_symlink() or not auth_source.is_file(): raise RuntimeError('Codex auth source unavailable')
    lock_fd = None
    try:
        while lock_fd is None:
            if time.monotonic() >= deadline: raise RuntimeError('Codex worker lock timeout')
            _check_blocked(slot_root)
            for index in range(3):
                home = slot_root / ('worker-' + str(index + 1)); _directory(home)
                lock = home / '.lock'
                fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                os.fchmod(fd, 0o600)
                try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: os.close(fd); continue
                lock_fd = fd; break
            if lock_fd is None: time.sleep(0.1)
        _check_blocked(slot_root)
        _check_plugins(home, slot_root)
        _check_blocked(slot_root)
        auth = auth_source.read_bytes()
        _atomic_private(home/'auth.json', auth)
        _atomic_private(home/'config.toml', CONFIG.encode())
        _preflight(home, executable)
        yield home
    finally:
        if lock_fd is not None:
            try:
                _check_plugins(home, slot_root)
                _check_blocked(slot_root)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN); os.close(lock_fd)


def clean_env(home):
    keep = ('PATH','HOME','USER','LANG','LC_ALL','TMPDIR','HTTP_PROXY','HTTPS_PROXY',
            'NO_PROXY','http_proxy','https_proxy','no_proxy','SSL_CERT_FILE')
    env = {key: os.environ[key] for key in keep if key in os.environ}
    proxy_file = Path.home()/'.config/panelize-local/codex-proxy'
    if proxy_file.is_file():
        proxy = proxy_file.read_text().strip()
        env.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy)
    env['CODEX_HOME'] = str(home)
    return env
