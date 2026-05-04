use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use serde::Serialize;
use tauri::Manager;

const PROJECT_DIR_CACHE_FILE: &str = "project_dir.txt";
const MANAGED_VENV_DIR: &str = ".venv-desktop";
const DATA_SUBDIR: &str = "superchat-monitor";
/// 最简安装方式：官方安装包（macOS pkg），安装时勾选将 Python 加入 PATH
const PYTHON_DOWNLOAD_URL: &str = "https://www.python.org/downloads/";

fn is_valid_runtime_dir(path: &Path) -> bool {
    path.join("monitor_ctl.sh").is_file() && path.join("monitor_tip.py").is_file()
}

fn managed_python_path(data_dir: &Path) -> PathBuf {
    data_dir.join(MANAGED_VENV_DIR).join("bin").join("python3")
}

/// 用于 `python3 -m venv`：依次尝试 python3.12 / 3.11 / 3.10 / python3，排除无 venv 或版本低于 3.9 的解释器。
fn find_usable_bootstrap_python() -> Option<PathBuf> {
    let script = r#"
set -e
for c in python3.12 python3.11 python3.10 python3; do
  p=$(command -v "$c" 2>/dev/null) || continue
  if "$p" -c 'import venv, sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    printf '%s\n' "$p"
    exit 0
  fi
done
exit 1
"#;
    let output = Command::new("/bin/bash")
        .args(["-lc", script])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if text.is_empty() {
        return None;
    }
    Some(PathBuf::from(text))
}

fn python_missing_user_message() -> String {
    format!(
        "未检测到可用于创建虚拟环境的 Python 3（需要 3.9 及以上，且包含 venv 模块）。\n\n\
         推荐：点击「打开 Python 官网」，下载 macOS 官方安装包并安装；安装末尾请勾选「Install or add Python to PATH」（将 Python 加入 PATH）。\n\n\
         安装完成后请完全退出并重新打开本应用，再点击「安装依赖」。\n\n\
         下载页：{PYTHON_DOWNLOAD_URL}"
    )
}

fn python_bootstrap_install_error() -> String {
    python_missing_user_message()
}

fn run_command(mut cmd: Command) -> Result<String, String> {
    let output = cmd.output().map_err(|e| format!("执行失败: {e}"))?;

    let mut text = String::new();
    text.push_str(&String::from_utf8_lossy(&output.stdout));
    text.push_str(&String::from_utf8_lossy(&output.stderr));
    let trimmed = text.trim().to_string();

    if output.status.success() {
        Ok(trimmed)
    } else if trimmed.is_empty() {
        Err(format!("命令失败，退出码: {:?}", output.status.code()))
    } else {
        Err(trimmed)
    }
}

fn cache_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    let mut dir = app.path().app_config_dir().ok()?;
    dir.push(PROJECT_DIR_CACHE_FILE);
    Some(dir)
}

fn load_cached_runtime_dir(app: &tauri::AppHandle) -> Option<PathBuf> {
    let path = cache_path(app)?;
    let text = fs::read_to_string(path).ok()?;
    let candidate = PathBuf::from(text.trim());
    if is_valid_runtime_dir(&candidate) {
        Some(candidate)
    } else {
        None
    }
}

fn persist_runtime_dir(app: &tauri::AppHandle, root: &Path) {
    let Some(path) = cache_path(app) else {
        return;
    };
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let normalized = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
    let _ = fs::write(path, format!("{}\n", normalized.display()));
}

fn bundled_runtime_dir(app: &tauri::AppHandle) -> Option<PathBuf> {
    let res = app.path().resource_dir().ok()?;
    let bundled = res.join("bundled-runtime");
    if is_valid_runtime_dir(&bundled) {
        Some(bundled)
    } else {
        None
    }
}

fn dev_repo_runtime_dir() -> Option<PathBuf> {
    #[cfg(debug_assertions)]
    {
        let live = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        if is_valid_runtime_dir(&live) {
            return Some(live);
        }
    }
    None
}

fn resolve_runtime_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if let Ok(custom_dir) = env::var("SUPERCHAT_PROJECT_DIR") {
        let path = PathBuf::from(custom_dir);
        if is_valid_runtime_dir(&path) {
            persist_runtime_dir(app, &path);
            return Ok(path);
        }
        return Err(format!(
            "SUPERCHAT_PROJECT_DIR 无效（需要 monitor_ctl.sh 与 monitor_tip.py）: {}",
            path.display()
        ));
    }

    if let Some(path) = dev_repo_runtime_dir() {
        persist_runtime_dir(app, &path);
        return Ok(path);
    }

    if let Some(path) = bundled_runtime_dir(app) {
        return Ok(path);
    }

    if let Some(path) = load_cached_runtime_dir(app) {
        return Ok(path);
    }

    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = env::current_dir() {
        candidates.push(cwd);
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(p) = exe.parent() {
            candidates.push(p.to_path_buf());
        }
    }
    #[cfg(debug_assertions)]
    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")));

    for base in candidates {
        if let Some(found) = search_up_for_runtime(&base) {
            persist_runtime_dir(app, &found);
            return Ok(found);
        }
    }

    Err(
        "未找到监控运行时。若使用 DMG 安装版，请重新安装或联系开发者；也可设置 SUPERCHAT_PROJECT_DIR。"
            .to_string(),
    )
}

fn search_up_for_runtime(start: &Path) -> Option<PathBuf> {
    let mut cur = Some(start.to_path_buf());
    while let Some(path) = cur {
        if is_valid_runtime_dir(&path) {
            return Some(path);
        }
        cur = path.parent().map(|p| p.to_path_buf());
    }
    None
}

/// 发布包：可写数据在 Application Support。开发且运行时指向仓库根时与仓库共用目录，便于调试。
fn resolve_effective_data_dir(
    app: &tauri::AppHandle,
    _runtime_dir: &Path,
) -> Result<PathBuf, String> {
    #[cfg(debug_assertions)]
    {
        let runtime_dir = _runtime_dir;
        if let (Ok(rt), Ok(lv)) = (
            runtime_dir.canonicalize(),
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../..")
                .canonicalize(),
        ) {
            if rt == lv {
                return Ok(rt);
            }
        }
    }

    let mut dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("无法解析本机数据目录: {e}"))?;
    dir.push(DATA_SUBDIR);
    fs::create_dir_all(&dir).map_err(|e| format!("无法创建数据目录: {e}"))?;
    Ok(dir)
}

fn run_ctl(app: &tauri::AppHandle, args: &[&str]) -> Result<String, String> {
    let runtime_dir = resolve_runtime_dir(app)?;
    let data_dir = resolve_effective_data_dir(app, &runtime_dir)?;
    let script = runtime_dir.join("monitor_ctl.sh");
    let managed_python = managed_python_path(&data_dir);

    let mut cmd = Command::new("/bin/bash");
    cmd.arg(script)
        .args(args)
        .current_dir(&data_dir)
        .env("SUPERCHAT_RUNTIME_DIR", &runtime_dir)
        .env("SUPERCHAT_DATA_DIR", &data_dir);
    if managed_python.is_file() {
        cmd.env("SUPERCHAT_PYTHON", managed_python);
    }
    run_command(cmd)
}

#[tauri::command]
fn service_status(app: tauri::AppHandle) -> Result<String, String> {
    run_ctl(&app, &["status"])
}

#[tauri::command]
fn service_start(app: tauri::AppHandle) -> Result<String, String> {
    run_ctl(&app, &["start"])
}

#[tauri::command]
fn service_stop(app: tauri::AppHandle) -> Result<String, String> {
    run_ctl(&app, &["stop"])
}

#[tauri::command]
fn service_restart(app: tauri::AppHandle) -> Result<String, String> {
    run_ctl(&app, &["restart"])
}

#[tauri::command]
fn service_open_panel(_app: tauri::AppHandle) -> Result<String, String> {
    let url = "http://localhost:17865";

    Command::new("/usr/bin/open")
        .arg(url)
        .status()
        .map_err(|e| format!("打开面板失败: {e}"))?;

    Ok(format!("已打开: {url}"))
}

#[tauri::command]
fn service_open_log(app: tauri::AppHandle) -> Result<String, String> {
    let runtime_dir = resolve_runtime_dir(&app)?;
    let data_dir = resolve_effective_data_dir(&app, &runtime_dir)?;
    let log_path = data_dir.join("superchat-monitor.log");

    Command::new("/usr/bin/open")
        .arg(&log_path)
        .status()
        .map_err(|e| format!("打开日志失败: {e}"))?;

    Ok(format!("已打开日志: {}", log_path.display()))
}

#[tauri::command]
fn app_exit(app: tauri::AppHandle) {
    app.exit(0);
}

fn open_https_url(url: &str) -> Result<(), String> {
    let u = url.trim();
    if !u.starts_with("https://") {
        return Err("仅允许打开 https 链接。".to_string());
    }
    if cfg!(target_os = "macos") {
        Command::new("/usr/bin/open")
            .arg(u)
            .status()
            .map_err(|e| format!("打开浏览器失败: {e}"))?;
        Ok(())
    } else {
        Err("当前构建仅支持在 macOS 上通过系统浏览器打开链接。".to_string())
    }
}

#[tauri::command]
fn open_python_downloads() -> Result<String, String> {
    open_https_url(PYTHON_DOWNLOAD_URL)?;
    Ok(format!("已在浏览器中打开: {PYTHON_DOWNLOAD_URL}"))
}

/// 供前端说明区外链使用（WebView 默认不会打开 `target="_blank"`）。
#[tauri::command]
fn open_external_url(url: String) -> Result<String, String> {
    open_https_url(&url)?;
    Ok(format!("已在浏览器中打开: {}", url.trim()))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SetupStatus {
    ready: bool,
    repo_root: Option<String>,
    data_dir: Option<String>,
    python: Option<String>,
    /// 已有 venv 或本机存在可用于执行 `python3 -m venv` 的解释器
    python_usable_for_bootstrap: bool,
    python_download_url: String,
    venv_exists: bool,
    deps_installed: bool,
    playwright_chromium_installed: bool,
    message: String,
}

fn check_python_deps(python: &Path, cwd: &Path) -> bool {
    let mut cmd = Command::new(python);
    cmd.args([
        "-c",
        "import aiohttp,aiohttp_socks,nicegui,playwright,requests;print('ok')",
    ])
    .current_dir(cwd);
    run_command(cmd).is_ok()
}

fn check_playwright_chromium(python: &Path, cwd: &Path) -> bool {
    let py_code = r#"
import os
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    path = p.chromium.executable_path
    print(path)
    raise SystemExit(0 if os.path.exists(path) else 2)
"#;
    let mut cmd = Command::new(python);
    cmd.args(["-c", py_code]).current_dir(cwd);
    run_command(cmd).is_ok()
}

#[tauri::command]
fn setup_check(app: tauri::AppHandle) -> SetupStatus {
    let dl = PYTHON_DOWNLOAD_URL.to_string();
    let mut status = SetupStatus {
        ready: false,
        repo_root: None,
        data_dir: None,
        python: None,
        python_usable_for_bootstrap: false,
        python_download_url: dl.clone(),
        venv_exists: false,
        deps_installed: false,
        playwright_chromium_installed: false,
        message: String::new(),
    };

    let runtime_dir = match resolve_runtime_dir(&app) {
        Ok(path) => path,
        Err(e) => {
            status.message = e;
            return status;
        }
    };
    status.repo_root = Some(runtime_dir.display().to_string());

    let data_dir = match resolve_effective_data_dir(&app, &runtime_dir) {
        Ok(path) => path,
        Err(e) => {
            status.message = e;
            return status;
        }
    };
    status.data_dir = Some(data_dir.display().to_string());

    let managed_python = managed_python_path(&data_dir);
    status.venv_exists = managed_python.is_file();

    let python_path: PathBuf = if status.venv_exists {
        status.python_usable_for_bootstrap = true;
        status.python = Some(managed_python.display().to_string());
        managed_python
    } else {
        let Some(sys_py) = find_usable_bootstrap_python() else {
            status.python_usable_for_bootstrap = false;
            status.python = None;
            status.message = python_missing_user_message();
            return status;
        };
        status.python_usable_for_bootstrap = true;
        status.python = Some(sys_py.display().to_string());
        sys_py
    };

    status.deps_installed = check_python_deps(&python_path, &data_dir);
    status.playwright_chromium_installed = check_playwright_chromium(&python_path, &data_dir);
    status.ready = status.venv_exists && status.deps_installed && status.playwright_chromium_installed;

    status.message = if status.ready {
        "环境已就绪，可以直接启动服务。".to_string()
    } else if !status.venv_exists {
        "本机 Python 可用于创建虚拟环境。请点击「安装依赖」安装依赖与 Chromium。".to_string()
    } else if !status.deps_installed {
        "虚拟环境存在，但依赖未安装完整，建议点击「安装依赖」。".to_string()
    } else {
        "依赖已安装，但未检测到 Playwright Chromium，建议点击「安装依赖」。".to_string()
    };
    status
}

#[tauri::command]
async fn setup_install(app: tauri::AppHandle) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || setup_install_blocking(&app))
        .await
        .map_err(|e| format!("安装任务异常: {e}"))?
}

fn setup_install_blocking(app: &tauri::AppHandle) -> Result<String, String> {
    let runtime_dir = resolve_runtime_dir(app)?;
    let data_dir = resolve_effective_data_dir(app, &runtime_dir)?;
    let mut logs: Vec<String> = Vec::new();
    logs.push(format!("运行时目录（只读）: {}", runtime_dir.display()));
    logs.push(format!("数据目录（可写）: {}", data_dir.display()));

    let req_file = runtime_dir.join("requirements.txt");
    if !req_file.is_file() {
        return Err(format!(
            "缺少 requirements.txt: {}",
            req_file.display()
        ));
    }

    let managed_python = managed_python_path(&data_dir);
    if !managed_python.is_file() {
        let bootstrap = find_usable_bootstrap_python().ok_or_else(python_bootstrap_install_error)?;
        logs.push(format!("使用系统 Python 创建虚拟环境: {}", bootstrap.display()));
        let mut create_venv = Command::new(&bootstrap);
        create_venv
            .args(["-m", "venv", MANAGED_VENV_DIR])
            .current_dir(&data_dir);
        let out = run_command(create_venv)?;
        if !out.is_empty() {
            logs.push(out);
        }
    } else {
        logs.push(format!("已检测到虚拟环境: {}", managed_python.display()));
    }

    if !managed_python.is_file() {
        return Err(format!(
            "{}\n虚拟环境创建完成后仍未找到 Python: {}",
            logs.join("\n"),
            managed_python.display()
        ));
    }

    logs.push("安装/升级 pip...".to_string());
    let mut pip_upgrade = Command::new(&managed_python);
    pip_upgrade
        .args(["-m", "pip", "install", "--upgrade", "pip"])
        .current_dir(&data_dir);
    let out = run_command(pip_upgrade)?;
    if !out.is_empty() {
        logs.push(out);
    }

    logs.push("安装 requirements.txt 依赖...".to_string());
    let req_str = req_file
        .to_str()
        .ok_or_else(|| "requirements.txt 路径无效".to_string())?
        .to_string();
    let mut pip_install = Command::new(&managed_python);
    pip_install
        .args(["-m", "pip", "install", "-r", &req_str])
        .current_dir(&data_dir);
    let out = run_command(pip_install)?;
    if !out.is_empty() {
        logs.push(out);
    }

    logs.push("安装 Playwright Chromium（首次会较慢）...".to_string());
    let mut pw_install = Command::new(&managed_python);
    pw_install
        .args(["-m", "playwright", "install", "chromium"])
        .current_dir(&data_dir);
    let out = run_command(pw_install)?;
    if !out.is_empty() {
        logs.push(out);
    }

    logs.push("安装依赖完成。现在可以点击「启动服务」。".to_string());
    Ok(logs.join("\n"))
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            service_status,
            service_start,
            service_stop,
            service_restart,
            service_open_panel,
            service_open_log,
            setup_check,
            setup_install,
            open_python_downloads,
            open_external_url,
            app_exit,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
