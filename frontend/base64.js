// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2025 CodeMagic LTD
const b64dict = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

export function base64ToByteArray(s) {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

export function byteArrayToBase64(buf) {
  let r = '';
  for (let i = 0; i < buf.length - 2; i += 3) {
    r += b64dict[buf[i] >> 2];
    r += b64dict[((buf[i] & 0x03) << 4) | (buf[i + 1] >> 4)];
    r += b64dict[((buf[i + 1] & 0x0f) << 2) | (buf[i + 2] >> 6)];
    r += b64dict[buf[i + 2] & 0x3f];
  }
  if (buf.length % 3 === 1) {
    r += b64dict[buf[buf.length - 1] >> 2];
    r += b64dict[(buf[buf.length - 1] & 0x03) << 4];
    r += '==';
  }
  if (buf.length % 3 === 2) {
    r += b64dict[buf[buf.length - 2] >> 2];
    r += b64dict[((buf[buf.length - 2] & 0x03) << 4) | (buf[buf.length - 1] >> 4)];
    r += b64dict[(buf[buf.length - 1] & 0x0f) << 2];
    r += '=';
  }
  return r;
}
