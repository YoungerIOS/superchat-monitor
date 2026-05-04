# SuperChat Monitor macOS Desktop (Tauri)

这是一个 macOS 桌面壳，通过 `monitor_ctl.sh` 控制后台服务。

**DMG 安装版**：应用包内自带 `monitor_tip.py`、`monitor_ctl.sh` 与 `requirements.txt`（构建时从仓库复制）。引导安装会把 **Python 虚拟环境、依赖与配置** 写到本机 `Application Support`，无需再拷贝整个仓库。每台 Mac 仍需本机已安装 **Python 3**（用于创建 venv）；Chromium 由 Playwright 下载到当前用户缓存目录。

## 功能

- 打开监控面板（`http://localhost:17865`）
- 启动 / 停止 / 重启后台服务
- 查看服务状态
- 打开日志文件

## 前置条件

- macOS 12+
- Rust toolchain（`rustup`, `cargo`）— 仅开发与自行打包时需要
- Node.js 18+ — 同上
- **终端用户**：系统已安装 **Python 3**；首次在客户端内完成「引导安装」即可

## 开发运行

```bash
cd desktop-tauri-macos
npm install
npm run dev
```

## 打包（生成 .app / .dmg）

```bash
cd desktop-tauri-macos
npm install
npm run build
```

产物默认在：

- `desktop-tauri-macos/src-tauri/target/release/bundle/macos/*.app`
- `desktop-tauri-macos/src-tauri/target/release/bundle/dmg/*.dmg`

## 运行时目录识别规则

1. 环境变量 `SUPERCHAT_PROJECT_DIR`（指向含 `monitor_tip.py` 与 `monitor_ctl.sh` 的目录）
2. **开发构建**：仓库根目录（相对 `src-tauri` 的 `../..`）
3. **发布构建**：应用包内 `Resources/bundled-runtime/`
4. 缓存路径与「当前目录 / 可执行文件向上查找」（便于从源码目录启动）

数据目录：发布版默认为 `~/Library/Application Support/<app-id>/superchat-monitor/`（venv、`streamers.json`、日志）；从源码 `npm run dev` 时若运行时指向仓库根，则与仓库共用目录。

高级用户仍可设置：

```bash
export SUPERCHAT_PROJECT_DIR="/path/to/superchat-monitor"
```
