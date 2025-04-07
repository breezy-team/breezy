use core::ops::BitAnd;
use log::debug;
#[cfg(unix)]
use nix::sys::stat::SFlag;
use std::fs::{set_permissions, symlink_metadata, Permissions};
use std::io::Read;
use std::io::Result;
use std::path::Path;
use walkdir::WalkDir;

pub fn make_writable<P: AsRef<Path>>(path: P) -> Result<()> {
    let path = path.as_ref();
    let metadata = std::fs::symlink_metadata(path)?;
    let mut permissions = metadata.permissions();
    if !metadata.file_type().is_symlink() {
        permissions.set_readonly(false);
        set_permissions(path, permissions)?;
    }
    Ok(())
}

pub fn make_readonly<P: AsRef<Path>>(path: P) -> Result<()> {
    let path = path.as_ref();
    let metadata = std::fs::symlink_metadata(path)?;
    let mut permissions = metadata.permissions();
    if !metadata.file_type().is_symlink() {
        permissions.set_readonly(true);
        set_permissions(path, permissions)?;
    }
    Ok(())
}

pub fn chmod_if_possible<P: AsRef<Path>>(path: P, permissions: Permissions) -> Result<()> {
    // Set file mode if that can be safely done.
    // Sometimes even on unix the filesystem won't allow it - see
    // https://bugs.launchpad.net/bzr/+bug/606537
    if let Err(e) = set_permissions(path.as_ref(), permissions) {
        // Permission/access denied seems to commonly happen on smbfs; there's
        // probably no point warning about it.
        // <https://bugs.launchpad.net/bzr/+bug/606537>
        match e.kind() {
            std::io::ErrorKind::PermissionDenied => {
                debug!("ignore error on chmod of {:?}: {:?}", path.as_ref(), e);
                Ok(())
            }
            _ => Err(e),
        }
    } else {
        Ok(())
    }
}

#[cfg(unix)]
pub fn copy_ownership_from_path<P: AsRef<Path>>(dst: P, src: Option<&Path>) -> Result<()> {
    use nix::unistd::{chown, Gid, Uid};

    use std::os::unix::fs::MetadataExt;

    let mut src = match src {
        Some(p) => p,
        None => dst.as_ref().parent().unwrap_or_else(|| Path::new(".")),
    };

    if src == Path::new("") {
        src = Path::new(".");
    }

    let s = std::fs::metadata(src)?;
    let uid = s.uid();
    let gid = s.gid();

    if let Err(err) = chown(
        dst.as_ref(),
        Some(Uid::from_raw(uid)),
        Some(Gid::from_raw(gid)),
    ) {
        debug!(
            "Unable to copy ownership from \"{}\" to \"{}\". \
               You may want to set it manually. {}",
            src.display(),
            dst.as_ref().display(),
            err
        );
    }
    Ok(())
}

pub fn is_dir(f: &std::path::Path) -> bool {
    match std::fs::symlink_metadata(f) {
        Ok(metadata) => metadata.is_dir(),
        Err(_) => false,
    }
}

pub fn is_file(f: &std::path::Path) -> bool {
    match std::fs::symlink_metadata(f) {
        Ok(metadata) => metadata.is_file(),
        Err(_) => false,
    }
}

pub fn is_link(f: &std::path::Path) -> bool {
    match std::fs::symlink_metadata(f) {
        Ok(metadata) => metadata.file_type().is_symlink(),
        Err(_) => false,
    }
}

#[cfg(unix)]
pub fn link_or_copy<P: AsRef<Path>, Q: AsRef<Path>>(src: P, dest: Q) -> std::io::Result<()> {
    let src = src.as_ref();
    let dest = dest.as_ref();
    match std::fs::hard_link(src, dest) {
        Ok(_) => Ok(()),
        Err(e) => {
            // TODO(jelmer): This should really be checking for
            // e.kind() != std::io::ErrorKind::CrossesDeviceBoundary{
            // See https://github.com/rust-lang/rust/issues/86442
            if e.kind() != std::io::ErrorKind::Other {
                return Err(e);
            }
            std::fs::copy(src, dest)?;
            Ok(())
        }
    }
}

#[cfg(any(target_os = "windows"))]
pub fn link_or_copy<P: AsRef<Path>, Q: AsRef<Path>>(src: P, dest: Q) -> std::io::Result<()> {
    std::fs::copy(src.as_ref(), dest.as_ref())?;
}

pub fn copy_tree<P: AsRef<Path>, Q: AsRef<Path>>(from_path: P, to_path: Q) -> std::io::Result<()> {
    for entry in WalkDir::new(from_path.as_ref()) {
        let entry = entry?;
        let path = entry.path();
        let dst_path = to_path
            .as_ref()
            .join(path.strip_prefix(from_path.as_ref()).unwrap());
        if entry.file_type().is_dir() {
            match std::fs::create_dir(&dst_path) {
                Ok(_) => {}
                Err(e) => {
                    if e.kind() != std::io::ErrorKind::AlreadyExists || dst_path != to_path.as_ref()
                    {
                        return Err(e);
                    }
                }
            }
        } else if entry.file_type().is_file() {
            std::fs::copy(path, dst_path)?;
        } else if entry.file_type().is_symlink() {
            let target = std::fs::read_link(path)?;
            let target = target
                .strip_prefix(from_path.as_ref())
                .unwrap_or(target.as_path());
            #[cfg(unix)]
            std::os::unix::fs::symlink(target, dst_path)?;
            #[cfg(windows)]
            std::os::windows::fs::symlink_file(target, dst_path)?;
        } else {
            return Err(std::io::Error::new(
                std::io::ErrorKind::Other,
                format!("Unsupported file type: {:?}", entry.file_type()),
            ));
        }
    }
    Ok(())
}

const FORMATS: [(SFlag, &str); 7] = [
    (SFlag::S_IFDIR, "directory"),
    (SFlag::S_IFCHR, "chardev"),
    (SFlag::S_IFBLK, "block"),
    (SFlag::S_IFREG, "file"),
    (SFlag::S_IFIFO, "fifo"),
    (SFlag::S_IFLNK, "symlink"),
    (SFlag::S_IFSOCK, "socket"),
];

pub fn kind_from_mode(mode: SFlag) -> &'static str {
    for (format_mode, format_kind) in FORMATS.iter() {
        if mode.bitand(SFlag::S_IFMT) == *format_mode {
            return format_kind;
        }
    }
    "unknown"
}

pub fn delete_any<P: AsRef<Path>>(path: P) -> std::io::Result<()> {
    fn delete_file_or_dir<P: AsRef<Path>>(path: P) -> std::io::Result<()> {
        let path = path.as_ref();
        // Look Before You Leap (LBYL) is appropriate here instead of Easier to Ask for
        // Forgiveness than Permission (EAFP) because:
        // - root can damage a solaris file system by using unlink,
        // - unlink raises different exceptions on different OSes (linux: EISDIR, win32:
        // EACCES, OSX: EPERM) when invoked on a directory.

        if path.is_dir() {
            std::fs::remove_dir(path)
        } else {
            std::fs::remove_file(path)
        }
    }

    // handle errors due to read-only files/directories
    match delete_file_or_dir(path.as_ref()) {
        Ok(()) => Ok(()),
        Err(ref e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
            if let Err(e) = make_writable(path.as_ref()) {
                debug!("Unable to make {:?} writable: {}", path.as_ref(), e);
            }
            delete_file_or_dir(path.as_ref())
        }
        Err(e) => Err(e),
    }
}

pub fn file_iterator<F: Read>(
    input_file: F,
    readsize: Option<usize>,
) -> impl Iterator<Item = Vec<u8>> {
    let readsize = readsize.unwrap_or(32768);
    let mut buffer = vec![0; readsize];
    let mut reader = std::io::BufReader::new(input_file);
    std::iter::from_fn(move || match reader.read(&mut buffer) {
        Ok(0) => None,
        Ok(n) => Some(buffer[..n].to_vec()),
        Err(_) => None,
    })
}

pub fn ensure_empty_directory_exists(path: &Path) -> std::io::Result<()> {
    match std::fs::create_dir(path) {
        Ok(_) => Ok(()),
        Err(e) => {
            if e.kind() != std::io::ErrorKind::AlreadyExists {
                Err(e)
            } else {
                let dir_entries = std::fs::read_dir(path)?;
                if dir_entries.count() > 0 {
                    Err(std::io::Error::new(
                        // TODO(jelmer): Switch to DirectoryNotEmpty once available:
                        // std::io::ErrorKind::DirectoryNotEmpty,
                        std::io::ErrorKind::Other,
                        format!("Directory {:?} is not empty", path),
                    ))
                } else {
                    Ok(())
                }
            }
        }
    }
}

pub fn lexists(path: &Path) -> std::io::Result<bool> {
    symlink_metadata(path).map(|_| true).or_else(|_e| Ok(false))
}

pub fn compare_files<T: Read, U: Read>(mut a: T, mut b: U) -> std::io::Result<bool> {
    const BUFSIZE: usize = 4096;
    let mut buf_a = [0; BUFSIZE];
    let mut buf_b = [0; BUFSIZE];

    loop {
        let n_a = a.read(&mut buf_a)?;
        let n_b = b.read(&mut buf_b)?;

        if buf_a[..n_a] != buf_b[..n_b] {
            return Ok(false);
        }

        if n_a == 0 {
            return Ok(n_b == 0);
        }
    }
}

pub fn isdir(f: &Path) -> bool {
    match std::fs::symlink_metadata(f) {
        Ok(metadata) => metadata.is_dir(),
        Err(_) => false,
    }
}
