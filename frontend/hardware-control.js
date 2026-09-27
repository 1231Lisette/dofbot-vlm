const image = document.querySelector("#camera-image");
const overlay = document.querySelector("#overlay");
const context = overlay.getContext("2d");
const frame = document.querySelector("#camera-frame");
const placeholder = document.querySelector("#camera-placeholder");
const serverState = document.querySelector("#server-state");
const cameraState = document.querySelector("#camera-state");
const modelState = document.querySelector("#model-state");
const hardwareState = document.querySelector("#hardware-state");
const unlock = document.querySelector("#hardware-unlock");
const message = document.querySelector("#message");
const resumeButton = document.querySelector("#resume");

const gestures = {
  Thumb_Up: { icon:"👍", name:"点赞", action:"张开夹爪", frames:6, endpoint:"/api/gripper/open" },
  Closed_Fist: { icon:"✊", name:"握拳", action:"闭合夹爪", frames:6, endpoint:"/api/gripper/close" },
  Victory: { icon:"✌️", name:"V 手势", action:"上举并点头两次", frames:7, endpoint:null },
};
const connections = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];

let recognizer;
let status;
let running = true;
let currentGesture = null;
let stableFrames = 0;
let latched = false;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

function drawHand(hand) {
  context.clearRect(0,0,overlay.width,overlay.height);
  if (!hand) return;
  context.strokeStyle="#42e2c0"; context.fillStyle="#f2fffc"; context.lineWidth=3;
  connections.forEach(([a,b])=>{ context.beginPath(); context.moveTo(hand[a].x*overlay.width,hand[a].y*overlay.height); context.lineTo(hand[b].x*overlay.width,hand[b].y*overlay.height); context.stroke(); });
  hand.forEach(point=>{ context.beginPath(); context.arc(point.x*overlay.width,point.y*overlay.height,4,0,Math.PI*2); context.fill(); });
}

async function triggerGesture(definition) {
  if (!definition.endpoint) {
    const reason = status?.victory_pose?.reason || "动作尚未标定";
    message.textContent = `V 手势已识别，但已被安全锁阻止：${reason}`;
    return;
  }
  if (!unlock.checked) {
    message.textContent = `${definition.action}未发送：请先完成现场安全确认。`;
    return;
  }
  try {
    const result = await api(definition.endpoint, { method:"POST" });
    message.textContent = `${definition.action}命令已发送，目标 ${result.angle}°。`;
  } catch (error) {
    message.textContent = `动作被服务端阻止：${error.message}`;
  }
}

function showGesture(name, confidence) {
  const definition = gestures[name];
  document.querySelectorAll("[data-gesture]").forEach(card=>card.classList.toggle("active",card.dataset.gesture===name));
  document.querySelector("#confidence").textContent=`${Math.round(confidence*100)}%`;
  if (!definition) {
    currentGesture=null; stableFrames=0; latched=false;
    document.querySelector("#gesture-icon").textContent="—";
    document.querySelector("#gesture-name").textContent="等待手势";
    document.querySelector("#gesture-action").textContent="尚未触发";
    document.querySelector("#gesture-progress").style.width="0";
    return;
  }
  if (!latched) {
    stableFrames=currentGesture===name?stableFrames+1:1; currentGesture=name;
    if (stableFrames>=definition.frames) { latched=true; triggerGesture(definition); }
  }
  document.querySelector("#gesture-icon").textContent=definition.icon;
  document.querySelector("#gesture-name").textContent=definition.name;
  document.querySelector("#gesture-action").textContent=`${definition.action}${latched?" · 已锁存":" · 稳定中"}`;
  document.querySelector("#gesture-progress").style.width=`${Math.min(100,stableFrames/definition.frames*100)}%`;
}

async function cameraLoop() {
  while (running) {
    try {
      const response=await fetch(`/api/camera/frame.jpg?t=${Date.now()}`,{cache:"no-store"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob=await response.blob();
      const url=URL.createObjectURL(blob);
      image.src=url;
      await image.decode();
      placeholder.hidden=true; cameraState.textContent="LIVE";
      if (recognizer) {
        const result=recognizer.recognize(image);
        const category=result.gestures?.[0]?.[0];
        const name=gestures[category?.categoryName]?category.categoryName:null;
        showGesture(name,name?category.score:0);
        drawHand(result.landmarks?.[0]);
      }
      URL.revokeObjectURL(url);
    } catch (error) {
      cameraState.textContent="WAITING";
      await new Promise(resolve=>setTimeout(resolve,300));
    }
  }
}

function renderServos() {
  const root=document.querySelector("#servo-controls"); root.replaceChildren();
  Object.entries(status.servos).forEach(([id,item])=>{
    const article=document.createElement("article"); article.className=`servo-control${item.enabled?"":" locked"}`;
    const value=status.last_angles[id];
    article.innerHTML=`<div><strong>S${id} · ${item.name}</strong><small>${item.enabled?`${item.min}–${item.max}° 软限位`:"待标定 · 服务端锁定"}</small></div><input type="range" min="${item.min}" max="${item.max}" value="${value}" ${item.enabled?"":"disabled"}><output>${value}°</output><button ${item.enabled?"":"disabled"}>发送</button>`;
    const slider=article.querySelector("input"); const output=article.querySelector("output"); const button=article.querySelector("button");
    slider.addEventListener("input",()=>{output.value=`${slider.value}°`;});
    button.addEventListener("click",async()=>{
      if (!unlock.checked) { message.textContent="未发送：请先完成现场安全确认。"; return; }
      try { await api(`/api/servos/${id}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({angle:Number(slider.value),duration_ms:status.move_time_ms})}); message.textContent=`S${id} 已发送 ${slider.value}°。`; }
      catch(error){message.textContent=`S${id} 被阻止：${error.message}`;}
    });
    root.append(article);
  });
}

async function refreshStatus() {
  status=await api("/api/status");
  serverState.textContent=status.hardware_enabled?"JETSON · HARDWARE":"JETSON · CAMERA ONLY";
  serverState.classList.add("live");
  hardwareState.textContent=status.estopped?"扭矩已关闭":status.hardware_enabled?"真机已连接":"硬件锁定";
  resumeButton.disabled=!status.hardware_enabled||!status.estopped;
  renderServos();
}

async function loadRecognizer() {
  const {FilesetResolver,GestureRecognizer}=await import("/web/vendor/mediapipe/vision_bundle.mjs");
  const vision=await FilesetResolver.forVisionTasks("/web/vendor/mediapipe/wasm");
  recognizer=await GestureRecognizer.createFromOptions(vision,{baseOptions:{modelAssetPath:"/web/vendor/mediapipe/gesture_recognizer.task"},runningMode:"IMAGE",numHands:1,cannedGesturesClassifierOptions:{categoryAllowlist:Object.keys(gestures),scoreThreshold:.72,maxResults:1}});
  modelState.textContent="READY";
}

document.querySelector("#mirror").addEventListener("change",event=>frame.classList.toggle("mirrored",event.target.checked));
document.querySelector("#emergency-stop").addEventListener("click",async()=>{
  if (!confirm("急停会关闭全部舵机扭矩，机械臂可能下坠。确认已经托住整臂？")) return;
  try { await api("/api/emergency-stop",{method:"POST"}); unlock.checked=false; await refreshStatus(); message.textContent="已发送扭矩关闭命令；继续托住机械臂。"; }
  catch(error){message.textContent=`急停失败：${error.message}`;}
});
resumeButton.addEventListener("click",async()=>{
  if (!unlock.checked) { message.textContent="恢复扭矩前必须完成现场安全确认。"; return; }
  if (!confirm("恢复全部舵机扭矩？确认机械臂姿态和人员位置安全。")) return;
  try { await api("/api/resume",{method:"POST"}); await refreshStatus(); message.textContent="扭矩已恢复。"; }
  catch(error){message.textContent=`恢复失败：${error.message}`;}
});

try { await refreshStatus(); await loadRecognizer(); cameraLoop(); }
catch(error){ serverState.textContent="连接失败"; message.textContent=error.message; }
