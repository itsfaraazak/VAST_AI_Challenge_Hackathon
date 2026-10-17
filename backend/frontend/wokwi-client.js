/**
 * Minimal Wokwi experimental embed client (MessagePort protocol).
 * Based on wokwi/wokwi-embed-example patterns.
 */

export class WokwiClient {
  constructor(iframe) {
    this.iframe = iframe;
    this.port = null;
    this._ready = new Promise((resolve) => {
      this._resolveReady = resolve;
    });
    window.addEventListener("message", (event) => this._onMessage(event));
  }

  _onMessage(event) {
    if (event.source !== this.iframe.contentWindow) return;
    if (event.data && event.data.command === "port") {
      this.port = event.ports[0];
      this.port.onmessage = () => {};
      if (this._resolveReady) {
        this._resolveReady();
        this._resolveReady = null;
      }
    }
  }

  async ready(timeoutMs = 15000) {
    const timer = new Promise((_, reject) => {
      setTimeout(() => reject(new Error("Wokwi embed timed out")), timeoutMs);
    });
    await Promise.race([this._ready, timer]);
  }

  _send(command, payload = {}) {
    if (!this.port) throw new Error("Wokwi port not ready");
    this.port.postMessage({ command, ...payload });
  }

  async uploadFiles(files) {
    await this.ready();
    for (const [name, content] of Object.entries(files || {})) {
      const encoded =
        typeof content === "string"
          ? btoa(unescape(encodeURIComponent(content)))
          : content;
      this._send("file:upload", { name, content: encoded });
    }
  }

  async start(firmware = "sketch.ino", elf = "sketch.ino") {
    await this.ready();
    this._send("sim:start", { firmware, elf });
  }
}
