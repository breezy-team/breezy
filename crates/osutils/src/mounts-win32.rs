use std::ffi::OsStr;
use std::os::windows::ffi::{OsStrExt, OsStringExt};
use std::path::Path;
use std::ptr;
use winapi::shared::minwindef::DWORD;
use winapi::um::fileapi::GetVolumeInformationW;

fn _get_fs_type(drive: &str) -> Option<String> {
    const MAX_FS_TYPE_LENGTH: DWORD = 16;
    let drive_wide: Vec<u16> = OsStr::new(drive)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let mut fs_type = vec![0u16; (MAX_FS_TYPE_LENGTH + 1) as usize];
    let res = unsafe {
        GetVolumeInformationW(
            drive_wide.as_ptr(),
            ptr::null_mut(),
            0,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            fs_type.as_mut_ptr(),
            MAX_FS_TYPE_LENGTH,
        )
    };
    if res != 0 {
        let end = fs_type
            .iter()
            .position(|&c| c == 0)
            .unwrap_or(fs_type.len());
        Some(
            std::ffi::OsString::from_wide(&fs_type[..end])
                .to_string_lossy()
                .into_owned(),
        )
    } else {
        None
    }
}

pub fn get_fs_type<P: AsRef<Path>>(path: P) -> Option<String> {
    let drive = path
        .as_ref()
        .parent()
        .and_then(|p| p.to_str())
        .unwrap_or_default();
    let drive = if drive.contains(':') {
        drive
    } else {
        &format!("{}\\", drive)
    };
    let fs_type = _get_fs_type(drive)?;
    Some(match fs_type.as_str() {
        "FAT32" => String::from("vfat"),
        "NTFS" => String::from("ntfs"),
        _ => fs_type,
    })
}
