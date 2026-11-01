#!/data/data/com.termux/files/usr/bin/bash
# 看门狗：bridge / 晶御监听 掉线就拉起来。由 termux-job-scheduler 定时调用。
termux-wake-lock 2>/dev/null
APP="$HOME/laundry-xiaoai"
CFG="$HOME/.config/laundry-xiaoai"
mkdir -p "$CFG"

alive() {
  p="$(cat "$1" 2>/dev/null)"
  [ -n "$p" ] && [ -r "/proc/$p/cmdline" ] && grep -q "$2" "/proc/$p/cmdline" 2>/dev/null
}

cd "$APP" || exit 0

if ! alive "$CFG/supervisor.pid" "run-loop.sh"; then
  nohup bash "$APP/run-loop.sh" >> "$CFG/bridge.out" 2>&1 &
  echo "watchdog: 重启 bridge 守护" >> "$CFG/watchdog.log"
fi

if [ -f "$CFG/homeconnect.json" ] && ! alive "$CFG/hc_loop.pid" "hc-loop.sh"; then
  nohup bash "$APP/hc-loop.sh" >> "$CFG/hc_listen.out" 2>&1 &
  echo "watchdog: 重启晶御监听" >> "$CFG/watchdog.log"
fi
