use breezy_osutils::textfile::check_text_path;
use std::ffi::OsString;
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

pub enum Error {
    PatchInvokeError(
        String,
        String,
        Option<Box<dyn std::error::Error + Send + Sync>>,
    ),
    PatchFailed(i32, String),
    BinaryFile(std::path::PathBuf),
    Io(std::io::Error),
}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e)
    }
}

/// Invoke a command with the given arguments, passing `input` to its stdin.
fn write_to_cmd<'a, I>(
    command: &str,
    args: &[OsString],
    input: I,
) -> std::io::Result<(Vec<u8>, Vec<u8>, i32)>
where
    I: IntoIterator<Item = &'a [u8]>,
{
    let mut cmd = Command::new(command);
    cmd.args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = cmd.spawn()?;
    if let Some(mut stdin) = child.stdin.take() {
        for chunk in input {
            stdin.write_all(chunk)?;
        }
    }
    let output = child.wait_with_output()?;
    let stdout = output.stdout;
    let stderr = output.stderr;
    let status = output.status.code().unwrap_or(-1);
    Ok((stdout, stderr, status))
}

/// Apply a three-way merge using `diff3`.
pub fn diff3(
    out_file: &Path,
    mine_path: &Path,
    older_path: &Path,
    yours_path: &Path,
) -> Result<i32, Error> {
    fn add_label(args: &mut Vec<OsString>, label: &str) {
        args.extend(vec!["-L".into(), label.into()]);
    }
    for path in [mine_path, older_path, yours_path] {
        if !check_text_path(path)? {
            return Err(Error::BinaryFile(path.to_path_buf()));
        }
    }
    let mut args = vec!["-E".into(), "--merge".into()];
    add_label(&mut args, "TREE");
    add_label(&mut args, "ANCESTOR");
    add_label(&mut args, "MERGE-SOURCE");
    args.extend(vec![mine_path.into(), older_path.into(), yours_path.into()]);
    let (output, stderr, status) = write_to_cmd("diff3", &args, std::iter::once::<&[u8]>(&[]))?;
    if status != 0 && status != 1 {
        return Err(Error::PatchInvokeError(
            format!("diff3 exited with status {}", status),
            String::from_utf8_lossy(&stderr).to_string(),
            None,
        ));
    }
    std::fs::write(out_file, output)?;
    Ok(status)
}

pub fn run_patch<'a, I>(
    directory: &Path,
    patches: I,
    strip: u32,
    reverse: bool,
    dry_run: bool,
    quiet: bool,
    target_file: Option<&str>,
    out: &mut dyn Write,
    patch_cmd: Option<&str>,
) -> Result<(), Error>
where
    I: Iterator<Item = &'a [u8]>,
{
    let mut args: Vec<OsString> = vec![
        "-d".into(),
        directory.as_os_str().into(),
        format!("-p{}", strip).into(),
        "-f".into(),
        "--reject-file=-".into(),
        "--remove-empty-files".into(),
        "--input=-".into(),
    ];
    if quiet {
        args.push("--quiet".into());
    }
    #[cfg(target_os = "windows")]
    args.push("--binary".into());
    if reverse {
        args.push("-R".into());
    }
    if dry_run {
        #[cfg(target_os = "freebsd")]
        args.push("--check".into());
        #[cfg(not(target_os = "freebsd"))]
        args.push("--dry-run".into());
    }
    if let Some(target_file) = target_file {
        args.push(target_file.into());
    }
    let mut process = Command::new(patch_cmd.unwrap_or("patch"));
    process
        .args(&args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = process
        .spawn()
        .map_err(|e| Error::PatchInvokeError(e.to_string(), String::new(), Some(Box::new(e))))?;
    if let Some(mut stdin) = child.stdin.take() {
        for patch in patches {
            stdin.write_all(patch)?;
        }
        stdin.flush()?;
    } else {
        return Err(Error::PatchInvokeError(
            "Failed to open stdin".to_string(),
            String::new(),
            None,
        ));
    }
    let output = child.wait_with_output()?;
    let status = output.status.code().unwrap_or(-1);
    assert!(output.stderr.is_empty());
    if status != 0 {
        return Err(Error::PatchFailed(
            status,
            String::from_utf8_lossy(&output.stdout).to_string(),
        ));
    }
    out.write_all(&output.stdout)?;
    Ok(())
}
