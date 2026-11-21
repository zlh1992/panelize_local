"""Optional DOM regression in Chromium. No provider accounts or requests."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

p=argparse.ArgumentParser()
p.add_argument('--executable')
args=p.parse_args()
ext=Path(__file__).resolve().parents[1]/'extension'
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=args.executable)
    page=browser.new_page()
    page.set_content('<div id="input-engine-container"><textarea></textarea><button id="flow-end-msg-send">发送</button></div>')
    page.evaluate("""() => {window.chrome={runtime:{id:'fixture',onMessage:{addListener:f=>window.dispatchJob=f}}};
      document.querySelector('button').onclick=()=>{
        const user=document.createElement('div');user.dataset.testid='send_message';
        user.textContent=document.querySelector('textarea').value;document.body.append(user);
        const reply=document.createElement('div');reply.dataset.testid='receive_message';
        reply.innerHTML='<div data-testid="message_text_content">partial</div><button aria-label="停止"></button>';
        document.body.append(reply);
        setTimeout(()=>{reply.firstChild.textContent='已完成';reply.lastChild.setAttribute('aria-label','复制')},1800);
      };}""")
    for name in ['vendor/button-finder-utils.js','vendor/doubao-input.js','doubao.js']:
        page.add_script_tag(path=str(ext/name))
    ask="""q=>new Promise(resolve=>window.dispatchJob({type:'ask',query:q,deadline:Date.now()+8000},{id:'fixture'},resolve))"""
    result=page.evaluate(ask,'第一行\n第二行')
    assert result.get('answer')=='已完成',result
    result=page.evaluate(ask,'another')
    assert 'error' in result and 'answer' not in result,result
    print('PASS: current turn, streaming completion, existing draft/conversation guard')
    browser.close()
