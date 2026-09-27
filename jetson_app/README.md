# Jetson gesture control server

This Python 3.6-compatible Flask service exposes the Jetson USB camera and a guarded single-servo
API. Hardware access is disabled unless both `--enable-hardware` and the exact confirmation
environment value are present.

Camera-only mode:

```bash
python3 server.py --web-root ./web
```

Hardware mode, only after shutting down every Jupyter arm kernel and supporting the arm:

```bash
DOFBOT_HARDWARE_CONFIRM=POWER_CUTOFF_READY \
python3 server.py --web-root ./web --enable-hardware
```

The committed configuration unlocks only Servo 6 in the operator-requested 90–180° envelope. Test
that expanded range incrementally rather than commanding an immediate 180° to 90° jump. Servos 1–5
and the Victory pose remain locked until their mappings, directions and soft limits are measured.

The red Web emergency-stop button calls the vendor torque-off command. The arm can fall when torque
is removed, so it does not replace the physical power cutoff and must only be used while the arm is
supported.
