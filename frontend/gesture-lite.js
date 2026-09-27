const video = document.querySelector("#camera");
const overlay = document.querySelector("#overlay");
const context = overlay.getContext("2d");
const cameraSelect = document.querySelector("#camera-select");
const startButton = document.querySelector("#start");
const stopButton = document.querySelector("#stop");
const mirror = document.querySelector("#mirror");
const frame = document.querySelector("#camera-frame");
const placeholder = document.querySelector("#placeholder");
const engineState = document.querySelector("#engine-state");
const gestureIcon = document.querySelector("#gesture-icon");
const gestureName = document.querySelector("#gesture-name");
const gestureAction = document.querySelector("#gesture-action");
const confidenceLabel = document.querySelector("#confidence");
const progressBar = document.querySelector("#progress-bar");
const hint = document.querySelector("#hint");

const gestures = {
  Open_Palm: { icon: "✋", name: "张开手掌", action: "急停", frames: 3 },
  Thumb_Up: { icon: "👍", name: "点赞", action: "张开夹爪", frames: 6 },
  Closed_Fist: { icon: "✊", name: "握拳", action: "闭合夹爪", frames: 6 },
};
const connections = [
  [0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],
  [5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],
  [13,17],[17,18],[18,19],[19,20],[0,17],
];

let recognizer;
let stream;
let animationFrame;
let lastVideoTime = -1;
let currentGesture = null;
let stableFrames = 0;
let latched = false;

function setEngineState(text, className = "idle") {
  engineState.textContent = text;
  engineState.className = `status ${className}`;
}

function updateMirror() {
  frame.classList.toggle("mirrored", mirror.checked);
}

async function listCameras() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const selected = cameraSelect.value;
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === "videoinput");
  cameraSelect.replaceChildren(new Option("默认摄像头", ""));
  devices.forEach((device, index) => cameraSelect.add(new Option(device.label || `摄像头 ${index + 1}`, device.deviceId)));
  if ([...cameraSelect.options].some(option => option.value === selected)) cameraSelect.value = selected;
}

async function loadRecognizer() {
  if (recognizer) return;
  setEngineState("模型加载中");
  const { FilesetResolver, GestureRecognizer } = await import("./vendor/mediapipe/vision_bundle.mjs");
  const vision = await FilesetResolver.forVisionTasks("./vendor/mediapipe/wasm");
  recognizer = await GestureRecognizer.createFromOptions(vision, {
    baseOptions: { modelAssetPath: "./vendor/mediapipe/gesture_recognizer.task" },
    runningMode: "VIDEO",
    numHands: 1,
    cannedGesturesClassifierOptions: {
      categoryAllowlist: Object.keys(gestures),
      scoreThreshold: 0.65,
      maxResults: 1,
    },
  });
}

function drawHand(hand) {
  context.clearRect(0, 0, overlay.width, overlay.height);
  if (!hand) return;
  context.lineWidth = 3;
  context.strokeStyle = "#42e2c0";
  connections.forEach(([start, end]) => {
    context.beginPath();
    context.moveTo(hand[start].x * overlay.width, hand[start].y * overlay.height);
    context.lineTo(hand[end].x * overlay.width, hand[end].y * overlay.height);
    context.stroke();
  });
  context.fillStyle = "#f4fffd";
  hand.forEach(point => {
    context.beginPath();
    context.arc(point.x * overlay.width, point.y * overlay.height, 4, 0, Math.PI * 2);
    context.fill();
  });
}

function showResult(name, confidence) {
  const definition = gestures[name];
  document.querySelectorAll("[data-gesture]").forEach(card => card.classList.toggle("active", card.dataset.gesture === name));
  confidenceLabel.textContent = `${Math.round(confidence * 100)}%`;

  if (!definition) {
    currentGesture = null;
    stableFrames = 0;
    latched = false;
    gestureIcon.textContent = "—";
    gestureName.textContent = "未检测到目标手势";
    gestureAction.textContent = "尚未触发";
    progressBar.style.width = "0";
    return;
  }

  if (!latched) {
    stableFrames = currentGesture === name ? stableFrames + 1 : 1;
    currentGesture = name;
    if (stableFrames >= definition.frames) {
      latched = true;
      hint.textContent = `已识别：${definition.action}。当前仅预览，没有向机械臂发送命令。`;
    }
  }

  gestureIcon.textContent = definition.icon;
  gestureName.textContent = definition.name;
  gestureAction.textContent = latched ? `${definition.action} · 已锁存` : `${definition.action} · 稳定中`;
  progressBar.style.width = `${Math.min(100, stableFrames / definition.frames * 100)}%`;
}

function recognizeFrame() {
  if (!stream || !recognizer) return;
  if (video.readyState >= 2 && video.currentTime !== lastVideoTime) {
    lastVideoTime = video.currentTime;
    const result = recognizer.recognizeForVideo(video, performance.now());
    const category = result.gestures?.[0]?.[0];
    const name = gestures[category?.categoryName] ? category.categoryName : null;
    showResult(name, name ? category.score : 0);
    drawHand(result.landmarks?.[0]);
  }
  animationFrame = requestAnimationFrame(recognizeFrame);
}

async function startCamera() {
  startButton.disabled = true;
  try {
    await loadRecognizer();
    const deviceId = cameraSelect.value;
    stream = await navigator.mediaDevices.getUserMedia({
      video: deviceId ? { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } } : { width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    video.srcObject = stream;
    await video.play();
    await listCameras();
    placeholder.hidden = true;
    stopButton.disabled = false;
    setEngineState("识别中", "live");
    hint.textContent = "手势需连续稳定出现，放下手后才能再次触发。";
    recognizeFrame();
  } catch (error) {
    startButton.disabled = false;
    setEngineState("摄像头不可用", "error");
    hint.textContent = `启动失败：${error.message}`;
  }
}

function stopCamera() {
  cancelAnimationFrame(animationFrame);
  stream?.getTracks().forEach(track => track.stop());
  stream = undefined;
  video.srcObject = null;
  context.clearRect(0, 0, overlay.width, overlay.height);
  placeholder.hidden = false;
  startButton.disabled = false;
  stopButton.disabled = true;
  showResult(null, 0);
  setEngineState("待机");
}

startButton.addEventListener("click", startCamera);
stopButton.addEventListener("click", stopCamera);
mirror.addEventListener("change", updateMirror);
cameraSelect.addEventListener("change", () => { if (stream) { stopCamera(); startCamera(); } });
updateMirror();
listCameras().catch(() => {});
