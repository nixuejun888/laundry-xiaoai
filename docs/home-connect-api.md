# 晶御 / Home Connect 中国区 API 笔记（实测）

## 注册与应用

1. 开发者门户：<https://developer.home-connect.cn/user/register>
   - Account Type 选 **Individual**；
   - **邮箱全部小写**（大写会导致 OAuth 回调 400）。
2. 创建应用：
   - 勾 **Sync to China**；
   - **Home Connect User Account for Testing** 填晶御账号手机号（`+86` 无空格），否则登录成功但设备列表为空；
   - 应用类型选 **Device Flow**（只需 Client ID；被拒再改 Authorization Code）；
   - 如表单要求 Success Redirect，填 `https://api.home-connect.com`（Device Flow 也需要一个合法 https URI）。
3. 若门户有 scope 勾选项：勾 `IdentifyAppliance`、`Monitor`、`Washer-Monitor`、`Dryer-Monitor`，与配置里的 `scope` 一致。

## OAuth

- Device Authorization：`POST https://api.home-connect.cn/security/oauth/device_authorization`
  - form：`client_id`、`scope`
  - 返回：`device_code`、`user_code`、`verification_uri`、`verification_uri_complete`（务必用完整链接，根地址会 `Cannot GET /`）
  - 设备码有效期约 30 分钟，`interval` 建议按返回值轮询；
- Token：`POST https://api.home-connect.cn/security/oauth/token`
  - `grant_type=device_code`（部分实现要求 RFC URN，脚本已做兜底）；
  - 刷新：`grant_type=refresh_token`；
- access_token 有效期约 24 小时，refresh_token 可续期；限流：刷新约 100 次/天。

## REST 请求

- 所有 REST 请求必须带：
  - `Authorization: Bearer <access_token>`
  - `Accept: application/vnd.bsh.sdk.v1+json`（否则 406）
- 设备列表：`GET /api/homeappliances`
- 状态：`GET /api/homeappliances/{haId}/status`
- 设置：`GET /api/homeappliances/{haId}/settings`（需要额外 scope，默认会 403）
- 当前程序：`GET /api/homeappliances/{haId}/programs/active`
- 事件流：`GET /api/homeappliances/{haId}/events`（SSE，`Accept: text/event-stream`）

## 事件

| 事件 | 含义 |
| --- | --- |
| `BSH.Common.Event.ProgramFinished` | 程序完成（洗衣机；烘干机可能被防皱延后） |
| `LaundryCare.Dryer.Event.DryingProcessFinished` | 烘干完成（推荐用于烘干机） |
| `LaundryCare.Washer.Event.IDos1FillLevelPoor` | i-DOS 1 仓（洗衣液）液位不足（`Present` 表示发生） |
| `LaundryCare.Washer.Event.IDos2FillLevelPoor` | i-DOS 2 仓（柔顺剂）液位不足 |
| `BSH.Common.Status.DoorState` | 门状态（Open/Closed/Locked） |
| `BSH.Common.Option.RemainingProgramTime` / `ProgramProgress` | 剩余时间 / 进度（是否推送取决于机型/固件） |
| `BSH.Common.Root.ActiveProgram` / `SelectedProgram` | 当前/选中的程序 |

**不要用** `BSH.Common.Status.OperationState = Finished` 当完成信号：官方语义包含“成功中止”，中途取消也会发。

实测的噪音事件（建议忽略/不播报）：
`EstimatedTotalProgramTime`、`FinishInRelative`、`IDos1Active`、`IDos2Active`、`SpinSpeed`、`Temperature`、`SelectedProgram`（切换程序时会大量产生）。

## 限流

- 约 1000 请求/天、50/分钟；
- SSE 长连接常驻只算一次请求；断线重连也算请求；
- 建议重连间隔 ≥ 15 秒（脚本已内置指数退避）。

## 常见错误

| 报错 | 原因/处理 |
| --- | --- |
| 406 `only available with these types` | 缺 `Accept: application/vnd.bsh.sdk.v1+json` |
| 403 `insufficient_scope` | 应用/令牌缺 Settings 等 scope |
| 404 `SDK.Error.NoProgramActive` | 当前没有程序在跑，正常 |
| `invalid_scope` | 门户 scope 与配置不一致 |
| `--list` 为空 | 测试账号手机号与晶御不一致，或没勾 Sync to China |
| 设备码 `invalid_grant` / 验证码失效 | 设备码 30 分钟过期，重新 `--login` |
