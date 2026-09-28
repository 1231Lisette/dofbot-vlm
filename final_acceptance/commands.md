# DOFBOT操作命令

---

ssh jetson@192.168.1.149

pgrep -af '^python3 /home/jetson/dofbot-web/server.py '

---

cd /home/jetson/dofbot-web

export DOFBOT_HARDWARE_CONFIRM=POWER_CUTOFF_READY

nohup python3 /home/jetson/dofbot-web/server.py \
  --host 0.0.0.0 \
  --port 8765 \
  --web-root /home/jetson/dofbot-web/web \
  --enable-hardware \
  > /home/jetson/dofbot-web/server.log 2>&1 < /dev/null &

curl -s http://127.0.0.1:8765/api/status | python3 -m json.tool

http://192.168.1.149:8765/