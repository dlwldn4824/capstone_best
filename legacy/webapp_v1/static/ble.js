// 블루투스 심박 센서 (표준 Heart Rate Service 0x180D).
// Polar H10 · Verity Sense, 심박 '방송' 을 켠 Galaxy Watch / Garmin 등 표준 프로필을 쓰는 기기.
// Web Bluetooth 는 안드로이드 Chrome · 데스크톱 Chrome/Edge 에서만, https 또는 localhost 에서만 된다.
// (iOS Safari 는 지원하지 않는다.)
"use strict";

const BLE = (() => {
  let device = null;
  const listeners = new Set();

  function supported() {
    return !!(navigator.bluetooth && window.isSecureContext);
  }

  // Heart Rate Measurement 해석 (Bluetooth SIG 규격)
  function parse(view) {
    const flags = view.getUint8(0);
    let i = 1;
    const wide = flags & 0x01;
    const bpm = wide ? view.getUint16(i, true) : view.getUint8(i);
    i += wide ? 2 : 1;
    if (flags & 0x08) i += 2;                     // 소모 에너지
    const rr = [];
    if (flags & 0x10) {
      for (; i + 1 < view.byteLength; i += 2) rr.push(view.getUint16(i, true) / 1024);
    }
    return { bpm, rr };
  }

  async function connect() {
    if (!supported()) throw new Error("이 브라우저에서는 블루투스를 쓸 수 없어요 (안드로이드 Chrome + https 필요)");
    device = await navigator.bluetooth.requestDevice({ filters: [{ services: ["heart_rate"] }] });
    const server = await device.gatt.connect();
    const svc = await server.getPrimaryService("heart_rate");
    const ch = await svc.getCharacteristic("heart_rate_measurement");
    await ch.startNotifications();
    ch.addEventListener("characteristicvaluechanged", (e) => {
      const m = parse(e.target.value);
      m.at = Date.now();
      m.device = device.name || "심박 센서";
      listeners.forEach((fn) => fn(m));
    });
    device.addEventListener("gattserverdisconnected", () => listeners.forEach((fn) => fn(null)));
    return device.name || "심박 센서";
  }

  function disconnect() {
    if (device && device.gatt.connected) device.gatt.disconnect();
  }

  return { supported, connect, disconnect, onBeat: (fn) => listeners.add(fn), parse };
})();
