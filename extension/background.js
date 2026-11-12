// Clicking the toolbar button opens the side panel.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(console.error);

// Game frames from colonist.io tabs (see colonist_hook.js) go to the local advisor only.
const ADVISOR = "http://127.0.0.1:8765/api/capture";
chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== "frames" || !sender.tab) return;
  fetch(ADVISOR, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tab: sender.tab.id, page: message.page, frames: message.frames }),
  }).catch(() => {}); // the advisor is not running: nothing is kept
});
