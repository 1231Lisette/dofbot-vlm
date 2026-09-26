import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { STLLoader } from "./vendor/STLLoader.js";

const jointLabels = {
  base: "底座",
  shoulder: "肩部",
  elbow: "肘部",
  wrist_pitch: "腕部俯仰",
  wrist_roll: "腕部旋转",
};
const objectLabels = {
  red_cube: "红色方块",
  blue_cube: "蓝色方块",
  green_cube: "绿色方块",
};
const controls = document.querySelector("#joint-controls");
const view = document.querySelector("#robot-view");
const message = document.querySelector("#message");
const modelStatus = document.querySelector("#model-status");
const cameraView = document.querySelector("#camera-view");
const detectionOverlay = document.querySelector("#detection-overlay");
const overlayContext = detectionOverlay.getContext("2d");
const commandInput = document.querySelector("#command-input");
const parseCommandButton = document.querySelector("#parse-button");
const executeCommandButton = document.querySelector("#execute-command-button");
const gestureVideo = document.querySelector("#gesture-video");
const gestureOverlay = document.querySelector("#gesture-overlay");
const gestureContext = gestureOverlay.getContext("2d");
let socket;
let reconnectTimer;
let latestState;
let latestPerception;
let selectedDetection = "red_cube";
let parsedIntent;
let parsedText = "";
let gestureRecognizer;
let gestureStream;
let gestureAnimationFrame;
let lastGestureVideoTime = -1;
let lastGestureSentAt = 0;
let simulatedTimestamp = 2000;

const gestureLabels = {
  Open_Palm: "✋ 张开手掌",
  Thumb_Up: "👍 点赞",
  Victory: "✌️ V 手势",
};
const handConnections = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20], [0, 17],
];

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x081015);
scene.fog = new THREE.Fog(0x081015, 1.1, 2.7);

const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 10);
camera.up.set(0, 0, 1);
camera.position.set(0.52, -0.78, 0.76);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
view.append(renderer.domElement);

const visionCamera = new THREE.OrthographicCamera(-0.65, 0.65, 0.45, -0.45, 0.01, 4);
visionCamera.position.set(0, 0, 1.8);
visionCamera.lookAt(0, 0, 0);
const visionRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
visionRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
visionRenderer.outputColorSpace = THREE.SRGBColorSpace;
cameraView.append(visionRenderer.domElement);

const orbit = new OrbitControls(camera, renderer.domElement);
orbit.target.set(-0.08, 0, 0.49);
orbit.enableDamping = true;
orbit.minDistance = 0.55;
orbit.maxDistance = 2.4;

scene.add(new THREE.HemisphereLight(0xb8eaff, 0x192029, 2.2));
const keyLight = new THREE.DirectionalLight(0xffffff, 3.6);
keyLight.position.set(-0.5, -0.8, 1.8);
keyLight.castShadow = true;
scene.add(keyLight);
const rimLight = new THREE.DirectionalLight(0x55e8d5, 1.4);
rimLight.position.set(1.0, 0.8, 1.1);
scene.add(rimLight);

const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(4, 4),
  new THREE.MeshStandardMaterial({ color: 0x0b1118, roughness: 0.9, metalness: 0.05 }),
);
floor.receiveShadow = true;
scene.add(floor);

const table = new THREE.Mesh(
  new THREE.BoxGeometry(1.44, 1.0, 0.07),
  new THREE.MeshStandardMaterial({ color: 0x493524, roughness: 0.78 }),
);
table.position.z = 0.34;
table.receiveShadow = true;
scene.add(table);

const cubeMeshes = {};
const cubeDefinitions = [
  ["red_cube", 0xef5264, -0.18, -0.17],
  ["blue_cube", 0x4188ef, -0.30, -0.21],
  ["green_cube", 0x3ed88c, -0.47, -0.17],
];
cubeDefinitions.forEach(([name, color, x, y]) => {
  const cube = new THREE.Mesh(
    new THREE.BoxGeometry(0.028, 0.028, 0.028),
    new THREE.MeshStandardMaterial({ color, roughness: 0.45 }),
  );
  cube.position.set(x, y, 0.389);
  cube.castShadow = true;
  scene.add(cube);
  cubeMeshes[name] = cube;
});

const targetZone = new THREE.Mesh(
  new THREE.CylinderGeometry(0.075, 0.075, 0.006, 48),
  new THREE.MeshStandardMaterial({ color: 0x35dcc4, transparent: true, opacity: 0.42 }),
);
targetZone.rotation.x = Math.PI / 2;
targetZone.position.set(-0.20, 0.05, 0.38);
scene.add(targetZone);

const sortZoneMeshes = {};
[
  ["red_cube", 0xef5264, -0.16],
  ["blue_cube", 0x4188ef, -0.25],
  ["green_cube", 0x3ed88c, -0.45],
].forEach(([name, color, x]) => {
  const zone = new THREE.Mesh(
    new THREE.CylinderGeometry(0.038, 0.038, 0.005, 40),
    new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.52 }),
  );
  zone.rotation.x = Math.PI / 2;
  zone.position.set(x, 0.05, 0.381);
  zone.visible = false;
  scene.add(zone);
  sortZoneMeshes[name] = zone;
});

const eefMarker = new THREE.Group();
const eefSphere = new THREE.Mesh(
  new THREE.SphereGeometry(0.008, 18, 12),
  new THREE.MeshBasicMaterial({ color: 0xff4d2e }),
);
eefMarker.add(eefSphere);
eefMarker.add(new THREE.AxesHelper(0.055));
scene.add(eefMarker);

const robotRoot = new THREE.Group();
robotRoot.position.set(-0.35, 0, 0.405);
robotRoot.rotation.z = Math.PI;
scene.add(robotRoot);

const jointPivots = {};
const gripperPivots = {};
const loader = new STLLoader();
const materials = {
  dark: new THREE.MeshStandardMaterial({ color: 0x8d9aa2, metalness: 0.55, roughness: 0.32 }),
  gold: new THREE.MeshStandardMaterial({ color: 0xf2a900, metalness: 0.5, roughness: 0.3 }),
  light: new THREE.MeshStandardMaterial({ color: 0xe6e8e9, metalness: 0.6, roughness: 0.27 }),
};

function attachMesh(parent, name, material) {
  return new Promise((resolve, reject) => {
    loader.load(`/model-assets/${name}.STL`, geometry => {
      geometry.computeVertexNormals();
      const mesh = new THREE.Mesh(geometry, material);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      parent.add(mesh);
      resolve();
    }, undefined, reject);
  });
}

function makeJoint(parent, name, position, fixedEuler = [0, 0, 0]) {
  const origin = new THREE.Group();
  origin.position.set(...position);
  origin.rotation.set(...fixedEuler);
  parent.add(origin);
  const pivot = new THREE.Group();
  origin.add(pivot);
  jointPivots[name] = pivot;
  return pivot;
}

async function loadDofbot() {
  const jobs = [attachMesh(robotRoot, "base_link", materials.dark)];
  const j1 = makeJoint(robotRoot, "base", [0, 0, 0.06605], [-0.010805, 0, 0]);
  jobs.push(attachMesh(j1, "link1", materials.gold));
  const j2 = makeJoint(j1, "shoulder", [0, -0.00031873, 0.04145], [0, Math.PI / 2, 0]);
  jobs.push(attachMesh(j2, "link2", materials.dark));
  const j3 = makeJoint(j2, "elbow", [-0.08285, 0, 0]);
  jobs.push(attachMesh(j3, "link3", materials.gold));
  const j4 = makeJoint(j3, "wrist_pitch", [-0.08285, 0, 0], [0, 0, 0.0083081]);
  jobs.push(attachMesh(j4, "link4", materials.dark));
  const j5 = makeJoint(j4, "wrist_roll", [-0.07385, -0.001, 0], [0, -1.57, 0]);
  jobs.push(attachMesh(j5, "link5_base", materials.light));
  const leftFinger = new THREE.Group();
  const rightFinger = new THREE.Group();
  j5.add(leftFinger, rightFinger);
  gripperPivots.left = leftFinger;
  gripperPivots.right = rightFinger;
  jobs.push(attachMesh(leftFinger, "link5_left_finger", materials.light));
  jobs.push(attachMesh(rightFinger, "link5_right_finger", materials.light));
  await Promise.all(jobs);
  modelStatus.textContent = "STL 模型已加载 · 可拖拽视角";
}

loadDofbot().catch(error => {
  modelStatus.textContent = "STL 模型加载失败";
  console.error(error);
});

function setConnection(kind, text) {
  const box = document.querySelector(".connection");
  box.className = `connection ${kind}`;
  document.querySelector("#connection-text").textContent = text;
}

function buildControls(nextState) {
  if (controls.children.length) return;
  for (const [name, limits] of Object.entries(nextState.limits)) {
    const row = document.createElement("div");
    row.className = "joint-row";
    row.innerHTML = `
      <div class="joint-name"><strong>${jointLabels[name]}</strong><span>${name}</span></div>
      <input data-joint="${name}" type="range" min="${limits[0]}" max="${limits[1]}" step="0.01" value="${nextState.targets[name]}">
      <output class="joint-value" data-value="${name}">0.00</output>`;
    controls.append(row);
  }
  controls.querySelectorAll("input").forEach(input => input.addEventListener("input", event => {
    const name = event.target.dataset.joint;
    document.querySelector(`[data-value="${name}"]`).textContent = Number(event.target.value).toFixed(2);
    send({ type: "set_joints", targets: { [name]: Number(event.target.value) } });
  }));
}

function update(nextState) {
  latestState = nextState;
  buildControls(nextState);
  document.querySelector("#sim-time").textContent = `${nextState.sim_time.toFixed(3)} s`;
  const badge = document.querySelector("#robot-badge");
  badge.textContent = nextState.status === "running" ? "运行中" : "已急停";
  badge.className = nextState.status;
  for (const [name, value] of Object.entries(nextState.joints)) {
    document.querySelector(`[data-value="${name}"]`).textContent = value.toFixed(2);
    const slider = document.querySelector(`[data-joint="${name}"]`);
    if (document.activeElement !== slider) slider.value = nextState.targets[name];
    if (jointPivots[name]) jointPivots[name].rotation.z = value;
  }
  for (const [name, position] of Object.entries(nextState.objects || {})) {
    cubeMeshes[name]?.position.set(...position);
    if (cubeMeshes[name]) cubeMeshes[name].rotation.z = nextState.object_orientations?.[name] || 0;
  }
  eefMarker.position.set(...nextState.tool_position);
  const [leftTravel, rightTravel] = nextState.gripper.finger_positions || [0, 0];
  if (gripperPivots.left) gripperPivots.left.position.x = leftTravel;
  if (gripperPivots.right) gripperPivots.right.position.x = -rightTravel;
  const task = nextState.task;
  const target = task.target || [-0.20, 0.05];
  targetZone.position.x = target[0];
  targetZone.position.y = target[1];
  document.querySelector("#target-readout").textContent = `X ${target[0].toFixed(2)} · Y ${target[1] >= 0 ? "+" : ""}${target[1].toFixed(2)}`;
  const taskChip = document.querySelector("#task-status");
  taskChip.textContent = task.status.toUpperCase();
  taskChip.className = `task-chip ${task.status}`;
  document.querySelector("#task-stage").textContent = task.stage;
  document.querySelector("#task-progress").style.width = `${Math.round(task.progress * 100)}%`;
  document.querySelector("#gripper-state").textContent = nextState.gripper.attached
    ? "GRASPING"
    : (nextState.gripper.opening > 0.5 ? "OPEN" : "CLOSED");
  const collisionReadout = document.querySelector("#collision-state");
  const collision = nextState.collision || { status: "clear", active_contacts: 0 };
  collisionReadout.textContent = collision.status === "warning"
    ? `WARNING ${collision.unexpected_contacts.length}`
    : "CLEAR";
  collisionReadout.className = collision.status;
  const collisionDetail = document.querySelector("#collision-detail");
  if (collision.status === "warning" && collision.unexpected_contacts.length) {
    collisionDetail.textContent = collision.unexpected_contacts
      .map(contact => contact.geoms.join(" ↔ "))
      .join(" · ");
  } else {
    collisionDetail.textContent = `全机械臂接触监测正常 · 环境接触 ${collision.active_contacts || 0}`;
  }
  const taskActive = ["running", "paused"].includes(task.status);
  document.querySelector("#pick-button").disabled = taskActive || nextState.status === "estopped";
  document.querySelector("#object-select").disabled = taskActive;
  document.querySelector("#sort-button").disabled = taskActive || nextState.status === "estopped";
  document.querySelector("#stack-button").disabled = taskActive || nextState.status === "estopped";
  document.querySelector("#cancel-button").disabled = !taskActive;
  controls.querySelectorAll("input").forEach(input => { input.disabled = task.status === "running"; });
  if (nextState.status === "estopped") {
    message.textContent = "急停已锁定关节；自动任务已暂停，点击恢复可继续。";
  } else if (task.status !== "idle") {
    message.textContent = task.message;
  } else {
    message.textContent = "Dofbot 仿真正常，可执行自动抓取或使用手动关节控制。";
  }
  updateAutomation(nextState.automation, task);
  updatePerception(nextState.perception);
  updateGesture(nextState.gesture);
  updateVerification(nextState.verification);
}

function updateVerification(verification) {
  if (!verification) return;
  const current = verification.current;
  const metrics = verification.metrics || {};
  const status = current?.status || "standby";
  const chip = document.querySelector("#verification-status");
  chip.textContent = status.toUpperCase();
  chip.className = status;
  document.querySelector("#verification-message").textContent = current?.message
    || "等待单次抓取任务";
  document.querySelector("#verification-attempt").textContent = current
    ? `${current.attempt} / ${current.max_attempts}`
    : `0 / ${1 + (verification.max_retries || 1)}`;
  document.querySelector("#verification-error").textContent = current?.position_error == null
    ? "—"
    : `${(current.position_error * 1000).toFixed(1)} mm`;
  document.querySelector("#verification-count").textContent = metrics.verified ?? 0;
  document.querySelector("#verification-retries").textContent = metrics.retries ?? 0;
  const reasons = Object.entries(metrics.failure_reasons || {});
  document.querySelector("#verification-detail").textContent = reasons.length
    ? `失败记录 · ${reasons.map(([name, count]) => `${name} ${count}`).join(" · ")}`
    : `SIM CAMERA · 放置容差 ${verification.tolerance_mm.toFixed(0)} mm`;
}

function updateGesture(gesture) {
  if (!gesture) return;
  const current = gesture.current;
  document.querySelector("#gesture-current").textContent = gestureLabels[current] || "未检测到目标手势";
  document.querySelector("#gesture-confidence").textContent = `${Math.round((gesture.confidence || 0) * 100)}%`;
  const required = Math.max(gesture.required_frames || 1, 1);
  document.querySelector("#gesture-progress").style.width = `${Math.min(100, gesture.streak / required * 100)}%`;
  document.querySelector("#gesture-result").textContent = gesture.last_result || "连续稳定识别后才会触发动作。";
  document.querySelector("#gesture-pending").textContent = gesture.pending?.summary || "暂无，请先解析中文指令";
  document.querySelectorAll("[data-gesture-card]").forEach(card => {
    card.classList.toggle("active", card.dataset.gestureCard === current);
    card.classList.toggle("latched", card.dataset.gestureCard === gesture.latched);
  });
}

function updateAutomation(automation, task) {
  if (!automation) return;
  const workflow = automation.workflow;
  const modeLabels = { sorting: "颜色分拣", stacking: "三层堆垛" };
  document.querySelector("#workflow-mode").textContent = modeLabels[workflow.mode] || "等待任务";
  document.querySelector("#workflow-count").textContent = `${workflow.completed} / ${workflow.total}`;
  document.querySelector("#workflow-success").textContent = workflow.succeeded;
  document.querySelector("#workflow-rate").textContent = workflow.completed
    ? `${Math.round(workflow.succeeded / workflow.completed * 100)}%`
    : "—";
  document.querySelector("#workflow-progress").style.width = `${Math.round(workflow.progress * 100)}%`;
  const chip = document.querySelector("#workflow-status");
  chip.textContent = workflow.status.toUpperCase();
  chip.className = `task-chip ${workflow.status}`;
  document.querySelector("#queue-count").textContent = `${automation.queue.length} WAITING`;

  const queueList = document.querySelector("#queue-list");
  const queued = [];
  if (["running", "paused"].includes(workflow.status)
      && task.workflow_id === workflow.id
      && ["running", "paused"].includes(task.status)) {
    queued.push({
      queue_index: task.queue_index,
      object: task.object,
      target: task.target,
      status: "active",
    });
  }
  queued.push(...automation.queue);
  queueList.className = queued.length ? "workflow-list" : "workflow-list empty-list";
  queueList.innerHTML = queued.length ? "" : "暂无排队任务";
  queued.forEach(item => {
    const row = document.createElement("div");
    row.className = `workflow-item ${item.status}`;
    row.innerHTML = `
      <span class="order">${String(item.queue_index).padStart(2, "0")}</span>
      <span><strong>${objectLabels[item.object] || item.object}</strong><small>XY ${item.target[0].toFixed(2)}, ${item.target[1].toFixed(2)}</small></span>
      <b>${item.status === "active" ? task.stage : "QUEUED"}</b>`;
    queueList.append(row);
  });

  const historyList = document.querySelector("#history-list");
  historyList.className = automation.history.length ? "workflow-list" : "workflow-list empty-list";
  historyList.innerHTML = automation.history.length ? "" : "暂无执行记录";
  automation.history.slice(0, 5).forEach(item => {
    const row = document.createElement("div");
    row.className = `workflow-item ${item.status}`;
    row.innerHTML = `
      <span class="order">${String(item.id).padStart(2, "0")}</span>
      <span><strong>${objectLabels[item.object] || item.object}</strong><small>${item.duration.toFixed(2)} SIM-S</small></span>
      <b>${item.status === "completed" ? "DONE" : "FAILED"}</b>`;
    historyList.append(row);
  });

  const sortingVisible = workflow.mode === "sorting" && workflow.status !== "idle";
  Object.values(sortZoneMeshes).forEach(zone => { zone.visible = sortingVisible; });
  targetZone.visible = !sortingVisible;
}

function updatePerception(perception) {
  if (!perception) return;
  latestPerception = perception;
  const detections = perception.detections || [];
  document.querySelector("#detection-count").textContent = String(detections.length).padStart(2, "0");
  const list = document.querySelector("#detection-list");
  list.innerHTML = "";
  detections.forEach(detection => {
    const button = document.createElement("button");
    button.className = `detection-item${selectedDetection === detection.object_name ? " selected" : ""}`;
    const [x, y] = detection.world_center;
    button.innerHTML = `
      <i style="color:${detection.color};background:${detection.color}"></i>
      <span><strong>${detection.label}</strong><small>X ${x.toFixed(3)} · Y ${y.toFixed(3)}</small></span>
      <b>${Math.round(detection.confidence * 100)}%</b>`;
    button.addEventListener("click", () => pickDetection(detection));
    list.append(button);
  });
  updateGraspPlan();
  drawDetections();
}

function updateGraspPlan() {
  const plans = latestPerception?.grasp_plans || {};
  const plan = plans[selectedDetection] || Object.values(plans)[0];
  const list = document.querySelector("#grasp-candidate-list");
  if (!plan) {
    document.querySelector("#grasp-plan-object").textContent = "AWAITING";
    document.querySelector("#grasp-selected-readout").textContent = "暂无安全候选";
    list.innerHTML = "";
    return;
  }
  document.querySelector("#grasp-plan-object").textContent = objectLabels[plan.object_name] || plan.object_name;
  const selected = plan.selected;
  document.querySelector("#grasp-selected-readout").textContent = selected
    ? `${selected.id} · ${selected.yaw_deg >= 0 ? "+" : ""}${selected.yaw_deg.toFixed(1)}° · SCORE ${Math.round(selected.score * 100)}`
    : "没有通过安全筛选的候选";
  list.innerHTML = "";
  plan.candidates.forEach(candidate => {
    const row = document.createElement("div");
    row.className = `grasp-candidate ${candidate.status}`;
    const reason = candidate.reasons?.length
      ? candidate.reasons.join(" / ")
      : `夹指净空 ${(candidate.components.collision_margin * 1000).toFixed(0)} mm · 路径 ${(candidate.components.path_clearance * 1000).toFixed(0)} mm`;
    row.innerHTML = `
      <b>${candidate.id}</b>
      <span><strong>${candidate.label} · ${candidate.yaw_deg >= 0 ? "+" : ""}${candidate.yaw_deg.toFixed(1)}°</strong><small>${reason}</small></span>
      <em>${candidate.status === "rejected" ? "BLOCK" : Math.round(candidate.score * 100)}</em>`;
    list.append(row);
  });
}

function drawDetections() {
  overlayContext.clearRect(0, 0, detectionOverlay.width, detectionOverlay.height);
  if (!latestPerception) return;
  overlayContext.font = "600 13px ui-monospace, SFMono-Regular, Menlo, monospace";
  latestPerception.detections.forEach((detection, index, detections) => {
    const [x1, y1, x2, y2] = detection.bbox;
    const selected = selectedDetection === detection.object_name;
    overlayContext.strokeStyle = detection.color;
    overlayContext.lineWidth = selected ? 4 : 2;
    if (detection.polygon?.length) {
      overlayContext.beginPath();
      detection.polygon.forEach(([px, py], pointIndex) => {
        if (pointIndex === 0) overlayContext.moveTo(px, py);
        else overlayContext.lineTo(px, py);
      });
      overlayContext.closePath();
      overlayContext.stroke();
    } else {
      overlayContext.strokeRect(x1, y1, x2 - x1, y2 - y1);
    }
    const title = `${detection.label}  ${Math.round(detection.confidence * 100)}%`;
    const titleWidth = overlayContext.measureText(title).width + 12;
    const overlapIndex = detections.slice(0, index).filter(previous => (
      Math.abs(previous.pixel_center[0] - detection.pixel_center[0]) < 4
      && Math.abs(previous.pixel_center[1] - detection.pixel_center[1]) < 4
    )).length;
    const labelY = Math.max(0, y1 - 23 - overlapIndex * 24);
    overlayContext.fillStyle = detection.color;
    overlayContext.fillRect(x1, labelY, titleWidth, 22);
    overlayContext.fillStyle = "#07100f";
    overlayContext.fillText(title, x1 + 6, labelY + 16);
  });
  drawGraspCandidates();
}

function drawGraspCandidates() {
  const detection = latestPerception?.detections?.find(item => item.object_name === selectedDetection);
  const plan = latestPerception?.grasp_plans?.[selectedDetection];
  if (!detection || !plan) return;
  const [u, v] = detection.pixel_center;
  plan.candidates.forEach((candidate, index) => {
    const selected = candidate.status === "selected";
    const rejected = candidate.status === "rejected";
    const angle = candidate.yaw;
    const length = selected ? 31 : 24;
    const dx = Math.cos(angle) * length;
    const dy = -Math.sin(angle) * length;
    const offset = index * 2.2;
    overlayContext.save();
    overlayContext.strokeStyle = rejected ? "#ff5267" : (selected ? "#35dcc4" : "#d4b855");
    overlayContext.fillStyle = overlayContext.strokeStyle;
    overlayContext.lineWidth = selected ? 4 : 2;
    overlayContext.setLineDash(selected ? [] : [5, 4]);
    overlayContext.beginPath();
    overlayContext.moveTo(u - dx, v - dy + offset);
    overlayContext.lineTo(u + dx, v + dy + offset);
    overlayContext.stroke();
    overlayContext.setLineDash([]);
    overlayContext.font = "700 10px ui-monospace, SFMono-Regular, Menlo, monospace";
    overlayContext.fillText(candidate.id, u + dx + 4, v + dy + offset + 3);
    overlayContext.restore();
  });
}

function pickDetection(detection) {
  const active = ["running", "paused"].includes(latestState?.task?.status);
  if (active || latestState?.status === "estopped") {
    message.textContent = active ? "当前任务还在执行，请等待完成或先取消。" : "机器人已急停，请先恢复。";
    return;
  }
  selectedDetection = detection.object_name;
  const [u, v] = detection.pixel_center;
  const [x, y] = detection.world_center;
  document.querySelector("#mapping-readout").textContent = `PX ${u.toFixed(1)}, ${v.toFixed(1)}  →  XY ${x.toFixed(3)}, ${y.toFixed(3)}`;
  document.querySelector("#object-select").value = detection.object_name;
  updateGraspPlan();
  drawDetections();
  send({ type: "pick_place", object_name: detection.object_name, target_xy: [-0.20, 0.05] });
}

detectionOverlay.addEventListener("click", event => {
  if (!latestPerception) return;
  const rect = detectionOverlay.getBoundingClientRect();
  const u = (event.clientX - rect.left) / rect.width * detectionOverlay.width;
  const v = (event.clientY - rect.top) / rect.height * detectionOverlay.height;
  const detection = [...latestPerception.detections].reverse().find(item => {
    const [x1, y1, x2, y2] = item.bbox;
    return u >= x1 && u <= x2 && v >= y1 && v <= y2;
  });
  if (detection) pickDetection(detection);
});

function send(payload) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
}

function drawHandLandmarks(landmarks = []) {
  const width = gestureOverlay.width;
  const height = gestureOverlay.height;
  gestureContext.clearRect(0, 0, width, height);
  gestureContext.lineWidth = 3;
  gestureContext.strokeStyle = "#35dcc4";
  for (const hand of landmarks) {
    gestureContext.beginPath();
    for (const [start, end] of handConnections) {
      gestureContext.moveTo(hand[start].x * width, hand[start].y * height);
      gestureContext.lineTo(hand[end].x * width, hand[end].y * height);
    }
    gestureContext.stroke();
    gestureContext.fillStyle = "#edf4f7";
    hand.forEach(point => {
      gestureContext.beginPath();
      gestureContext.arc(point.x * width, point.y * height, 4, 0, Math.PI * 2);
      gestureContext.fill();
    });
  }
}

function recognizeGestureFrame() {
  if (!gestureStream || !gestureRecognizer) return;
  if (gestureVideo.readyState >= 2 && gestureVideo.currentTime !== lastGestureVideoTime) {
    lastGestureVideoTime = gestureVideo.currentTime;
    const now = performance.now();
    const result = gestureRecognizer.recognizeForVideo(gestureVideo, now);
    drawHandLandmarks(result.landmarks || []);
    const category = result.gestures?.[0]?.[0];
    const gesture = gestureLabels[category?.categoryName] ? category.categoryName : null;
    const confidence = gesture ? category.score : 0;
    if (now - lastGestureSentAt >= 90) {
      send({ type: "gesture_frame", gesture, confidence, timestamp_ms: now, source: "camera" });
      lastGestureSentAt = now;
    }
  }
  gestureAnimationFrame = requestAnimationFrame(recognizeGestureFrame);
}

async function startGestureCamera() {
  const startButton = document.querySelector("#gesture-camera-button");
  const stopButton = document.querySelector("#gesture-camera-stop");
  const chip = document.querySelector("#gesture-engine-chip");
  startButton.disabled = true;
  chip.textContent = "MEDIAPIPE · LOADING";
  try {
    if (!gestureRecognizer) {
      const { FilesetResolver, GestureRecognizer } = await import("./vendor/mediapipe/vision_bundle.mjs");
      const vision = await FilesetResolver.forVisionTasks("/static/vendor/mediapipe/wasm");
      gestureRecognizer = await GestureRecognizer.createFromOptions(vision, {
        baseOptions: { modelAssetPath: "/static/vendor/mediapipe/gesture_recognizer.task" },
        runningMode: "VIDEO",
        numHands: 1,
        cannedGesturesClassifierOptions: {
          categoryAllowlist: ["Open_Palm", "Thumb_Up", "Victory"],
          scoreThreshold: 0.65,
          maxResults: 1,
        },
      });
    }
    gestureStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
      audio: false,
    });
    gestureVideo.srcObject = gestureStream;
    await gestureVideo.play();
    document.querySelector("#gesture-placeholder").hidden = true;
    stopButton.disabled = false;
    chip.textContent = "MEDIAPIPE · LIVE";
    chip.classList.remove("muted-chip");
    recognizeGestureFrame();
  } catch (error) {
    startButton.disabled = false;
    chip.textContent = "CAMERA · UNAVAILABLE";
    document.querySelector("#gesture-result").textContent = "摄像头或模型无法启动，可使用下方模拟手势验收。";
    console.error(error);
  }
}

function stopGestureCamera() {
  cancelAnimationFrame(gestureAnimationFrame);
  gestureStream?.getTracks().forEach(track => track.stop());
  gestureStream = undefined;
  gestureVideo.srcObject = null;
  gestureContext.clearRect(0, 0, gestureOverlay.width, gestureOverlay.height);
  document.querySelector("#gesture-placeholder").hidden = false;
  document.querySelector("#gesture-camera-button").disabled = false;
  document.querySelector("#gesture-camera-stop").disabled = true;
  const chip = document.querySelector("#gesture-engine-chip");
  chip.textContent = "MEDIAPIPE · READY";
  chip.classList.add("muted-chip");
  send({ type: "gesture_frame", gesture: null, confidence: 0, timestamp_ms: performance.now(), source: "camera" });
}

async function simulateGesture(gesture) {
  const frames = gesture === "Open_Palm" ? 3 : 6;
  simulatedTimestamp = Math.max(simulatedTimestamp + 2000, performance.now() + 2000);
  const sequence = [{ gesture: null, confidence: 0, timestamp_ms: simulatedTimestamp - 100 }];
  for (let index = 0; index < frames; index += 1) {
    sequence.push({ gesture, confidence: 0.98, timestamp_ms: simulatedTimestamp + index * 100 });
  }
  let payload;
  for (const frame of sequence) {
    const response = await fetch("/api/gestures/frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...frame, source: "simulation" }),
    });
    payload = await response.json();
  }
  if (payload?.state) updateGesture(payload.state);
  if (payload?.robot_state) update(payload.robot_state);
}

const actionLabels = {
  pick_and_place: "PICK_AND_PLACE",
  sort: "SORT_ALL",
  stack: "STACK_ALL",
  home: "HOME",
  cancel: "CANCEL",
  emergency_stop: "EMERGENCY_STOP",
  resume: "RESUME",
};
const targetLabels = {
  left_zone: "LEFT_ZONE",
  center_zone: "CENTER_ZONE",
  right_zone: "RIGHT_ZONE",
};

function renderIntent(intent, state = "preview", overrideMessage = "") {
  parsedIntent = intent;
  const card = document.querySelector("#intent-card");
  const valid = Boolean(intent?.valid);
  card.className = `intent-card ${state === "executed" ? "executed" : (valid ? "valid" : "invalid")}`;
  document.querySelector("#intent-status").textContent = state === "executed"
    ? "EXECUTED"
    : (valid ? "READY" : "REJECTED");
  document.querySelector("#intent-summary").textContent = intent?.summary || "指令未解析";
  document.querySelector("#intent-action").textContent = actionLabels[intent?.action] || "—";
  document.querySelector("#intent-object").textContent = objectLabels[intent?.object_name] || "—";
  const target = targetLabels[intent?.target_name];
  document.querySelector("#intent-target").textContent = target && intent.target_xy
    ? `${target} · ${intent.target_xy[0].toFixed(2)}, ${intent.target_xy[1].toFixed(2)}`
    : (target || "—");
  document.querySelector("#intent-message").textContent = overrideMessage
    || intent?.error
    || (state === "executed" ? "指令已发送，执行状态将在任务面板实时更新。" : "解析成功，请确认后执行。");
  executeCommandButton.disabled = !valid || state === "executed";
}

async function parseLanguage(execute = false) {
  const text = commandInput.value.trim();
  if (!text) {
    renderIntent({ valid: false, summary: "指令未执行", error: "请输入任务指令" });
    return;
  }
  const endpoint = execute ? "/api/language/execute" : "/api/language/parse";
  const activeButton = execute ? executeCommandButton : parseCommandButton;
  const originalLabel = activeButton.innerHTML;
  activeButton.disabled = true;
  activeButton.textContent = execute ? "正在发送…" : "正在解析…";
  document.querySelector("#intent-status").textContent = execute ? "EXECUTING" : "PARSING";
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const payload = await response.json();
    if (!response.ok) {
      const detail = payload.detail || {};
      renderIntent(
        detail.intent || { valid: false, summary: "指令未执行" },
        "blocked",
        detail.execution_error || detail.error || "当前无法执行该指令",
      );
      return;
    }
    parsedText = text;
    renderIntent(payload.intent, execute ? "executed" : "preview");
    if (execute && payload.state) update(payload.state);
  } catch (error) {
    renderIntent({ valid: false, summary: "连接失败", error: "无法连接任务解析接口" });
    console.error(error);
  } finally {
    activeButton.innerHTML = originalLabel;
    if (!execute) activeButton.disabled = false;
  }
}

function connect() {
  clearTimeout(reconnectTimer);
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws`);
  socket.onopen = () => setConnection("online", "Backend Online");
  socket.onmessage = event => {
    const payload = JSON.parse(event.data);
    if (payload.type === "state") update(payload.data);
    if (payload.type === "gesture_result") {
      updateGesture(payload.data.state);
      if (payload.data.robot_state) update(payload.data.robot_state);
    }
    if (payload.type === "error") message.textContent = payload.message;
  };
  socket.onclose = () => {
    setConnection("offline", "连接断开，正在重试");
    reconnectTimer = setTimeout(connect, 1400);
  };
}

function resizeRenderer() {
  const { width, height } = view.getBoundingClientRect();
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  const cameraRect = cameraView.getBoundingClientRect();
  visionRenderer.setSize(cameraRect.width, cameraRect.height, false);
}

function animate() {
  resizeRenderer();
  orbit.update();
  renderer.render(scene, camera);
  visionRenderer.render(scene, visionCamera);
  requestAnimationFrame(animate);
}

document.querySelector("#home-button").addEventListener("click", () => send({ type: "home" }));
document.querySelector("#resume-button").addEventListener("click", () => send({ type: "resume" }));
document.querySelector("#stop-button").addEventListener("click", () => send({ type: "stop" }));
document.querySelector("#pick-button").addEventListener("click", () => send({
  type: "pick_place",
  object_name: document.querySelector("#object-select").value,
  target_xy: [-0.20, 0.05],
}));
document.querySelector("#sort-button").addEventListener("click", () => send({ type: "sort_all" }));
document.querySelector("#stack-button").addEventListener("click", () => send({ type: "stack_all" }));
document.querySelector("#cancel-button").addEventListener("click", () => send({ type: "cancel_task" }));
document.querySelector("#reset-button").addEventListener("click", () => send({ type: "reset_scene" }));
parseCommandButton.addEventListener("click", () => parseLanguage(false));
executeCommandButton.addEventListener("click", () => {
  if (parsedIntent?.valid && parsedText === commandInput.value.trim()) parseLanguage(true);
});
commandInput.addEventListener("input", () => {
  parsedIntent = undefined;
  parsedText = "";
  executeCommandButton.disabled = true;
  const card = document.querySelector("#intent-card");
  card.className = "intent-card awaiting";
  document.querySelector("#intent-status").textContent = "CHANGED";
  document.querySelector("#intent-summary").textContent = "指令内容已修改";
  document.querySelector("#intent-action").textContent = "—";
  document.querySelector("#intent-object").textContent = "—";
  document.querySelector("#intent-target").textContent = "—";
  document.querySelector("#intent-message").textContent = "内容已更改，请重新解析后执行。";
  fetch("/api/gestures/pending", { method: "DELETE" }).catch(() => {});
});
commandInput.addEventListener("keydown", event => {
  if (event.isComposing || event.key !== "Enter") return;
  if ((event.metaKey || event.ctrlKey) && !executeCommandButton.disabled) {
    event.preventDefault();
    executeCommandButton.click();
  } else if (!event.shiftKey && !event.metaKey && !event.ctrlKey) {
    event.preventDefault();
    parseCommandButton.click();
  }
});
document.querySelectorAll("[data-command]").forEach(button => button.addEventListener("click", () => {
  commandInput.value = button.dataset.command;
  parsedIntent = undefined;
  parsedText = "";
  executeCommandButton.disabled = true;
  parseLanguage(false);
}));
document.querySelector("#gesture-camera-button").addEventListener("click", startGestureCamera);
document.querySelector("#gesture-camera-stop").addEventListener("click", stopGestureCamera);
document.querySelectorAll("[data-sim-gesture]").forEach(button => button.addEventListener("click", () => {
  simulateGesture(button.dataset.simGesture).catch(error => {
    document.querySelector("#gesture-result").textContent = "模拟手势发送失败，请检查后端连接。";
    console.error(error);
  });
}));
connect();
animate();
