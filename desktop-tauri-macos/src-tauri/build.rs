use std::fs;
use std::path::{Path, PathBuf};

fn main() {
    with_bundle_copy_lock(env!("CARGO_MANIFEST_DIR"), copy_runtime_bundle);
    clear_tauri_resource_staging();
    tauri_build::build();
}

/// Universal builds compile aarch64 and x86_64 in parallel; both run this build script.
/// Without a lock they race on `bundled-python/` and fail with "Permission denied".
#[cfg(unix)]
fn with_bundle_copy_lock(manifest_dir: &str, f: fn()) {
    use std::fs::OpenOptions;
    use std::os::unix::io::AsRawFd;

    let lock_path = PathBuf::from(manifest_dir).join(".bundle-copy.lock");
    let file = OpenOptions::new()
        .create(true)
        .write(true)
        .open(&lock_path)
        .expect("open bundle copy lock");
    let fd = file.as_raw_fd();
    let rc = unsafe { libc::flock(fd, libc::LOCK_EX) };
    if rc != 0 {
        panic!("flock bundle copy lock: {}", std::io::Error::last_os_error());
    }
    f();
    let rc = unsafe { libc::flock(fd, libc::LOCK_UN) };
    if rc != 0 {
        panic!("unlock bundle copy lock: {}", std::io::Error::last_os_error());
    }
}

#[cfg(not(unix))]
fn with_bundle_copy_lock(_manifest_dir: &str, f: fn()) {
    f();
}

fn copy_runtime_bundle() {
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest_dir.join("../..");
    let desktop_root = manifest_dir.join("..");
    let out_dir = manifest_dir.join("bundled-runtime");

    for name in ["monitor_tip.py", "monitor_ctl.sh", "requirements.txt"] {
        let src = repo_root.join(name);
        println!("cargo:rerun-if-changed={}", src.display());
        if !src.is_file() {
            panic!(
                "SuperChat runtime file missing: {} (expected repo layout: superchat-monitor/{})",
                src.display(),
                name
            );
        }
    }

    let _ = fs::remove_dir_all(&out_dir);
    fs::create_dir_all(&out_dir).expect("create bundled-runtime");

    for name in ["monitor_tip.py", "monitor_ctl.sh", "requirements.txt"] {
        let src = repo_root.join(name);
        let dst = out_dir.join(name);
        fs::copy(&src, &dst).unwrap_or_else(|e| panic!("copy {}: {e}", src.display()));
    }

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let ctl = out_dir.join("monitor_ctl.sh");
        let mut perms = fs::metadata(&ctl)
            .expect("monitor_ctl metadata")
            .permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&ctl, perms).expect("chmod monitor_ctl");
    }

    let bundled_python_src = desktop_root.join("bundled-python");
    let bundled_python_dst = manifest_dir.join("bundled-python");
    let _ = fs::remove_dir_all(&bundled_python_dst);
    if bundled_python_src.is_dir() {
        copy_dir_recursive(&bundled_python_src, &bundled_python_dst)
            .unwrap_or_else(|e| panic!("copy bundled-python: {e}"));
        normalize_tree_permissions(&bundled_python_dst);
        let py = bundled_python_dst.join("bin").join("python3");
        if is_release_build() && !py.is_file() {
            panic!(
                "bundled-python is missing required executable: {}",
                py.display()
            );
        } else if !py.is_file() {
            println!(
                "cargo:warning=bundled-python missing bin/python3 (dev mode): {}",
                py.display()
            );
        }
    } else {
        if is_release_build() {
            panic!(
                "release build requires bundled-python directory: {}",
                bundled_python_src.display()
            );
        } else {
            println!(
                "cargo:warning=bundled-python directory not found: {}",
                bundled_python_src.display()
            );
        }
    }
}

fn is_release_build() -> bool {
    std::env::var("PROFILE").ok().as_deref() == Some("release")
}

/// Tauri copies resources into `target/<triple>/<profile>/`. Leftover read-only files
/// (555 from the Python.org framework) make `fs::copy` fail on rebuild.
fn clear_tauri_resource_staging() {
    let Ok(out_dir) = std::env::var("OUT_DIR") else {
        return;
    };
    let mut target_dir = PathBuf::from(out_dir);
    for _ in 0..3 {
        let Some(parent) = target_dir.parent() else {
            return;
        };
        target_dir = parent.to_path_buf();
    }
    for name in ["bundled-python", "bundled-runtime"] {
        let _ = fs::remove_dir_all(target_dir.join(name));
    }
}

#[cfg(unix)]
fn normalize_tree_permissions(root: &Path) {
    use std::os::unix::fs::PermissionsExt;

    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Ok(meta) = entry.metadata() else {
            continue;
        };
        if meta.is_dir() {
            let mut perms = meta.permissions();
            perms.set_mode(0o755);
            let _ = fs::set_permissions(&path, perms);
            normalize_tree_permissions(&path);
        } else if meta.is_file() {
            let mut perms = meta.permissions();
            let mode = if perms.mode() & 0o111 != 0 {
                0o755
            } else {
                0o644
            };
            perms.set_mode(mode);
            let _ = fs::set_permissions(&path, perms);
        }
    }
}

#[cfg(not(unix))]
fn normalize_tree_permissions(_root: &Path) {}

fn copy_dir_recursive(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let file_type = entry.file_type()?;
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        if file_type.is_dir() {
            copy_dir_recursive(&src_path, &dst_path)?;
        } else if file_type.is_file() {
            fs::copy(&src_path, &dst_path)?;
        } else if file_type.is_symlink() {
            let target = fs::canonicalize(&src_path)?;
            if target.is_dir() {
                copy_dir_recursive(&target, &dst_path)?;
            } else {
                fs::copy(&target, &dst_path)?;
            }
        }
    }
    Ok(())
}
