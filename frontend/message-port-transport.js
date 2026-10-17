export class MessagePortTransport {
  constructor(port) {
    this.port = port;
    this.port.onmessage = (event) => { this.onMessage(event.data); };
    this.onMessage = () => {};
    this.port.start();
  }
  send(message) { this.port.postMessage(message); }
}
