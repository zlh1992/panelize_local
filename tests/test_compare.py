import argparse
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import compare
import codex_worker
import codex_text_runtime
import native_host


class CompareTest(unittest.TestCase):
    def test_agent_accepts_tool_items_then_requires_completed_turn(self):
        events = [
            {'type':'turn.started'},
            {'type':'item.started','item':{'id':'w','type':'web_search'}},
            {'type':'item.completed','item':{'id':'w','type':'web_search'}},
            {'type':'item.completed','item':{'id':'s','type':'mcp_tool_call','tool':'search','status':'failed'}},
            {'type':'item.completed','item':{'id':'x','type':'command_execution','status':'completed'}},
            {'type':'item.completed','item':{'type':'agent_message','text':'answer'}},
            {'type':'turn.completed'},
        ]
        self.assertEqual([x['tool'] for x in codex_worker.agent_tools(map(json.dumps,events))],
                         ['web_search','search','command_execution'])
        for last in ('turn.started', 'turn.failed', 'turn.cancelled'):
            with self.assertRaises(RuntimeError):
                codex_worker.agent_tools(map(json.dumps, events + [{'type':last}]))

    def test_report_is_readable_while_another_target_is_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/'codex.md').write_text('done')
            row = dict(requested_model='gpt',status='completed',answer='codex.md',seconds=1)
            compare.write_report(folder,'question',{'codex':row,'deepseek':None})
            report = (folder/'index.html').read_text()
            self.assertIn('运行中', report)
            self.assertIn('done', report)
            self.assertIn('http-equiv="refresh"', report)
            compare.write_report(folder,'question',{'codex':row})
            self.assertNotIn('http-equiv="refresh"', (folder/'index.html').read_text())

    def test_codex_discovery_with_and_without_terminal_path(self):
        bundle = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / 'codex'
            cli.touch(mode=0o700)
            with patch.dict(os.environ, {'PATH':tmp, 'PANELIZE_CODEX':''}):
                self.assertEqual(codex_text_runtime.resolve_codex(), str(cli))
                os.environ['PATH'] = str(cli.parent / 'empty')
                with patch.object(sys, 'platform', 'darwin'), \
                        patch.object(Path, 'is_file', autospec=True, side_effect=lambda p: str(p) == bundle), \
                        patch.object(os, 'access', return_value=True):
                    self.assertEqual(codex_text_runtime.resolve_codex(), bundle)
                os.environ['PANELIZE_CODEX'] = str(cli)
                self.assertEqual(codex_text_runtime.resolve_codex(), str(cli))
                os.environ['PANELIZE_CODEX'] = str(cli.parent / 'unavailable')
                with self.assertRaisesRegex(RuntimeError, 'PANELIZE_CODEX'):
                    codex_text_runtime.resolve_codex()

    def test_input_and_independent_failure(self):
        text = '第一行\n$(touch BAD) <script>one</script>'
        seen = {}
        def adapter(target,q,opts,work):
            seen[target] = q
            if target == 'doubao':
                raise TimeoutError('missing receipt')
            return q, {'source':'fixture'}
        with tempfile.TemporaryDirectory() as out, patch.object(compare,'call',adapter), patch.object(
            sys, 'argv',['compare','--query',text,'--out',out,'--targets','deepseek,doubao']):
            self.assertEqual(compare.main(),1)
            run, = Path(out).iterdir()
            rows = json.loads((run/'results.json').read_text())
            self.assertEqual([r['status'] for r in rows],['completed','failed'])
            self.assertEqual(seen,dict(deepseek=text,doubao=text))
            self.assertEqual((run/'deepseek.md').read_text(),text)
            self.assertNotIn('<script>',(run/'index.html').read_text())
            self.assertFalse((run/'doubao.md').exists())

    def test_native_message_boundaries(self):
        raw = io.BytesIO()
        for v in [{'query':'豆包\nabc'}, {'id':'another'}]: native_host.send(raw,v)
        raw.seek(0)
        self.assertEqual(native_host.receive(raw)['query'],'豆包\nabc')
        self.assertEqual(native_host.receive(raw)['id'],'another')
        with self.assertRaises(EOFError): native_host.receive(raw)

    def test_dsh_incomplete_turn(self):
        options = argparse.Namespace(deepseek_model='deepseek-flash',timeout=10)
        with tempfile.TemporaryDirectory() as tmp, patch.object(compare,'private_key',return_value='dummy'), patch.object(
            compare,'run_process',return_value='{"type":"final","reason":{"kind":"error"},"text":"partial"}'):
            with self.assertRaises(ValueError): compare.call('deepseek','query',options,Path(tmp))

if __name__ == '__main__':
    unittest.main()
