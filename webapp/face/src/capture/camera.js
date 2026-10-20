// 전면 카메라 640×480 30fps. iOS Safari는 사용자 탭 안에서만 getUserMedia가 허용된다.
export async function openCamera(videoEl) {
  const constraints = {
    audio: false,
    video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30, max: 30 } },
  };
  const stream = await navigator.mediaDevices.getUserMedia(constraints);
  videoEl.srcObject = stream;
  videoEl.setAttribute('playsinline', '');   // iOS 전체화면 방지
  videoEl.muted = true;
  await videoEl.play();
  const track = stream.getVideoTracks()[0];
  const settings = track.getSettings();
  return { stream, track, width: settings.width || 640, height: settings.height || 480, fps: settings.frameRate || 30 };
}

export function closeCamera(videoEl) {
  const s = videoEl.srcObject;
  if (s) for (const t of s.getTracks()) t.stop();
  videoEl.srcObject = null;
}

// 지원되면 노출·화이트밸런스 고정을 시도한다. iOS Safari는 대부분 거부하므로 결과만 기록.
export async function tryLockExposure(track) {
  const caps = track.getCapabilities ? track.getCapabilities() : {};
  const adv = [];
  if (caps.exposureMode && caps.exposureMode.includes('manual')) adv.push({ exposureMode: 'manual' });
  if (caps.whiteBalanceMode && caps.whiteBalanceMode.includes('manual')) adv.push({ whiteBalanceMode: 'manual' });
  if (!adv.length) return { locked: false, reason: 'unsupported' };
  try { await track.applyConstraints({ advanced: adv }); return { locked: true }; }
  catch (e) { return { locked: false, reason: String(e) }; }
}
