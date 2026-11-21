let port;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function compare(job) {
  const tab = await chrome.tabs.create({url: 'https://www.doubao.com/chat/', active: false});
  for (let i = 0; i < 100 && Date.now() < job.deadline; i++) {
    let ready;
    try { ready = await chrome.tabs.sendMessage(tab.id, {type: 'ready'}); }
    catch { /* The new tab has not registered its content script. */ }
    if (ready) {
      // Dispatch once. A lost response may mean the site already accepted the prompt.
      return await chrome.tabs.sendMessage(tab.id, {...job, type: 'ask'});
    }
    await sleep(250);
  }
  throw new Error('豆包新标签页未就绪，请检查网络和当前 Chrome profile');
}

function connect() {
  if (port) return;
  const channel = chrome.runtime.connectNative('local.panelize.compare');
  port = channel;
  channel.onDisconnect.addListener(() => {
    void chrome.runtime.lastError;
    if (port === channel) port = undefined;
  });
  channel.onMessage.addListener(async job => {
    try {
      const result = await compare(job);
      channel.postMessage({id: job.id, ...result});
    } catch (error) {
      try { channel.postMessage({id: job.id, error: String(error.message || error)}); } catch {}
    }
  });
}
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('connect', {periodInMinutes: 1});
  connect();
});
chrome.runtime.onStartup.addListener(connect);
chrome.action.onClicked.addListener(connect);
chrome.alarms.onAlarm.addListener(connect);
connect();
