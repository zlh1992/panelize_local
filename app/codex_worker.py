#!/usr/bin/env python3
"""Run a configured, text-only Codex worker with no ambient account fallback."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

import codex_text_runtime as runtime

# Matches activity, not benign flags such as `plugins=false`.
PLUGIN_ACTIVITY = re.compile(r'(?i)(?:plugin[^\n]{0,100}(?:download|sync|fetch|install)|(?:download|sync|fetch|install)[^\n]{0,100}plugin)')
TEXT_ONLY_INSTRUCTIONS = (
    "Answer the user's question directly in text. This worker has no external data or tools. "
    "Do not call tools, discover MCP resources, or invoke skills. "
    "If current data is needed and the user did not supply it, say what cannot be verified."
)


def configuration(path):
    cfg = json.loads(Path(path).read_text())['providers']['codex']
    if cfg.get('enabled') is not True:
        raise ValueError('Codex is disabled; explicitly configure this account first')
    for field in ('auth_file', 'model', 'runtime_dir'):
        if not isinstance(cfg.get(field), str) or not cfg[field].strip():
            raise ValueError('Missing Codex configuration: ' + field)
    for field in ('auth_file', 'runtime_dir'):
        if not Path(cfg[field]).is_absolute():
            raise ValueError(field + ' must be an absolute path')
    if not Path(cfg['auth_file']).is_file():
        raise ValueError('Configured Codex auth_file does not exist')
    return cfg


def terminate(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)


def run(cfg, prompt, output, executable=None, timeout=600):
    executable = executable or runtime.resolve_codex()
    if not prompt.strip():
        raise ValueError('Prompt must not be empty')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists; select a new result path')
    root = Path(cfg['runtime_dir'])
    with runtime.worker_home(cfg['auth_file'], root, executable) as home:
        with tempfile.TemporaryDirectory(prefix='text-task-', dir=home) as temporary:
            work = Path(temporary)
            result = work / 'answer.txt'
            args = [executable, 'exec', '--ignore-user-config', '--strict-config',
                    *runtime.DISABLE_ARGS, '--ephemeral', '--skip-git-repo-check',
                    '-s', 'read-only', '--disable', 'shell_tool', '--disable', 'apps',
                    '--disable', 'browser_use', '--disable', 'computer_use',
                    '-c', 'skills.include_instructions=false',
                    '-c', 'developer_instructions=' + json.dumps(TEXT_ONLY_INSTRUCTIONS),
                    '-c', 'web_search="disabled"', '--json', '-c', 'model_reasoning_effort='+json.dumps(cfg.get('effort','high')), '-m', cfg['model'],
                    '-o', str(result), '-']
            with (work/'prompt.txt').open('w+') as inp, (work/'stdout').open('w+') as stdout, (work/'stderr').open('w+') as stderr:
                inp.write(prompt)
                inp.seek(0)
                proc = subprocess.Popen(args, stdin=inp, stdout=stdout, stderr=stderr,
                                        cwd=work, env=runtime.clean_env(home), start_new_session=True)
                start = time.monotonic()
                offsets = [0, 0]
                tails = ['', '']
                stdout_pending = ''
                try:
                    while True:
                        runtime._check_blocked(root)
                        runtime._check_plugins(home, root)
                        for i, log in enumerate((work/'stdout', work/'stderr')):
                            with log.open(errors='replace') as stream:
                                stream.seek(offsets[i]); chunk = stream.read(1024 * 1024); offsets[i] = stream.tell()
                            # Only stderr operational logs are checked for sync text; model answers may discuss plugins.
                            if i == 1 and PLUGIN_ACTIVITY.search(tails[i] + chunk):
                                runtime._block(root)
                                raise RuntimeError('Plugin activity detected; runtime blocked for inspection')
                            if i == 0:
                                stdout_pending += chunk
                                lines = stdout_pending.split('\n')
                                stdout_pending = lines.pop()
                                for line in lines:
                                    try:
                                        event = json.loads(line)
                                    except json.JSONDecodeError:
                                        event = {}
                                    item_type = (event.get('item') or {}).get('type') if isinstance(event, dict) else None
                                    if item_type not in ('agent_message', 'reasoning') and PLUGIN_ACTIVITY.search(line):
                                        runtime._block(root)
                                        raise RuntimeError('Plugin activity detected; runtime blocked for inspection')
                            tails[i] = (tails[i] + chunk)[-256:]
                        if proc.poll() is not None:
                            break
                        if time.monotonic() - start > timeout:
                            raise RuntimeError('Codex worker timed out')
                        time.sleep(0.1)
                    if proc.returncode != 0:
                        raise RuntimeError('Codex worker failed; exit=' + str(proc.returncode))
                    completed = False
                    for line in (work/'stdout').read_text().splitlines():
                        event = json.loads(line)
                        if event.get('type') == 'turn.completed': completed = True
                        item = event.get('item') or {}
                        if item.get('type') not in (None, 'agent_message', 'reasoning', 'error'):
                            raise RuntimeError(f"Unexpected Codex item {item['type']!r}; answer rejected")
                        if event.get('type') in ('turn.failed', 'error') or item.get('type') == 'error':
                            raise RuntimeError('Codex reported an error; answer rejected')
                    if not completed or not result.is_file() or not result.read_text().strip():
                        raise RuntimeError('No completed nonempty Codex answer')
                    answer = result.read_bytes()
                finally:
                    terminate(proc)
    # Publish only after final runtime checks and lock release succeed.
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as destination: destination.write(answer)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--prompt')
    parser.add_argument('--output')
    parser.add_argument('--preflight', action='store_true', help='Check explicit configuration and local CLI features only; no model call')
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    try:
        cfg = configuration(args.config)
        if args.preflight:
            with runtime.worker_home(cfg['auth_file'], cfg['runtime_dir']) as home:
                print(json.dumps({'status': 'local_preflight_passed', 'home': str(home), 'model_called': False}))
        else:
            if not args.prompt or not args.output:
                raise ValueError('--prompt and --output are required unless --preflight is used')
            if args.timeout <= 0:
                raise ValueError('--timeout must be positive')
            print(run(cfg, Path(args.prompt).read_text(), args.output, timeout=args.timeout))
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
