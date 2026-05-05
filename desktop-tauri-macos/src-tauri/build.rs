use std::fs;
use std::path::Path;

fn main() {
    copy_runtime_bundle();
    tauri_build::build();
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
