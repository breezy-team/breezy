use log::debug;
use std::fs::{set_permissions, Permissions};
use std::io::Result;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

pub fn make_writable<P: AsRef<Path>>(path: P) -> Result<()> {
    let path = path.as_ref();
    let metadata = std::fs::symlink_metadata(path)?;
    let mut permissions = metadata.permissions();
    if !metadata.file_type().is_symlink() {
        permissions.set_mode(permissions.mode() | 0o200);
        chmod_if_possible(path, permissions)?;
    }
    Ok(())
}

pub fn make_readonly<P: AsRef<Path>>(path: P) -> Result<()> {
    let path = path.as_ref();
    let metadata = std::fs::symlink_metadata(path)?;
    let mut permissions = metadata.permissions();
    if !metadata.file_type().is_symlink() {
        permissions.set_mode(permissions.mode() & 0o777555);
        chmod_if_possible(path, permissions)?;
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
