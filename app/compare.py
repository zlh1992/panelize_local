"""Run the same question through four independent targets."""
import argparse
import concurrent.futures
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import codex_worker
from native_host import ROOT, SOCKET, send, receive

TARGETS = ('codex', 'minimax', 'doubao', 'deepseek')
DSH = Path.home()/'.local/share/panelize-local/dsh/node_modules/.bin/dsh'


def private_key(env, file):
    value = os.getenv(env)
    if not value:
        if not file.is_file():
            raise ValueError(f'请配置 {env} 或 {file.name}')
        value = file.read_text().strip()
    if not value:
        raise ValueError(f'{env} 为空')
    return value


def run_process(args, query, env, cwd, timeout, secrets=()):
    proc = subprocess.Popen(args, env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(query, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise ValueError('运行超时，已终止本次进程组')
    if proc.returncode:
        diagnostic = (err.strip() or out.strip())[-1400:]
        for secret in secrets:
            diagnostic = diagnostic.replace(secret, '[redacted]')
        diagnostic = re.sub(r'(?i)(?:sk-|Bearer )[\w.-]+', '[redacted]', diagnostic)
        raise ValueError(f'进程退出 {proc.returncode}: {diagnostic}')
    return out


def cli_env():
    return {k:v for k,v in os.environ.items() if k in {
        'HOME','PATH','LANG','LC_ALL','TMPDIR','USER','LOGNAME','SystemRoot',
        'HTTPS_PROXY','HTTP_PROXY','NO_PROXY','https_proxy','http_proxy','no_proxy','SSL_CERT_FILE',
        'NODE_EXTRA_CA_CERTS'}}


def call(target, q, a, work):
    if target == 'codex':
        auth = Path(a.codex_auth).expanduser()
        if json.loads(auth.read_text()).get('auth_mode') != 'chatgpt':
            raise ValueError('所选凭据未标记为 ChatGPT 订阅登录')
        config = dict(model=a.codex_model, effort=a.effort, auth_file=str(auth), runtime_dir=str(ROOT/'codex'))
        answer = work/'codex-answer'
        codex_worker.run(config, q, answer, timeout=a.timeout)
        return answer.read_text(), {'route':'Codex CLI / ChatGPT login','effort':a.effort}
    if target == 'minimax':
        route = os.environ.get('PANELIZE_MINIMAX_URL','https://api.minimaxi.com/anthropic').rstrip('/')
        if route not in {'https://api.minimaxi.com/anthropic','https://api.minimax.io/anthropic'}:
            raise ValueError('MiniMax 入口须为官方国内或海外地址')
        env = cli_env()
        args = ['claude']
        if a.magpie_model:
            args = ['magpie','claude','run']
            model = a.magpie_model
            route = 'magpie/'+model
            secrets = ()
        else:
            model = a.minimax_model
            token = private_key('MINIMAX_API_KEY',ROOT/'minimax.key')
            env.update(ANTHROPIC_BASE_URL=route, ANTHROPIC_AUTH_TOKEN=token, ANTHROPIC_MODEL=model,
                       CLAUDE_CONFIG_DIR=str(work/'claude'), CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
            secrets = (token,)
        kwargs = ['--bare','--setting-sources','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}',
                  '--tools','','--model',model,'--no-session-persistence','-p','--output-format','json']
        result = json.loads(run_process(args+kwargs,q,env,work,a.timeout,secrets))
        if result.get('is_error') or result.get('subtype') != 'success':
            raise ValueError('Claude Code 未成功完成本轮')
        return result['result'], {'route':route, 'model_usage':list((result.get('modelUsage') or {}).keys())}
    if target == 'deepseek':
        key = private_key('DEEPSEEK_API_KEY',ROOT/'deepseek.key')
        exe = os.getenv('PANELIZE_DSH') or (str(DSH) if DSH.exists() else 'dsh')
        env = cli_env()
        env.update(DEEPSEEK_API_KEY=key, DSH_HOME=str(work/'dsh-home'))
        patch = work/'model.yml'
        patch.write_text('- id: agent-default-model\n  config:\n    provider: deepseek-official\n    model: '+json.dumps(a.deepseek_model)+'\n')
        args = [exe,'headless','--patch',str(patch),'--permission-mode','read-only','--approval-policy','never','--json','-']
        out = run_process(args,q,env,work,a.timeout,(key,))
        events = [json.loads(line) for line in out.splitlines() if line.strip()]
        final = events[-1] if events else {}
        if final.get('type') != 'final' or final.get('reason') not in ('completed', {'kind':'completed'}):
            raise ValueError('DSH 未产生成功的 final 事件')
        return final['text'], {'route':'dsh / deepseek-official','session':final['sessionId']}
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(a.timeout+3)
        try:
            client.connect(str(SOCKET))
        except OSError as e:
            raise ValueError('豆包扩展未连接。请在已登录的 Chrome 中加载 extension，并点击扩展图标') from e
        with client.makefile('rwb') as io:
            job = uuid.uuid4().hex
            send(io,dict(query=q,id=job,deadline=int((time.time()+a.timeout)*1000)))
            result = receive(io)
            if result.get('error'):
                raise ValueError(result['error'])
            if result.get('id') != job or not result.get('source','').startswith('https://www.doubao.com/'):
                raise ValueError('豆包回执与请求不匹配')
            return result['answer'], {'source':result['source'], 'model':'网页未披露'}


def execute(target, q, a, folder):
    start = time.monotonic()
    model = {'codex':a.codex_model,'minimax':a.magpie_model or a.minimax_model,
             'deepseek':a.deepseek_model,'doubao':None}[target]
    result = dict(target=target,requested_model=model,status='failed')
    try:
        with tempfile.TemporaryDirectory(prefix='panelize-task-') as temp:
            answer, meta = call(target,q,a,Path(temp))
        if not isinstance(answer,str) or not answer.strip():
            raise ValueError('空答案')
        path = folder/(target+'.md')
        path.write_text(answer)
        result.update(status='completed',answer=path.name,**meta)
    except Exception as e:
        result['error'] = str(e) or type(e).__name__
    result['seconds'] = round(time.monotonic()-start,2)
    (folder/(target+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    q = p.add_mutually_exclusive_group()
    q.add_argument('--query','-q')
    q.add_argument('--query-file',type=Path)
    p.add_argument('--targets',default=','.join(TARGETS))
    p.add_argument('--codex-model',default='gpt-6.2-sol')
    p.add_argument('--effort',choices=['low','medium','high','xhigh'],default='high')
    p.add_argument('--codex-auth',default='~/.codex/auth.json')
    p.add_argument('--minimax-model',default='MiniMax-M3')
    p.add_argument('--magpie-model',help='通过 magpie claude run 选择已配置的 MiniMax 路由')
    p.add_argument('--deepseek-model',default='deepseek-flash')
    p.add_argument('--timeout',type=int,default=240)
    p.add_argument('--out',type=Path,default=Path.cwd()/'runs')
    a = p.parse_args()
    targets = list(dict.fromkeys(a.targets.split(',')))
    if any(t not in TARGETS for t in targets) or a.timeout < 1: p.error('无效 targets / timeout')
    query = a.query if a.query is not None else (a.query_file.read_text() if a.query_file else sys.stdin.read())
    if not query.strip() or len(query.encode()) > 120000: p.error('请输入 1–120000 字节的非空问题')
    folder = a.out.resolve()/(dt.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    (folder/'query.md').write_text(query)
    print(folder,flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as pool:
        jobs = [pool.submit(execute,t,query,a,folder) for t in targets]
        for job in concurrent.futures.as_completed(jobs):
            row = job.result()
            print(row['target'],row['status'],row.get('error','')[:250],flush=True)
    results = [job.result() for job in jobs]
    (folder/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    cards = []
    for r in results:
        content = (folder/r['answer']).read_text() if r['status']=='completed' else r['error']
        cards.append('<article><h2>'+r['target']+'</h2><small>'+html.escape(str(r['requested_model'] or 'Web')+' · '+r['status']+' · '+str(r['seconds'])+'s')+'</small><pre>'+html.escape(content)+'</pre></article>')
    (folder/'index.html').write_text('<!doctype html><meta charset=utf-8><title>回答对比</title><style>body{font:16px system-ui;margin:2rem}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1rem}article{padding:1rem;border:1px solid #ccc}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>回答对比</h1><pre>'+html.escape(query)+'</pre><main>'+''.join(cards)+'</main>')
    return int(any(r['status']!='completed' for r in results))

if __name__ == '__main__':
    sys.exit(main())
