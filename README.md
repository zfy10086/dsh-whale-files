# 鲸鲸文件箱 · dsh-whale-files 🐳

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![node](https://img.shields.io/badge/node-%5E22.19%20%7C%7C%20%3E%3D24-brightgreen.svg)](package.json)
[![platform](https://img.shields.io/badge/platform-Android%20%C2%B7%20DSHA-3ddc84.svg)](#运行前提)
[![python](https://img.shields.io/badge/python-3.x-3572A5.svg)](#运行前提)

> 给**手机端 DSHA** 用户的文件箱：**不给 root 权限**，也能把手机里的文件交给 AI、把 AI 做出来的东西拿回手机。

作者：**zfy10086**

---

## 目录

- [这个插件为什么存在](#这个插件为什么存在)
- [功能](#功能)
- [截图](#截图)
- [安装](#安装)
- [使用](#使用)
- [配置](#配置)
- [架构](#架构)
- [安全说明](#安全说明)
- [已知限制](#已知限制)
- [常见问题](#常见问题)
- [开发](#开发)
- [更新日志](#更新日志)
- [License](#license)

## 这个插件为什么存在

Android 11 以后，应用默认只能看到**自己创建的文件**——即使容器里挂着 `/storage/emulated/0`，也只会露出一个"目录骨架"，别人（包括用户用文件管理器放进去）的文件一律不可见。

想突破只有几条路，都不理想：

| 方案 | 问题 |
|---|---|
| 开「所有文件访问权限」 | 权限过重；部分 ROM 的开关是个壳，开了也不落地；Android 13+ 连入口都换了位置 |
| root / Shizuku 走 shell | 需要刷机或额外装东西，普通用户折腾不起 |
| 每次连电脑用 adb push | 离开了「在手机上随手用 AI」的意义 |

**鲸鲸文件箱的思路：绕开 Android 存储权限，走浏览器 HTTP 通道。**

手机浏览器本来就能访问 `127.0.0.1`，而 DSHA 的 Web GUI 就监听在这里。于是：

- **手机 → 容器**：浏览器上传（HTTP POST），不需要任何存储权限；
- **容器 → 手机**：调用 DSHA 的设备桥 `/app/export`，直接落到 `Download/DSHA/`；
- **整目录**：压缩成 zip 一次传，服务端自动解压到同名文件夹。

全程不碰 Android 的存储权限，也不用 root。

---

## 功能

### 传输

- **上传文件**：多选
- **上传 zip（整个文件夹）**：自动解压到**以压缩包命名的文件夹**里，保留目录结构、支持中文文件名、兼容 GBK 编码的国产压缩包
- **存手机**：把容器里的文件/目录投到手机 `Download/DSHA/`。**对目录会自动打包成 zip 再投递，压缩包只是临时文件——投递成功后立刻删除**，手机侧只多出一个 zip；不依赖浏览器下载，所以在 App 内嵌页面里也能用
- 上传失败可**单文件重试**；上传中显示百分比、速度、剩余时间、总进度

### 管理

- 浏览目录（面包屑 + **容器真实绝对路径**，可一键复制）
- 新建文件夹、重命名、删除
- **移动文件/文件夹**（可同时改名，如 `归档/2026年/新名字.txt`）
- 在线预览：图片直接显示，文本（md/json/代码等）在弹窗里看
- 顶部「整目录存手机」：把当前所在目录整个打包投递到手机

### 稳定性

- 页内含**心跳状态灯**（已连接 · 版本 · 运行时长），断线可点一下重连，恢复后自动刷新
- 当前目录记在 `localStorage` + URL hash，**刷新不会把你丢回根目录**
- 宿主半每 5 秒探活引擎，挂了自动拉起；引擎生命周期跟随 DSH 宿主，App 重启后自动回来

---

## 截图

> 截图位（把图片放到 `docs/` 下替换即可）：
>
> | 设置里的入口 | 文件箱页面 |
> |---|---|
> | `docs/settings.png` | `docs/panel.png` |

---

## 安装

### 方式一：插件栏安装（推荐）

在 DSHA 的插件栏输入：

```
github:zfy10086/dsh-whale-files
```

安装后**重启一次 DSHA App**（插件清单在启动时加载）。

### 方式二：本地 link

```bash
git clone https://github.com/zfy10086/dsh-whale-files
cd ~/.dsh/profiles/web
npm pkg set dependencies.dsh-whale-files="link:/path/to/dsh-whale-files"
```

再把 `dsh-whale-files` 加入 `package.json` 的 `dsh.profile.bundles` 数组，重启 App。

### 运行前提

| 依赖 | 说明 |
|---|---|
| Node.js | `^22.19.0 || >=24.0.0`（DSH 自带） |
| **Python 3** | 引擎用标准库实现，无需 pip 安装任何包。DSHA 的 Ubuntu 容器自带 |
| DSHA App | 需要带设备桥的版本（`/app/help` 可用）；「存手机」依赖 `/app/export` |
| 端口 | 默认 `127.0.0.1:8791`（引擎），可用 `WHALE_FILES_PORT` 改 |

---

## 使用

1. 打开 DSHA → **设置** → 底部 **「鲸鲸文件箱」**
2. 页面就是当前工作区（默认 `~/Documents/deepseek-harness/default-workspace`）
3. 传文件：点「上传文件」
4. 传整个文件夹：在 MT 管理器里长按文件夹 →「压缩」→ 回来点「上传 zip」
5. 把成品拿回手机：文件行点「存手机」，或点顶部「整目录存手机」，成品会出现在手机 `Download/DSHA/`

> 安卓浏览器普遍不支持"直接选文件夹"（`webkitdirectory` 未实现），所以整目录统一走 zip——这是刻意的设计，不是缺陷。

---

## 配置

全部通过环境变量，改完重启 App 生效：

| 变量 | 默认 | 作用 |
|---|---|---|
| `WHALE_FILES_ROOT` | DSHA 默认工作区 | 文件箱管理的根目录 |
| `WHALE_FILES_PORT` | `8791` | 引擎监听端口（只绑 127.0.0.1） |
| `WHALE_FILES_DIR` | 包内 `engine/` | 引擎目录（一般不用改） |
| `WHALE_FILES_BRIDGE_HEADERS` | `/root/.dsh/.bridge_headers` | 设备桥凭据文件（「存手机」用） |

---

## 架构

```
浏览器 / 设置页 iframe
        │  同源，走 3080
        ▼
DSH 宿主 (node)  ── lib/index.js（宿主半）
        │           • 注册 /whale-files 路由并反代
        │           • 每 5 秒探活引擎，挂了就拉起
        ▼
Python 引擎 (engine/files.py, 127.0.0.1:8791)
        │   • multipart 流式解析 / zip 解压 / 打包 / 移动 / 删除
        │   • 路径 realpath 限制在根目录内
        ▼
工作区目录
        │
        └─「存手机」──► DSHA 设备桥 127.0.0.1:3090 /app/export ──► Download/DSHA/
```

**为什么插件本体这么薄**：multipart 流式解析、zip-slip 防护、GBK 文件名修复这些细节在 Python 标准库里几行就能写稳，而且不引入任何 npm 依赖；Node 侧只做反代与保活，升级、调试都简单。

### 目录结构

```
dsh-whale-files/
├── package.json
├── cordis.patch.yml      # 自注册：把插件插入 loader 层栈
├── lib/
│   ├── index.js          # 宿主半：路由 + 反代 + 引擎保活
│   └── client.js         # 客户端半：设置页「鲸鲸文件箱」
├── engine/
│   ├── files.py          # Python 引擎（HTTP + 文件操作）
│   └── page.html         # 文件箱页面（单文件，无构建）
├── README.md
└── LICENSE
```

---

## 安全说明

- 引擎**只监听 `127.0.0.1`**，局域网/外网访问不到；
- 所有路径都经过 `realpath` 校验，**禁止越出根目录**（`..`、绝对路径注入都会被拒）；
- zip 解压做 **zip-slip 防护**，成员路径不会写到目标文件夹之外；
- 「存手机」只调用 DSHA 自己的设备桥，**不直接写入手机存储**；
- 页面无构建、无第三方 CDN、无遥测。

---

## 已知限制

- **安卓浏览器不能选文件夹** → 整目录请用 zip；
- **App 内嵌 iframe 里浏览器下载可能被拦** → 用「存手机」；
- **只测过 Android + DSHA**，Windows/macOS 上的 DSH 未验证（该场景本来也不需要它）；
- 「存手机」依赖 DSHA 设备桥，普通 DSH 桌面版没有这个通道，会提示失败，但不影响其它功能；
- 没有用户体系与鉴权——它的安全边界就是"只在本机回环地址上"。

---

## 常见问题

**Q：设置里没有「鲸鲸文件箱」？**
A：先确认插件已安装并出现在插件列表；改过 `package.json` 的话必须**重启 App**（插件清单在启动时加载）。

**Q：首开页面一片黑，点刷新才好？**
A：0.1.0 已修（延迟设置 iframe 地址 + 载入中占位 + 4 秒自动重载一次 + 引擎侧 `no-store`）。若仍出现，点插件右上角「刷新」。

**Q：上传完文件跑到根目录、乱七八糟？**
A：旧版本会"拍平"同名顶层目录；0.1.0 起**永远解压到以压缩包命名的文件夹里**。

**Q：能不能不装 Python？**
A：引擎是 Python 标准库实现，DSHA 容器自带。若环境没有 python3，插件日志会报"引擎未就绪"。

---

## 开发

```bash
# 只跑引擎（不装插件也能用，浏览器开 127.0.0.1:8791）
cd engine
ROOT=/path/to/workspace python3 files.py

# 整套（需要 DSH 宿主）
# 把包装进 profile 的 dependencies + bundles，然后重启 dsh web
```

引擎没有第三方依赖，`page.html` 是手写的单文件 SPA。注意页面在引擎启动时读入内存，改完 `page.html` 需要重启引擎。

---

## 更新日志

**0.1.1**
- 界面精简：去掉独立的「下载」「打包」按钮——「存手机」已覆盖（目录自动打 zip，临时包投递后自动删除）
- 引擎随包分发（`engine/`），不再依赖外部 `/root/upload-server`
- 修复：zip 一律解压到以压缩包命名的文件夹，不再把同名顶层目录"拍平"导致文件散落
- 修复：`/whale-files` 前缀路由匹配（webserver 的 prefix 不能带结尾斜杠）
- 优化：设置页首开不再黑屏（延迟设 iframe 地址 + 载入中占位 + 4 秒自动重载一次）；引擎响应加 `Cache-Control: no-store`
- 新增：绝对路径显示与一键复制、引擎保活（5 秒探活）

**0.1.0**
- 首个版本：上传文件 / 上传 zip 自动解压 / 移动 / 改名 / 删除 / 新建目录 / 预览 / 打包下载 / 存手机
- 绝对路径显示与复制、心跳状态灯、上传进度、断线重连、引擎保活

---

## License

MIT © zfy10086
