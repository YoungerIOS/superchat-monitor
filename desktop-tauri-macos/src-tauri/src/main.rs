use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use serde::Serialize;
use tauri::Manager;

const PROJECT_DIR_CACHE_FILE: &str = "project_dir.txt";
const MANAGED_VENV_DIR: &str = ".venv-desktop";
const DATA_SUBDIR: &str = "superchat-monitor";
const EMBEDDED_PYTHON_RELATIVE: &str = "bundled-python/bin/python3";

fn is_valid_runtime_dir(path: &Path) -> bool {
    path.join("monitor_ctl.sh").is_file() && path.join("monitor_tip.py").is_file()
}

fn managed_python_path(data_dir: &Path) -> PathBuf {
    data_dir.join(MANAGED_VENV_DIR).join("bin").join("python3")
}

fn embedded_python_missing_message() -> String {
    "未检测到应用内置 Python 运行时（bundled-python）。请重新安装应用或联系开发者。".to_string()
}

fn resolve_embedded_python(app: &tauri::AppHandle, runtime_dir: &Path) -> Option<PathBuf> {
    if let Ok(custom) = env::var("SUPERCHAT_EMBEDDED_PYTHON") {
        let path = PathBuf::from(custom);
        if path.is_file() {
            return Some(path);
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        let bundled = resource_dir.join(EMBEDDED_PYTHON_RELATIVE);
        if bundled.is_file() {
            return Some(bundled);
        }
    }

    // 开发模式：允许从仓库内预置的 bundled-python 调试。
    #[cfg(debug_assertions)]
    {
        let dev_candidate = runtime_dir
            .join("desktop-tauri-macos")
            .join("src-tauri")
            .join(EMBEDDED_PYTHON_RELATIVE);
        if dev_candidate.is_file() {
            return Some(dev_candidate);
        }
    }

    None
}

fn check_embedded_python_usable(python: &Path, cwd: &Path) -> Result<String, String> {
    let py_code = r#"
import platform, sys, venv
ok = sys.version_info >= (3, 9)
print(f"{sys.executable} :: Python {platform.python_version()}")
raise SystemExit(0 if ok else 2)
"#;
    let mut cmd = Command::new(python);
    cmd.args(["-c", py_code]).current_dir(cwd);
    run_command(cmd)
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
    /// 已有 venv 或可用于创建 venv 的内置 Python
    python_usable_for_bootstrap: bool,
    embedded_python_available: bool,
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
    let mut status = SetupStatus {
        ready: false,
        repo_root: None,
        data_dir: None,
        python: None,
        python_usable_for_bootstrap: false,
        embedded_python_available: false,
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

    let embedded_python = resolve_embedded_python(&app, &runtime_dir);
    status.embedded_python_available = embedded_python.is_some();
    status.python_usable_for_bootstrap = status.venv_exists || status.embedded_python_available;

    if status.venv_exists {
        status.python = Some(managed_python.display().to_string());
    } else if let Some(ref embedded) = embedded_python {
        status.python = Some(embedded.display().to_string());
        if let Err(e) = check_embedded_python_usable(embedded, &data_dir) {
            status.embedded_python_available = false;
            status.python_usable_for_bootstrap = false;
            status.message = format!("应用内置 Python 不可用（需 3.9+ 且包含 venv）：{e}");
            return status;
        }
    } else {
        status.message = embedded_python_missing_message();
        return status;
    }

    if status.venv_exists {
        status.deps_installed = check_python_deps(&managed_python, &data_dir);
        status.playwright_chromium_installed = check_playwright_chromium(&managed_python, &data_dir);
    }
    status.ready = status.venv_exists && status.deps_installed && status.playwright_chromium_installed;

    status.message = if status.ready {
        "环境已就绪，可以直接启动服务🎉".to_string()
    } else if !status.venv_exists {
        "点击【启动服务】将自动创建环境并安装依赖，完成后即可正常使用。".to_string()
    } else if !status.deps_installed {
        "虚拟环境存在，但依赖未安装完整，启动服务时会自动安装。".to_string()
    } else {
        "依赖已安装，但未检测到 Playwright Chromium，启动服务时会自动下载安装。".to_string()
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
    let embedded_python = resolve_embedded_python(app, &runtime_dir)
        .ok_or_else(embedded_python_missing_message)?;
    let mut logs: Vec<String> = Vec::new();
    logs.push(format!("运行时目录（只读）: {}", runtime_dir.display()));
    logs.push(format!("数据目录（可写）: {}", data_dir.display()));
    logs.push(format!("内置 Python: {}", embedded_python.display()));
    let py_probe = check_embedded_python_usable(&embedded_python, &data_dir)
        .map_err(|e| format!("内置 Python 不可用（需 3.9+ 且包含 venv）：{e}"))?;
    if !py_probe.is_empty() {
        logs.push(format!("内置 Python 检测通过: {}", py_probe.replace('\n', " | ")));
    }

    let req_file = runtime_dir.join("requirements.txt");
    if !req_file.is_file() {
        return Err(format!(
            "缺少 requirements.txt: {}",
            req_file.display()
        ));
    }

    let managed_python = managed_python_path(&data_dir);
    if !managed_python.is_file() {
        logs.push("使用内置 Python 创建虚拟环境...".to_string());
        let mut create_venv = Command::new(&embedded_python);
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
            open_external_url,
            app_exit,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
