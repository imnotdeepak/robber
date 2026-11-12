// Isolated-world relay: passes frames from colonist_hook.js to the background worker in
// small batches, which posts them to the advisor running on this computer.
(() => {
  let batch = [];
  let timer = null;
  const flush = () => {
    timer = null;
    if (!batch.length) return;
    const frames = batch;
    batch = [];
    chrome.runtime.sendMessage({ type: "frames", page: location.href, frames }).catch(() => {});
  };
  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data || event.data.__robber !== "frame") return;
    const { __robber, ...frame } = event.data;
    batch.push(frame);
    if (!timer) timer = setTimeout(flush, 250);
  });
})();
