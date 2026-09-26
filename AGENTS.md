# Repository working agreement

## Start here

Read these files before changing the project:

1. `README.md`
2. `docs/HANDOFF.md`
3. `docs/COURSE_REQUIREMENTS.md`
4. `docs/HARDWARE_SETUP.md` for any real-machine work
5. `docs/CALIBRATION.md` before sending a servo command

## Safety boundary

- The current `DofbotRobot` is a placeholder until Milestone 7 is implemented and calibrated.
- Never copy MuJoCo radians directly to real servos. Apply an explicit joint-name, servo-ID,
  zero-offset, direction and soft-limit mapping.
- Do not send simultaneous or full-range servo motion before all six servo IDs have been read,
  identified and tested one at a time at low speed.
- Keep a physical power cutoff within reach during the first hardware tests.
- Only one process may own the hardware control channel. Check vendor services before starting a
  custom controller.
- Do not upgrade or overwrite the vendor Jetson image before making a verified backup.

## Change workflow

- Keep `main` runnable. Use one branch for each bounded feature or fix.
- Preserve the `RobotInterface` boundary and keep the MuJoCo backend working while adding the
  Dofbot backend.
- Add or update tests for behavior changes. Before merging, run:

```bash
python -m pytest -q
python -m ruff check .
node --check frontend/app.js
python scripts/check_scene.py
```

- Update `docs/HANDOFF.md` after a milestone or hardware discovery.
- Record measured hardware values in `docs/CALIBRATION.md`; do not bury calibration constants in
  source code.
- Never commit passwords, Wi-Fi credentials, tokens, system images, virtual environments, logs or
  large trained weights.

## Current priority

Milestone 7 is the active phase: establish the Jetson baseline, collect servo/camera calibration,
then implement a safe network hardware bridge and `DofbotRobot` adapter.
