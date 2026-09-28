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
const syncK1Button = document.querySelector("#sync-k1");
const standbyButton = document.querySelector("#standby-pose");
const standbyNote = document.querySelector("#standby-note");
const servoStatusBody = document.querySelector("#servo-status-body");
const eventLog = document.querySelector("#event-log");
const telemetryState = document.querySelector("#telemetry-state");

const gestures = {
  Thumb_Up: { icon:"👍", name:"点赞", action:"张开夹爪", frames:6 },
  Closed_Fist: { icon:"✊", name:"握拳", action:"闭合夹爪", frames:6 },
  Victory: { icon:"✌️", name:"V 手势", action:"回到等候姿势后点头两次", frames:7 },
  Pointing_Up: { icon:"☝️", name:"食指向上", action:"回到等候姿势", frames:7 },
};
const connections = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];

let recognizer;
let status;
let running = true;
let currentGesture = null;
let stableFrames = 0;
let latched = false;
const servoElements = new Map();
let pendingMove = null;
let moveTimer = null;
let motionRequestInFlight = false;
let activeRequestServo = null;
let motionReadyAt = 0;

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

async function triggerGesture(name, definition) {
  if (!unlock.checked) {
    message.textContent = `${definition.action}未发送：请先完成现场安全确认。`;
    return;
  }
  try {
    await api(`/api/gestures/${encodeURIComponent(name)}`, { method:"POST" });
    message.textContent = `${definition.action}命令已接受。`;
  } catch (error) {
    message.textContent = `动作被服务端阻止：${error.message}`;
  }
}

function queueLiveMove(servoId, angle) {
  if (!unlock.checked) {
    message.textContent = "拖动未发送：请先完成现场安全确认。";
    return;
  }
  if (motionRequestInFlight || Date.now() < motionReadyAt) {
    const elements=servoElements.get(String(servoId));
    const accepted=status.last_angles[String(servoId)];
    if (elements) { elements.slider.value=accepted; elements.output.value=`${accepted}°`; }
    message.textContent="上一条舵机动作尚未结束，本次输入未发送。";
    return;
  }
  if (pendingMove && pendingMove.servoId !== servoId) {
    const previous=servoElements.get(String(pendingMove.servoId));
    const accepted=status.last_angles[String(pendingMove.servoId)];
    if (previous) { previous.slider.value=accepted; previous.output.value=`${accepted}°`; }
  }
  pendingMove={servoId,angle};
  clearTimeout(moveTimer);
  moveTimer=setTimeout(flushLiveMove,140);
}

async function flushLiveMove() {
  if (!pendingMove || motionRequestInFlight) return;
  const {servoId,angle}=pendingMove;
  pendingMove=null;
  if (Date.now() < motionReadyAt) return;
  motionRequestInFlight=true;
  activeRequestServo=servoId;
  try {
    const result = await api(`/api/servos/${servoId}`, {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({angle, duration_ms:status.live_move_time_ms}),
    });
    status.last_angles[String(servoId)] = result.angle;
    motionReadyAt=Date.now()+result.duration_ms;
    message.textContent = `S${servoId} 正在跟随：${angle}°。`;
  } catch (error) {
    const elements = servoElements.get(String(servoId));
    if (elements) {
      const accepted = status.last_angles[String(servoId)];
      elements.slider.value = accepted;
      elements.output.value = `${accepted}°`;
    }
    message.textContent = `S${servoId} 被阻止：${error.message}`;
  } finally {
    motionRequestInFlight=false;
    activeRequestServo=null;
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
    if (stableFrames>=definition.frames) { latched=true; triggerGesture(name,definition); }
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
      const cameraDevice=response.headers.get("X-DOFBOT-Camera-Device");
      const blob=await response.blob();
      const url=URL.createObjectURL(blob);
      image.src=url;
      await image.decode();
      placeholder.hidden=true; cameraState.textContent=cameraDevice?`LIVE ${cameraDevice}`:"LIVE";
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
  servoElements.clear();
  Object.entries(status.servos).forEach(([id,item])=>{
    const controlEnabled=item.enabled&&status.manual_control.enabled;
    const article=document.createElement("article"); article.className=`servo-control${controlEnabled?"":" locked"}`;
    const value=status.last_angles[id];
    const stepNote=item.max_step?` · 单次≤${item.max_step}°`:"";
    const input=`<input type="range" min="${item.min}" max="${item.max}" step="1" value="${value}" ${controlEnabled?"":"disabled"}>`;
    const control=item.max_step?`<div class="servo-adjust"><button type="button" data-delta="-1" ${controlEnabled?"":"disabled"}>−1°</button>${input}<button type="button" data-delta="1" ${controlEnabled?"":"disabled"}>+1°</button></div>`:input;
    article.innerHTML=`<div><strong>S${id} · ${item.name}</strong><small>${controlEnabled?`${item.min}–${item.max}°${stepNote}`:"接线待验证 · 服务端锁定"}</small></div>${control}<output>${value}°</output>`;
    const slider=article.querySelector("input"); const output=article.querySelector("output");
    servoElements.set(id,{slider,output});
    slider.addEventListener("input",()=>{
      const accepted=Number(status.last_angles[id]);
      const requested=Number(slider.value);
      const target=item.max_step?Math.max(accepted-item.max_step,Math.min(accepted+item.max_step,requested)):requested;
      slider.value=target; output.value=`${target}°`; queueLiveMove(id,target);
    });
    article.querySelectorAll("[data-delta]").forEach(button=>button.addEventListener("click",()=>{
      if (!unlock.checked) { message.textContent="步进未发送：请先完成现场安全确认。"; return; }
      const target=Math.max(item.min,Math.min(item.max,Number(status.last_angles[id])+Number(button.dataset.delta)));
      slider.value=target; output.value=`${target}°`; queueLiveMove(id,target);
    }));
    root.append(article);
  });
}

function renderGestureActions() {
  const gestureConfig=status.gesture_actions;
  Object.entries(gestureConfig.actions).forEach(([name,action])=>{
    const card=document.querySelector(`[data-gesture="${name}"]`);
    if (!card) return;
    const executable=gestureConfig.enabled&&action.enabled;
    card.querySelector("small").textContent=`${action.label}${executable?" · 可执行":" · 仅识别"}`;
  });
}

function renderTelemetry(telemetry) {
  telemetryState.textContent=telemetry.estopped?"扭矩已关闭":`TORQUE ${telemetry.last_torque_command.toUpperCase()}`;
  Object.entries(telemetry.last_angles).forEach(([id,angle])=>{
    status.last_angles[id]=angle;
    const elements=servoElements.get(id);
    if (elements && String(activeRequestServo)!==id && (!pendingMove || String(pendingMove.servoId)!==id)) {
      elements.slider.value=angle;
      elements.output.value=`${angle}°`;
    }
  });
  servoStatusBody.replaceChildren();
  Object.entries(status.servos).forEach(([id,item])=>{
    const state=telemetry.servo_states[id]||{};
    const row=document.createElement("tr");
    const active=Number(telemetry.active_servo_id)===Number(id)?" · 动作窗口":"";
    row.innerHTML=`<td>S${id}</td><td>${item.name}</td><td>${state.target_angle ?? telemetry.last_angles[id]}°</td><td class="unknown">—</td><td>${state.command_state||"unknown"}${active}</td><td>${state.last_command_at||"—"}</td><td>${state.last_message||"无到位反馈"}</td>`;
    servoStatusBody.append(row);
  });
  const lines=telemetry.events.slice(-80).map(event=>{
    const marker={info:"INFO",warning:"WARN",error:"ERROR",critical:"CRITICAL"}[event.level]||event.level.toUpperCase();
    return `[${event.timestamp}] ${marker.padEnd(8)} ${event.message}`;
  });
  eventLog.textContent=lines.join("\n")||"暂无事件";
  eventLog.scrollTop=eventLog.scrollHeight;
}

async function telemetryLoop() {
  while (running) {
    try {
      renderTelemetry(await api("/api/telemetry"));
    } catch (error) {
      telemetryState.textContent="OFFLINE";
    }
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
}

async function refreshStatus() {
  status=await api("/api/status");
  serverState.textContent=status.hardware_enabled?"JETSON · HARDWARE":"JETSON · CAMERA ONLY";
  serverState.classList.add("live");
  hardwareState.textContent=status.estopped?"扭矩已关闭":status.hardware_enabled?"扭矩状态未知":"硬件锁定";
  if (!status.manual_control.enabled) hardwareState.textContent="接线待验证 · 全局锁定";
  resumeButton.disabled=!status.hardware_enabled||!status.manual_control.enabled;
  syncK1Button.disabled=!status.hardware_enabled||!status.manual_control.enabled||!status.k1_pose?.enabled;
  standbyButton.disabled=!status.hardware_enabled||!status.manual_control.enabled||!status.standby_pose.enabled;
  if (status.standby_pose.enabled) {
    const angles=Object.values(status.standby_pose.angles).join("/");
    standbyNote.textContent=`已配置等候姿势 ${angles}°；执行时逐轴运动，上一条完成后才发送下一条。`;
  } else {
    standbyNote.textContent=`等候姿势未启用：${status.standby_pose.reason}`;
  }
  renderServos();
  renderGestureActions();
  renderTelemetry({
    estopped:status.estopped,
    last_torque_command:status.last_torque_command,
    active_servo_id:status.active_servo_id,
    last_angles:status.last_angles,
    servo_states:status.servo_states,
    events:[],
  });
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
syncK1Button.addEventListener("click",async()=>{
  if (!unlock.checked) { message.textContent="K1 同步前必须完成现场安全确认。"; return; }
  if (!confirm("仅当你刚刚按过物理 K1，且机械臂已稳定直立时继续。\n\n此操作只同步网页基准，不会移动舵机。")) return;
  try {
    await api("/api/sync-k1",{method:"POST"});
    await refreshStatus();
    message.textContent="K1 直立基准已同步；未发送舵机命令。现在可点击‘回到等候姿势’。";
  } catch(error) { message.textContent=`K1 同步失败：${error.message}`; }
});
standbyButton.addEventListener("click",async()=>{
  if (!unlock.checked) { message.textContent="执行等候姿势前必须完成现场安全确认。"; return; }
  if (!confirm("回到等候姿势？动作将逐轴、每步最多 10° 执行。")) return;
  try { await api("/api/standby",{method:"POST"}); message.textContent="等候姿势序列已执行。"; }
  catch(error){message.textContent=`等候姿势被阻止：${error.message}`;}
});

try { await refreshStatus(); await loadRecognizer(); cameraLoop(); telemetryLoop(); }
catch(error){ serverState.textContent="连接失败"; message.textContent=error.message; }
