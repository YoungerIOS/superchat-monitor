# SuperChat Monitor macOS Desktop (Tauri)

这是一个 macOS 桌面壳，通过 `monitor_ctl.sh` 控制后台服务。

**DMG 安装版**：应用包内自带 `monitor_tip.py`、`monitor_ctl.sh`、`requirements.txt` 与最小 Python 运行时（`bundled-python`）。引导安装会把 **Python 虚拟环境、依赖与配置** 写到本机 `Application Support`，无需再拷贝整个仓库。首次点击「启动服务」时会自动检测环境并按需下载安装 Chromium。

## 功能

- 打开监控面板（`http://localhost:17865`）
- 启动 / 停止 / 重启后台服务
- 查看服务状态
- 打开日志文件

## 前置条件

- macOS 12+
- Rust toolchain（`rustup`, `cargo`）— 仅开发与自行打包时需要
- Node.js 18+ — 同上
- **终端用户**：不需要系统 Python（由应用内置 `bundled-python` 提供）

## 内置 Python 准备（打包前必做）

将最小 Python 运行时放到：

- `desktop-tauri-macos/bundled-python/bin/python3`

构建脚本会将该目录复制到 `src-tauri/bundled-python` 并打入安装包。  
发布构建（release）时若缺少 `bundled-python` 或缺少 `bin/python3` 会直接失败。

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

## 首次使用流程（终端用户）

1. 打开应用，状态区会显示环境检测结果（内置 Python / venv / 依赖 / Chromium）。
2. 点击「启动服务」：
   - 若环境就绪：直接启动。
   - 若环境未就绪：自动执行依赖与 Chromium 安装，并在状态区显示进度。
3. 安装完成后自动启动服务，再点击「打开面板」访问 `http://localhost:17865`。
