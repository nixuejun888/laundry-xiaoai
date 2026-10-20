# Changelog

## v0.1.0

首个公开版本：

- `bridge.py`：本机 HTTP 播报服务（小米云 TTS / MIoT play-text 自动选择、类别去抖、免打扰、音量、指定音箱）；
- 方案 A：微信通知 → 通知转发 App → bridge → 小爱；
- 方案 B：晶御（Home Connect 中国区）官方 API SSE 监听，支持完成事件与 i-DOS 耗材不足事件；
- 播报模式：`finished` / `minimal` / `important` / `all`；
- `install.py` 从零一键安装（依赖安装、小米登录、测试播报、可选晶御配置、守护与开机自启）；
- `tools/fix.py` 更新/重启/自愈；`tools/diag.py`、`showlog.py`、`selftest.py`、`stop.py` 等；
- 实测机型：博世洗衣机 WGK754D10W、干衣机 WQK755U10W；小爱音箱硬件 OH2。
