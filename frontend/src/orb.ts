import * as THREE from "three";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

/** Palette de l'orbe : une couleur "#rrggbb" par etat (partielle acceptee). */
export type OrbPalette = Partial<Record<OrbState, string>>;

export interface Orb {
  setState(state: OrbState): void;
  setVolume(volume: number): void;
  triggerDemo(): void;
  /** Remplace la couleur d'un ou plusieurs etats (personnalisation). */
  setPalette(palette: OrbPalette): void;
}

const _HEX_RE = /^#[0-9a-fA-F]{6}$/;
const _STATES: OrbState[] = ["idle", "listening", "thinking", "speaking"];

const STATE_COLOR: Record<OrbState, THREE.Color> = {
  idle: new THREE.Color(0x4ca8e8),
  listening: new THREE.Color(0x6fd8ff),
  thinking: new THREE.Color(0xb066ff),
  speaking: new THREE.Color(0x66ffd1),
};

const ORBIT_COUNT = 28;
const POINTS_PER_ORBIT = 320;
const TOTAL_POINTS = ORBIT_COUNT * POINTS_PER_ORBIT;

function makeStarTexture(): THREE.Texture {
  const size = 64;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d") as CanvasRenderingContext2D;
  const cx = size / 2;
  const cy = size / 2;
  const img = ctx.createImageData(size, size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (x - cx) / cx;
      const dy = (y - cy) / cy;
      const r = Math.hypot(dx, dy);
      const core = Math.exp(-r * r * 5);
      const glow = Math.exp(-r * r * 1.4) * 0.35;
      const v = Math.min(1, core + glow);
      const i = (y * size + x) * 4;
      img.data[i] = 255;
      img.data[i + 1] = 255;
      img.data[i + 2] = 255;
      img.data[i + 3] = Math.round(v * 255);
    }
  }
  ctx.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeFlareTexture(): THREE.Texture {
  const size = 512;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d") as CanvasRenderingContext2D;
  const cx = size / 2;
  const cy = size / 2;
  const img = ctx.createImageData(size, size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (x - cx) / cx;
      const dy = (y - cy) / cy;
      const r = Math.hypot(dx, dy);
      const ax = Math.abs(dx);
      const ay = Math.abs(dy);

      const edgeFade = r < 0.7 ? 1 : Math.max(0, 1 - (r - 0.7) / 0.3);
      const edgeFadeSmooth = edgeFade * edgeFade * (3 - 2 * edgeFade);

      const rayH = Math.exp(-ay * 180) * Math.exp(-ax * 0.6);
      const rayV = Math.exp(-ax * 180) * Math.exp(-ay * 0.6);
      const rayDiag1 = Math.exp(-Math.abs(dx - dy) * 200) * Math.exp(-r * 1.4) * 0.45;
      const rayDiag2 = Math.exp(-Math.abs(dx + dy) * 200) * Math.exp(-r * 1.4) * 0.45;
      const core = Math.exp(-r * r * 90);
      const halo = Math.exp(-r * r * 18) * 0.25;

      const rays = (rayH + rayV) * 0.85 + (rayDiag1 + rayDiag2);
      const v = Math.min(1, (core * 1.4 + halo + rays * edgeFadeSmooth) * edgeFadeSmooth);

      const i = (y * size + x) * 4;
      img.data[i] = 255;
      img.data[i + 1] = 255;
      img.data[i + 2] = 255;
      img.data[i + 3] = Math.round(v * 255);
    }
  }
  ctx.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

function randomOrthogonalBasis(): { u: THREE.Vector3; v: THREE.Vector3 } {
  const u = new THREE.Vector3(
    Math.random() * 2 - 1,
    Math.random() * 2 - 1,
    Math.random() * 2 - 1,
  ).normalize();
  let v = new THREE.Vector3(
    Math.random() * 2 - 1,
    Math.random() * 2 - 1,
    Math.random() * 2 - 1,
  );
  v.sub(u.clone().multiplyScalar(v.dot(u))).normalize();
  return { u, v };
}

const particleVertex = `
  attribute float aSize;
  attribute float aBrightness;

  uniform float uVolume;
  uniform float uPulse;
  uniform float uPixelRatio;

  varying float vBrightness;

  void main() {
    float scale = 1.0 + uPulse * 0.05 + uVolume * 0.35;
    vec3 p = position * scale;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = aSize * uPixelRatio * (1.0 + uVolume * 0.4);
    vBrightness = aBrightness * (0.7 + uVolume * 0.6 + uPulse * 0.15);
  }
`;

const particleFragment = `
  uniform sampler2D uTex;
  uniform vec3 uColor;
  varying float vBrightness;

  void main() {
    vec4 t = texture2D(uTex, gl_PointCoord);
    if (t.a < 0.05) discard;
    vec3 col = uColor * vBrightness;
    gl_FragColor = vec4(col, t.a * vBrightness);
  }
`;

const coreVertex = `
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vNormal = normalize(normalMatrix * normal);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;

const coreFragment = `
  uniform vec3 uColor;
  uniform float uIntensity;
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    float fr = pow(1.0 - max(dot(vNormal, vView), 0.0), 2.0);
    vec3 col = mix(vec3(1.0), uColor, fr);
    gl_FragColor = vec4(col, (0.85 + fr * 0.15) * uIntensity);
  }
`;

const haloFragment = `
  uniform vec3 uColor;
  uniform float uIntensity;
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    float fr = pow(1.0 - max(dot(vNormal, vView), 0.0), 4.5);
    gl_FragColor = vec4(uColor, fr * uIntensity);
  }
`;

export function createOrb(canvas: HTMLCanvasElement): Orb {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    premultipliedAlpha: false,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 0, 2.6);

  const group = new THREE.Group();
  scene.add(group);

  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(TOTAL_POINTS * 3);
  const sizes = new Float32Array(TOTAL_POINTS);
  const brights = new Float32Array(TOTAL_POINTS);

  function rand(min: number, max: number): number {
    return min + Math.random() * (max - min);
  }

  for (let o = 0; o < ORBIT_COUNT; o++) {
    const { u, v } = randomOrthogonalBasis();
    const harmonics = [
      [1, 1],
      [2, 3],
      [3, 2],
      [3, 4],
      [5, 4],
      [3, 5],
      [1, 2],
      [2, 5],
      [4, 5],
    ];
    const [n1, n2] = harmonics[Math.floor(Math.random() * harmonics.length)];
    const radius = rand(0.6, 1.5);
    const phaseOffset = rand(0, Math.PI * 2);

    for (let p = 0; p < POINTS_PER_ORBIT; p++) {
      const i = o * POINTS_PER_ORBIT + p;
      const t = (p / POINTS_PER_ORBIT) * Math.PI * 2;

      const cx = Math.cos(n1 * t + phaseOffset);
      const sy = Math.sin(n2 * t + phaseOffset * 0.7);

      const px = (u.x * cx + v.x * sy) * radius;
      const py = (u.y * cx + v.y * sy) * radius;
      const pz = (u.z * cx + v.z * sy) * radius;

      positions[i * 3 + 0] = px + rand(-0.01, 0.01);
      positions[i * 3 + 1] = py + rand(-0.01, 0.01);
      positions[i * 3 + 2] = pz + rand(-0.01, 0.01);

      sizes[i] = rand(4, 8);
      brights[i] = rand(0.55, 1.0);
    }
  }

  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
  geometry.setAttribute("aBrightness", new THREE.BufferAttribute(brights, 1));

  const particleUniforms = {
    uVolume: { value: 0 },
    uPulse: { value: 0 },
    uPixelRatio: { value: renderer.getPixelRatio() },
    uColor: { value: STATE_COLOR.idle.clone() },
    uTex: { value: makeStarTexture() },
  };

  const particleMat = new THREE.ShaderMaterial({
    uniforms: particleUniforms,
    vertexShader: particleVertex,
    fragmentShader: particleFragment,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });

  const particles = new THREE.Points(geometry, particleMat);
  group.add(particles);

  // Boule centrale et rayons retires (demande utilisateur).
  // makeFlareTexture reste defini mais inutilise.
  void makeFlareTexture;

  // Palette MUTABLE (copie des couleurs par defaut) : setPalette la remplace
  // pour la personnalisation. On garde l'etat courant pour re-cibler la couleur
  // immediatement quand la palette change.
  const palette: Record<OrbState, THREE.Color> = {
    idle: STATE_COLOR.idle.clone(),
    listening: STATE_COLOR.listening.clone(),
    thinking: STATE_COLOR.thinking.clone(),
    speaking: STATE_COLOR.speaking.clone(),
  };
  let currentState: OrbState = "idle";

  const targetColor = palette.idle.clone();
  let targetSpinY = 0.12;
  let targetSpinX = 0.04;
  let targetCoreIntensity = 0.85;
  let targetHalo = 0.45;
  let demoUntil = 0;
  let displayedVolume = 0;
  let targetVolume = 0;

  function setState(state: OrbState): void {
    currentState = state;
    targetColor.copy(palette[state]);
    switch (state) {
      case "idle":
        targetSpinY = 0.1;
        targetSpinX = 0.04;
        targetCoreIntensity = 0.8;
        targetHalo = 0.4;
        break;
      case "listening":
        targetSpinY = 0.25;
        targetSpinX = 0.08;
        targetCoreIntensity = 1.0;
        targetHalo = 0.55;
        break;
      case "thinking":
        targetSpinY = 0.7;
        targetSpinX = 0.2;
        targetCoreIntensity = 1.05;
        targetHalo = 0.5;
        break;
      case "speaking":
        targetSpinY = 0.35;
        targetSpinX = 0.1;
        targetCoreIntensity = 1.2;
        targetHalo = 0.65;
        break;
    }
  }

  function setVolume(v: number): void {
    targetVolume = Math.max(0, Math.min(1, v));
  }

  function triggerDemo(): void {
    demoUntil = performance.now() + 2500;
  }

  function setPalette(p: OrbPalette): void {
    for (const state of _STATES) {
      const hex = p[state];
      if (typeof hex === "string" && _HEX_RE.test(hex)) {
        palette[state].set(hex);
      }
    }
    // Re-cible la couleur de l'etat courant : l'animation lerp en douceur.
    targetColor.copy(palette[currentState]);
  }

  function resize(): void {
    const w = window.innerWidth;
    const h = window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    particleUniforms.uPixelRatio.value = renderer.getPixelRatio();
  }
  resize();
  window.addEventListener("resize", resize);

  const clock = new THREE.Clock();
  let spinY = 0.12;
  let spinX = 0.04;

  function tick(): void {
    const dt = Math.min(0.05, clock.getDelta());
    const elapsed = clock.getElapsedTime();

    displayedVolume += (targetVolume - displayedVolume) * Math.min(1, dt * 8);
    particleUniforms.uVolume.value = displayedVolume;

    const isDemo = performance.now() < demoUntil;
    const pulseTarget =
      0.5 + 0.5 * Math.sin(elapsed * 1.6) + displayedVolume * 0.6 + (isDemo ? 0.6 : 0);
    particleUniforms.uPulse.value +=
      (pulseTarget - particleUniforms.uPulse.value) * Math.min(1, dt * 6);

    const sy = isDemo ? 1.6 : targetSpinY;
    const sx = isDemo ? 0.5 : targetSpinX;
    spinY += (sy - spinY) * Math.min(1, dt * 3);
    spinX += (sx - spinX) * Math.min(1, dt * 3);

    particleUniforms.uColor.value.lerp(targetColor, Math.min(1, dt * 4));

    void targetCoreIntensity;
    void targetHalo;

    group.rotation.y += dt * spinY;
    group.rotation.x += dt * spinX;

    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  tick();

  return { setState, setVolume, triggerDemo, setPalette };
}
