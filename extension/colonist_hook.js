// Runs inside colonist.io pages (main world), with the user's written permission from
// colonist.io to read the state of their own games. Copies every WebSocket message the
// page sends or receives, decoded from MessagePack, to the relay script by postMessage.
// It never sends anything to colonist.io and never changes a message.
(() => {
  const Native = window.WebSocket;
  if (!Native || Native.__robber) return;

  function forward(direction, url, data) {
    const time = Date.now();
    const send = (body) => window.postMessage({ __robber: "frame", direction, url, time, ...body }, window.location.origin);
    const decode = (bytes) => {
      try { send({ messages: self.RobberMsgpack.decodeAll(bytes) }); }
      catch (error) { send({ error: String(error), raw: Array.from(bytes) }); }
    };
    if (typeof data === "string") {
      try { send({ messages: [JSON.parse(data)] }); } catch { send({ text: data }); }
    } else if (data instanceof ArrayBuffer) decode(new Uint8Array(data));
    else if (ArrayBuffer.isView(data)) decode(new Uint8Array(data.buffer, data.byteOffset, data.byteLength));
    else if (data instanceof Blob) data.arrayBuffer().then((b) => decode(new Uint8Array(b)));
  }

  class RobberSocket extends Native {
    constructor(...args) {
      super(...args);
      this.addEventListener("message", (event) => forward("in", this.url, event.data));
    }
    send(data) {
      forward("out", this.url, data);
      return super.send(data);
    }
  }
  RobberSocket.__robber = true;
  window.WebSocket = RobberSocket;
})();
