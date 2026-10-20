#!/data/data/com.termux/files/usr/bin/bash
# 开机自启（由 tools/fix.py 生成到 ~/.termux/boot/start-laundry.sh，需装 Termux:Boot 并打开一次）
SUP="$HOME/.config/laundry-xiaoai/supervisor.pid"
BRIDGE_RUNNING=0
if [ -f "$SUP" ]; then
  p="$(cat "$SUP" 2>/dev/null)"
  if [ -n "$p" ] && [ -r "/proc/$p/cmdline" ] && grep -q "run-loop.sh" "/proc/$p/cmdline" 2>/dev/null; then
    BRIDGE_RUNNING=1
  fi
fi
if [ "$BRIDGE_RUNNING" = "0" ]; then
  nohup bash "$HOME/laundry-xiaoai/run-loop.sh" >/dev/null 2>&1 &
fi

HC_LOOP="$HOME/laundry-xiaoai/hc-loop.sh"
if [ -f "$HC_LOOP" ]; then
  HCPID="$HOME/.config/laundry-xiaoai/hc_loop.pid"
  HC_RUNNING=0
  if [ -f "$HCPID" ]; then
    p="$(cat "$HCPID" 2>/dev/null)"
    if [ -n "$p" ] && [ -r "/proc/$p/cmdline" ] && grep -q "hc-loop.sh" "/proc/$p/cmdline" 2>/dev/null; then
      HC_RUNNING=1
    fi
  fi
  if [ "$HC_RUNNING" = "0" ]; then
    nohup bash "$HC_LOOP" >/dev/null 2>&1 &
  fi
fi
