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

The commissioning configuration exposes Servos 1–5 only in a narrow 85–95° envelope and Servo 6 in
the operator-requested 90–180° envelope. The server rejects switching to a different servo while the
previous servo's commanded move time is still active. Expand each envelope only after its direction
and mechanical clearance are observed. The multi-joint Victory pose remains locked.

The red Web emergency-stop button calls the vendor torque-off command. The arm can fall when torque
is removed, so it does not replace the physical power cutoff and must only be used while the arm is
supported.
