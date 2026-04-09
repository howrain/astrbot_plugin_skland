<div align="center">

# astrbot_plugin_skland
### AstrBot 森空岛签到与明日方舟查询插件

[![Build and Release](https://github.com/howrain/astrbot_plugin_skland/actions/workflows/release.yml/badge.svg)](https://github.com/howrain/astrbot_plugin_skland/actions/workflows/release.yml)
[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-3b82f6?style=flat-square)](https://github.com/Soulter/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10%2B-0ea5e9?style=flat-square)](https://www.python.org/)

支持 `森空岛签到`、`森空岛扫码绑定`、`明日方舟便签与公告`、`公招/材料/肉鸽/抽卡记录` 的一体化插件。

兼容旧版 `skdlogin <token>` 绑定数据，升级后无需重新录入账号。

</div>

---

## 功能概览

- `森空岛签到`：支持明日方舟与终末地每日签到，保留原有手动 token 登录。
- `扫码绑定`：新增 `/skdscan` 扫码登录，成功、超时或拒绝后自动撤回二维码消息。
- `账号兼容`：兼容旧版单账号存储与旧登录信息，新旧登录方式可同时继续使用。
- `明日方舟查询`：支持便签、理智、剿灭、日常、周常、公告、公招、刷图推荐、肉鸽、抽卡记录等功能。
- `图片渲染`：便签、公告列表、公告正文、公招查询、材料掉率、肉鸽、抽卡记录统一输出图片，失败时自动回退文本。
- `文档预览`：仓库内提供真实接口生成的预览图，可直接用于 README 展示或后续更新。

## 指令前缀

默认指令前缀为 AstrBot 配置中的命令前缀，以下示例均以 `/` 表示。

### 森空岛指令

| 指令 | 别名 | 作用 |
|:--|:--|:--|
| `skd` | `森空岛` | 查看当前账号的签到状态与最近结果 |
| `skdlogin <token>` | `森空岛登录` | 手动录入森空岛 token 并立即尝试签到 |
| `skdscan` | `森空岛扫码登录` | 发送二维码，用森空岛 App 扫码绑定 |
| `skdlogout` | `森空岛登出`、`森空岛退出` | 删除当前用户绑定信息 |
| `skdusers` | `森空岛用户` | 查看当前已存储的用户数量 |
| `skdhelp` | `森空岛帮助` | 查看完整帮助与自动签到说明 |

### 明日方舟指令

主命令为 `arknights`，别名为 `明日方舟`、`方舟`。

| 指令 | 是否需要绑定 | 作用 |
|:--|:--|:--|
| `/arknights 便签` | 是 | 输出博士资料、理智、日周常、剿灭、收藏数、线索、公招状态的一图流 |
| `/arknights 理智` | 是 | 单独查看当前理智与预计回满时间 |
| `/arknights 剿灭` | 是 | 查看本周剿灭进度 |
| `/arknights 日常` | 是 | 查看日常与周常完成情况 |
| `/arknights 周常` | 是 | 单独查看周常完成情况 |
| `/arknights 肉鸽` | 是 | 输出各主题集成战略进度图 |
| `/arknights 集成战略` | 是 | `肉鸽` 的别名 |
| `/arknights 抽卡记录` | 是 | 按卡池分组查看寻访记录、六星节点与当前保底进度 |
| `/arknights 寻访记录` | 是 | `抽卡记录` 的别名 |
| `/arknights 抽卡记录 不归花火` | 是 | 按卡池关键字筛选抽卡记录 |
| `/arknights 抽卡分析` | 是 | 统计总抽数、平均六星、UP 占比与六星角色分布 |
| `/arknights 寻访分析` | 是 | `抽卡分析` 的别名 |
| `/arknights 公告` | 否 | 查看官方公告列表图片 |
| `/arknights 公告 1` | 否 | 查看对应公告正文渲染图 |
| `/arknights 刷图推荐` | 否 | 优先截图一图流网站的推荐卡片区域；失败时回退到本地渲染版 |
| `/arknights 材料掉率` | 否 | 优先截图一图流网站的推荐卡片区域；失败时回退到本地渲染版 |
| `/arknights 公招查询 支援 远程位` | 否 | 查询公招标签组合；绑定后额外标记已持有 / 未持有 / 满潜 |

## 登录方式

### 1. 扫码登录，推荐

1. 私聊机器人发送 `/skdscan`
2. 使用森空岛 App 扫描二维码
3. 绑定完成后插件会立即尝试签到
4. 若二维码超时、登录完成或被拒绝，消息会自动撤回以降低泄露风险

### 2. 手动 token 登录

1. 登录 [森空岛](https://www.skland.com/)
2. 打开 [https://web-api.skland.com/account/info/hg](https://web-api.skland.com/account/info/hg)
3. 找到返回 JSON 中 `content` 的值
4. 私聊机器人发送 `/skdlogin <token>` 完成绑定

## 自动签到说明

- 插件支持定时为已绑定用户执行自动签到。
- 默认会同时尝试 `明日方舟` 和 `终末地` 的签到。
- 自动签到时间、开关、随机延迟等配置可在 AstrBot 配置页中调整。
- 若 token 失效，插件会提示重新使用 `/skdlogin` 或 `/skdscan` 绑定。

## 配置说明

目前常用配置项如下：

| 配置项 | 默认值 | 说明 |
|:--|:--|:--|
| `auto_sign_enabled` | `true` | 是否开启自动签到 |
| `auto_sign_hour` | `1` | 自动签到执行小时 |
| `auto_sign_delay` | `10` | 自动签到随机延迟秒数 |
| `max_users` | `10` | 最大绑定用户数，`0` 表示不限制 |
| `render_cache_ttl_seconds` | `3600` | 渲染缓存保留时长，单位秒；默认只保留最近 1 小时的 `render_cache` 文件 |

补充说明：

- `render_cache_ttl_seconds = 3600` 表示保留 1 小时
- `render_cache_ttl_seconds = 1800` 表示保留 30 分钟
- `render_cache_ttl_seconds = 0` 表示每次渲染前尽量清理全部旧缓存

## 效果预览

以下图片由仓库内脚本通过真实接口生成，位于 `docs/preview/`。

为兼容 AstrBot WebUI 的插件说明弹窗，README 中的预览图建议使用 `https://` 绝对地址。
像 `docs/preview/note.png` 这类相对路径，在 GitHub 中通常可正常显示，但在 AstrBot WebUI 中往往不会自动解析到插件目录，因此会出现图片裂开的情况。

### 便签与公告

| 便签 | 公告列表 |
|:--:|:--:|
| <img src="https://raw.githubusercontent.com/howrain/astrbot_plugin_skland/main/docs/preview/note.png" width="360" alt="note"> | <img src="https://raw.githubusercontent.com/howrain/astrbot_plugin_skland/main/docs/preview/announcement-list.png" width="360" alt="announcement-list"> |

| 公告正文 |
|:--:|
| <img src="https://raw.githubusercontent.com/howrain/astrbot_plugin_skland/main/docs/preview/announcement-1.png" width="720" alt="announcement-1"> |

### 材料、公招、肉鸽

| 一图流截图版 | 公招查询 |
|:--:|:--:|
| <img src="https://raw.githubusercontent.com/howrain/astrbot_plugin_skland/main/docs/preview/material.png" width="360" alt="material"> | <img src="https://raw.githubusercontent.com/howrain/astrbot_plugin_skland/main/docs/preview/recruit.png" width="360" alt="recruit"> |

| 本地渲染版材料图 |
|:--:|
| <img src="https://raw.githubusercontent.com/howrain/astrbot_plugin_skland/main/docs/preview/material-render.png" width="720" alt="material-render"> |

| 集成战略 |
|:--:|
| <img src="https://raw.githubusercontent.com/howrain/astrbot_plugin_skland/main/docs/preview/rogue.png" width="520" alt="rogue"> |

### 抽卡记录与分析

| 抽卡记录 | 指定卡池查询 |
|:--:|:--:|
| <img src="https://raw.githubusercontent.com/howrain/astrbot_plugin_skland/main/docs/preview/gacha.png" width="360" alt="gacha"> | <img src="https://raw.githubusercontent.com/howrain/astrbot_plugin_skland/main/docs/preview/gacha-pool.png" width="360" alt="gacha-pool"> |

| 抽卡分析 |
|:--:|
| <img src="https://raw.githubusercontent.com/howrain/astrbot_plugin_skland/main/docs/preview/gacha-analysis.png" width="720" alt="gacha-analysis"> |

## 安装与依赖

### 安装插件

```bash
cd AstrBot/data/plugins
git clone https://github.com/howrain/astrbot_plugin_skland.git
```

### 安装浏览器内核

图片渲染依赖 Playwright，首次安装后需要额外执行：

```bash
playwright install chromium
```

### Python 依赖

插件依赖已写入 `requirements.txt`，包含：

- `httpx`
- `pycryptodome`
- `apscheduler`
- `qrcode[pil]`
- `jinja2`
- `playwright`

## 材料掉率的两种输出模式

`/arknights 刷图推荐` 与 `/arknights 材料掉率` 目前采用双模式策略：

1. 网站截图版
   直接访问一图流页面，并只裁切推荐材料卡片区域。
   这版最接近一图流原站样式，优先用于日常输出。

2. 本地渲染版
   当网站截图失败、页面结构异常或 Playwright 无法稳定裁切时，回退到插件内置模板渲染。
   这版会展示：
   - 材料图标
   - 材料名称
   - 推荐关卡编号
   - 综合效率
   - 置信度与样本数
   - 期望理智
   - 当前接口返回的全部材料项（当前实测为 17 种）

补充说明：

- 本地渲染里的 `置信度 99.9` 来自一图流接口的 `sampleConfidence` 字段，本身就经常是 `99.9`，不是插件渲染错误。
- 样本数量单独来自 `sampleSize` 字段，便于和置信度区分查看。

## 兼容性说明

- 兼容旧版 `/skdlogin <token>` 登录方式。
- 兼容旧版已存储的用户信息与签到数据。
- 新版扫码登录写入新结构时，会自动兼容旧数据读取。
- 未安装 Playwright 或截图失败时，相关功能会自动回退为文本输出，不影响查询本身。

## 目录结构

```text
astrbot_plugin_skland/
├── main.py                     # 插件入口与命令分发
├── skland_api.py               # 森空岛核心 API 封装
├── core/
│   ├── auth.py                 # 扫码登录服务
│   ├── storage.py              # 用户存储与旧数据兼容
│   ├── message.py              # 登录消息与撤回逻辑
│   ├── arknights.py            # 公告等无需绑定的基础查询
│   ├── material.py             # 一图流材料掉率
│   ├── recruit.py              # PRTS 公招查询
│   ├── gacha.py                # 鹰角官网抽卡记录
│   └── render.py               # HTML 到图片渲染
├── resources/                  # HTML / CSS 模板与静态资源
├── docs/preview/               # README 使用的功能预览图
└── scripts/generate_preview.py # 重新生成预览图的测试脚本
```

## 预览图与功能测试

仓库提供了可复用的截图生成脚本：

```bash
$env:SKLAND_TOKEN="你的森空岛token"
python scripts/generate_preview.py
```

执行后会：

- 进行一次真实签到链路检查
- 拉取明日方舟角色数据
- 渲染便签、公告、材料、公招、肉鸽、抽卡记录图片
- 输出测试报告到 `docs/preview/test-report.json`
- 自动将 README 预览图压缩到更适合文档展示的尺寸

## 当前已实现的重点能力

- 森空岛扫码绑定与手动 token 登录双通道
- 明日方舟与终末地签到
- 公告列表与公告正文截图
- 一图流网站截图版材料掉率与刷图推荐
- 公招查询与持有状态标记
- 集成战略进度图
- 抽卡记录、指定卡池筛选与抽卡分析
- 便签扩展字段：头像、线索、公招完成状态、收藏数

## 致谢

- 森空岛官方接口与 Hypergryph 相关公开服务
- [arknights-plugin](https://github.com/gxy12345/arknights-plugin) 提供了不少功能设计上的参考
- [astrbot_plugin_endfield](https://github.com/Entropy-Increase-Team/astrbot_plugin_endfield) 提供了账号流程与渲染结构上的参考
