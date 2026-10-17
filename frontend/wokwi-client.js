// Minimal Wokwi client - based on wokwi/wokwi-embed-example (MIT)
import { byteArrayToBase64, base64ToByteArray } from './base64.js';

export class WokwiClient extends EventTarget {
    lastId = 0;
    pendingCommands = new Map();

    constructor(transport) {
        super();
        this.transport = transport;
        this.transport.onMessage = (m) => this.processMessage(m);
    }

    async fileUpload(name, content) {
        if (typeof content === 'string') {
            return this.sendCommand('file:upload', { name, text: content });
        }
        return this.sendCommand('file:upload', { name, binary: byteArrayToBase64(content) });
    }

    async fileDownload(name) {
        const result = await this.sendCommand('file:download', { name });
        return typeof result.text === 'string' ? result.text : base64ToByteArray(result.binary);
    }

    simStart(params) { return this.sendCommand('sim:start', params); }
    simPause() { return this.sendCommand('sim:pause'); }
    simResume(pauseAfter) { return this.sendCommand('sim:resume', { pauseAfter }); }
    simRestart(opts = {}) { return this.sendCommand('sim:restart', { pause: opts.pause }); }
    simStatus() { return this.sendCommand('sim:status'); }
    serialMonitorListen() { return this.sendCommand('serial-monitor:listen'); }
    serialMonitorWrite(bytes) {
        return this.sendCommand('serial-monitor:write', { bytes: Array.from(bytes) });
    }
    gpioList() { return this.sendCommand('gpio:list'); }
    gpioWrite(pin, value) { return this.sendCommand('gpio:write', { pin, value }); }
    pinRead(part, pin) { return this.sendCommand('pin:read', { part, pin }); }

    sendCommand(command, params) {
        return new Promise((resolve, reject) => {
            const id = (this.lastId++).toString();
            this.pendingCommands.set(id, [resolve, reject]);
            this.transport.send({ type: 'command', command, params, id });
        });
    }

    processMessage(m) {
        if (m.type === 'hello') {
            this.dispatchEvent(new CustomEvent('wokwi:connected', { detail: m }));
        } else if (m.type === 'event') {
            this.dispatchEvent(new CustomEvent(m.event, { detail: m.payload }));
        } else if (m.type === 'response') {
            const id = m.id ?? '';
            const handlers = this.pendingCommands.get(id);
            if (!handlers) return console.error('Unknown response', m);
            const [resolve, reject] = handlers;
            this.pendingCommands.delete(id);
            if (m.error) {
                const r = m.result || {};
                reject(new Error(`Error ${r.code}: ${r.message}`));
            } else {
                resolve(m.result);
            }
        }
    }
}
