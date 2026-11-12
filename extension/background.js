// Clicking the toolbar button opens the side panel. The extension reads no web pages:
// it has no content scripts and no access to any site except the local advisor.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(console.error);
