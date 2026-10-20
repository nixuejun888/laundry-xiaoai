#!/data/data/com.termux/files/usr/bin/bash
# hc_listen.py 守护循环（配置了晶御 client_id 时由 tools/fix.py 生成）
termux-wake-lock 2>/dev/null
cd "$HOME/laundry-xiaoai" || exit 1
echo $$ > "$HOME/.config/laundry-xiaoai/hc_loop.pid"
while true; do
  python hc_listen.py --run >> "$HOME/.config/laundry-xiaoai/hc_listen.out" 2>&1
  sleep 15
done
