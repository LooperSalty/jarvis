let stream: MediaStream | null = null;

export async function enableScreenCapture(): Promise<boolean> {
  if (stream) return true;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: 1 },
      audio: false,
    });
    stream.getVideoTracks()[0].addEventListener("ended", () => {
      stream = null;
      console.warn("[VISION] Partage d'écran arrêté par l'utilisateur");
    });
    console.log("[VISION] Capture d'écran activée");
    return true;
  } catch (e) {
    console.error("[VISION] Refusé:", e);
    return false;
  }
}

export async function captureFrame(): Promise<string | null> {
  if (!stream) {
    console.warn("[VISION] Pas de stream — clique sur 'Activer la vision'");
    return null;
  }
  const track = stream.getVideoTracks()[0];
  const ic: any = (window as any).ImageCapture;
  let bitmap: ImageBitmap;
  if (ic) {
    bitmap = await new ic(track).grabFrame();
  } else {
    const video = document.createElement("video");
    video.srcObject = stream;
    await video.play();
    bitmap = await createImageBitmap(video);
    video.pause();
  }

  const maxW = 1280;
  const ratio = bitmap.width > maxW ? maxW / bitmap.width : 1;
  const w = Math.round(bitmap.width * ratio);
  const h = Math.round(bitmap.height * ratio);

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(bitmap, 0, 0, w, h);
  
  return canvas.toDataURL("image/jpeg", 0.8).split(",")[1];
}

export function injectVisionButton() {
  const btn = document.createElement("button");
  btn.id = "vision-button";
  btn.textContent = "👁️ Activer la vision";
  btn.style.cssText =
    "position:fixed;top:64px;right:16px;z-index:9999;padding:8px 14px;" +
    "background:#4ca8e8;color:#fff;border:none;border-radius:6px;" +
    "font-family:sans-serif;cursor:pointer;font-size:13px;" +
    "box-shadow:0 4px 14px rgba(0,0,0,0.4);";
  btn.onclick = async () => {
    const ok = await enableScreenCapture();
    btn.textContent = ok ? "👁️ Vision active" : "❌ Vision refusée";
    btn.style.background = ok ? "#2ecc71" : "#e74c3c";
  };
  document.body.appendChild(btn);
}
