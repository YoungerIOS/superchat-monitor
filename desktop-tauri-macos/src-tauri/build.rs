use std::fs;
use std::path::Path;

fn main() {
    copy_runtime_bundle();
    tauri_build::build();
}

fn copy_runtime_bundle() {
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest_dir.join("../..");
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
}
