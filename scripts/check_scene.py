from pathlib import Path

import mujoco

root = Path(__file__).resolve().parents[1]
model = mujoco.MjModel.from_xml_path(str(root / "simulation" / "scene.xml"))
data = mujoco.MjData(model)
for _ in range(100):
    mujoco.mj_step(model, data)
print(f"scene ok: nq={model.nq}, nu={model.nu}, sim_time={data.time:.2f}s")
