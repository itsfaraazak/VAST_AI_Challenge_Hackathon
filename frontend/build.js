// Bridge to https://hexi.wokwi.com/build - Wokwi's public Arduino compiler.
// Used to turn `sketch.ino` (source) into `sketch.hex` (firmware) because the
// experimental embed expects compiled firmware, not source.

const HEXI = 'https://hexi.wokwi.com/build';

// Map a Wokwi diagram.json board type to the hexi `board` parameter.
// Only AVR boards are compiled by hexi today; ESP32 / Pi Pico Arduino projects
// would need a different builder, which we don't ship - those should use the
// MicroPython path instead.
const AVR_BOARDS = {
  'wokwi-arduino-uno':       'uno',
  'wokwi-arduino-mega':      'mega',
  'wokwi-arduino-nano':      'nano',
  'wokwi-attiny85':          'attiny85',
};

export function detectAvrBoard(diagramJsonText) {
  try {
    const d = JSON.parse(diagramJsonText);
    for (const part of d.parts || []) {
      if (AVR_BOARDS[part.type]) return AVR_BOARDS[part.type];
    }
  } catch {}
  return null;
}

// Returns { hex, stdout, stderr } - throws on network failure.
export async function buildArduinoHex(sketch, board) {
  const res = await fetch(HEXI, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sketch, board }),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`hexi.wokwi.com HTTP ${res.status}: ${t.slice(0, 400)}`);
  }
  const data = await res.json();
  if (!data.hex) {
    throw new Error(data.stderr || data.stdout || 'compile failed (no hex returned)');
  }
  return data;
}
