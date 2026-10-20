#!/data/data/com.termux/files/usr/bin/bash
# bridge.py 守护循环（由 tools/fix.py 生成到 ~/laundry-xiaoai/run-loop.sh）
termux-wake-lock 2>/dev/null
cd "$HOME/laundry-xiaoai" || exit 1
PID="$HOME/.config/laundry-xiaoai/bridge.pid"
SUP="$HOME/.config/laundry-xiaoai/supervisor.pid"
echo $$ > "$SUP"
while true; do
  if [ -f "$PID" ]; then
    p="$(cat "$PID" 2>/dev/null)"
    if [ -n "$p" ] && [ -r "/proc/$p/cmdline" ] && grep -q "bridge.py" "/proc/$p/cmdline" 2>/dev/null; then
      sleep 30
      continue
    fi
  fi
  python bridge.py >> "$HOME/.config/laundry-xiaoai/bridge.out" 2>&1
  sleep 10
done
