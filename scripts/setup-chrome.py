#!/usr/bin/env python3
"""Register this checkout as a native host for only the bundled extension."""
import base64
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

os.umask(0o077)
root = Path(__file__).resolve().parents[1]
cfg = Path.home()/'.config/panelize-local'
cfg.mkdir(parents=True, exist_ok=True)
manifest = json.loads((root/'extension/manifest.json').read_text())
digest = hashlib.sha256(base64.b64decode(manifest['key'])).hexdigest()[:32]
extension = ''.join(chr(97+int(c,16)) for c in digest)
directory = Path.home()/('Library/Application Support/Google/Chrome/NativeMessagingHosts' if sys.platform == 'darwin' else '.config/google-chrome/NativeMessagingHosts')
directory.mkdir(parents=True, exist_ok=True)
launcher = cfg/'native-host'
launcher.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(root/'app/native_host.py'))+'\n')
launcher.chmod(0o700)
(directory/'local.panelize.compare.json').write_text(json.dumps(dict(name='local.panelize.compare', description='Panelize Local', path=str(launcher), type='stdio', allowed_origins=['chrome-extension://'+extension+'/'])))
print('Chrome → chrome://extensions → 开发者模式 → 加载已解压的扩展程序：',root/'extension')
