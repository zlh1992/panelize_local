// Each request gets a fresh tab. Match the user's actual turn before accepting a reply.
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const visible = el => el && el.getClientRects().length > 0;
const findVisible = selectors => selectors.flatMap(s => [...document.querySelectorAll(s)]).find(visible);
const norm = text => (text || '').replace(/\s+/g, ' ').trim();
const promptRows = '[data-testid="send_message"],[data-message-author-role="user"]';
const replyRows = '[data-testid="receive_message"],[data-message-author-role="assistant"]';

function currentAnswer(query) {
  const row = [...document.querySelectorAll(promptRows)].find(el =>
    visible(el) && [el, ...el.querySelectorAll('[data-testid="message_text_content"], [class*="markdown"]')].some(n => norm(n.innerText) === norm(query)));
  if (!row) return null;
  const reply = [...document.querySelectorAll(replyRows)].find(el =>
    visible(el) && (row.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING));
  if (!reply) return null;
  const body = reply.querySelector('[data-testid="message_text_content"]') || reply.querySelector('[class*="flow-markdown"],[class*="markdown-body"]');
  const container = reply.closest('[data-testid="union_message"]') || reply;
  const copy = [...container.querySelectorAll('button,[role="button"],[data-testid]')].some(el =>
    /copy|复制/i.test([el.dataset.testid, el.title, el.getAttribute('aria-label')].join(' ')));
  return {text: body?.innerText?.trim(), copy};
}

async function ask({query, deadline}) {
  if (Date.now() >= deadline) throw new Error('任务已过期');
  let input;
  while (!(input = findVisible(['[data-testid="chat_input_input"]:is(textarea,[contenteditable="true"])',...doubaoInputs])) && Date.now() < Math.min(deadline, started + 20000)) await delay(300);
  if (!input) throw new Error('未找到输入框，请在此 Chrome profile 登录豆包');
  if (document.querySelector(promptRows) || norm(input.value || input.innerText))
    throw new Error('新会话已有消息或草稿，请检查新标签页');
  if (!injectTextIntoElement(input, query, 'doubao')) throw new Error('填充失败');
  let send;
  for (let i = 0; i < 30 && Date.now() < deadline; i++) {
    send = findVisible(['#flow-end-msg-send','button[data-testid="send-button"]','[data-testid="chat_input_send_button"]']) ||
      window.ButtonFinderUtils.findButton([{type:'aria',textKey:'send'},{type:'text',textKey:'send'}]);
    if (visible(send) && !send.disabled && send.getAttribute('aria-disabled') !== 'true') break;
    send = null;
    await delay(150);
  }
  if (!send || Date.now() >= deadline || norm(input.value || input.innerText) !== norm(query)) throw new Error('未确认填充内容或发送按钮');
  send.click();
  let last = '', changed = 0, sawBusy = false;
  while (Date.now() < deadline) {
    const busy = !!findVisible(['[data-testid="chat_input_stop_button"]','button[aria-label*="停止"]','button[aria-label*="Stop"]','#flow-end-msg-stop']);
    sawBusy ||= busy;
    const reply = currentAnswer(query);
    if (last !== (reply?.text || '')) { last = reply?.text || ''; changed = Date.now(); }
    if (last && !busy && (reply.copy || sawBusy) && Date.now() - changed >= 1800)
      return {answer:last, source:location.href};
    await delay(350);
  }
  throw new Error('已尝试发送，未观察到本轮完成信号；请检查保留的标签页');
}
const started = Date.now();
chrome.runtime.onMessage.addListener((job, sender, respond) => {
  if (sender.id !== chrome.runtime.id) return;
  if (job.type === 'ready') { respond(true); return; }
  if (job.type === 'ask') {
    ask(job).then(respond, e => respond({error:e.message,source:location.href}));
    return true;
  }
});
