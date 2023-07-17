use crate::Lock;
use std::ffi::OsString;
use std::os::windows::ffi::OsStringExt;
use std::ptr::null_mut;
use winapi::shared::minwindef::{DWORD, FALSE};
use winapi::shared::winerror::{ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION};
use winapi::um::fileapi::{
    CreateFileW, FILE_ATTRIBUTE_NORMAL, FILE_SHARE_READ, GENERIC_READ, GENERIC_WRITE,
    INVALID_HANDLE_VALUE, OPEN_ALWAYS,
};
use winapi::um::handleapi::CloseHandle;
use winapi::um::minwinbase::{LPSECURITY_ATTRIBUTES, OVERLAPPED};
use winapi::um::winbase::CREATE_ALWAYS;
use winapi::um::winnt::{FILE_SHARE_WRITE, HANDLE, LPCWSTR};

const _FUNCTION_NAME: &[u16] = &[
    0x0043, 0x0072, 0x0065, 0x0061, 0x0074, 0x0065, 0x0046, 0x0069, 0x006C, 0x0065, 0x0057, 0x0000,
];

fn create_file_w(
    filename: &str,
    access: DWORD,
    share_mode: DWORD,
    creation_disposition: DWORD,
    flags_and_attributes: DWORD,
) -> HANDLE {
    let filename_wide: Vec<u16> = OsString::from(filename)
        .encode_wide()
        .chain(Some(0))
        .collect();
    unsafe {
        CreateFileW(
            filename_wide.as_ptr() as LPCWSTR,
            access,
            share_mode,
            null_mut(),
            creation_disposition,
            flags_and_attributes,
            null_mut(),
        )
    }
}

struct FileLock(HANDLE);

impl Lock for FileLock {
    fn unlock(&self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

struct ReadLock(FileLock);

impl ReadLock {
    fn _open(filename: &str) -> Result<Self, String> {
        let handle = create_file_w(
            filename,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL,
        );
        if handle == INVALID_HANDLE_VALUE {
            let error_code = unsafe { winapi::um::errhandlingapi::GetLastError() };
            match error_code {
                ERROR_ACCESS_DENIED => {
                    return Err(format!("LockFailed: {}", filename));
                }
                ERROR_SHARING_VIOLATION => {
                    return Err(format!("LockContention: {}", filename));
                }
                _ => {
                    return Err(format!(
                        "Error creating read lock for {}: {}",
                        filename, error_code
                    ));
                }
            }
        }
        Ok(ReadLock(FileLock(handle)))
    }

    fn temporary_write_lock(&self) -> Result<(bool, WriteLock), ReadLock> {
        self.unlock();
        let write_lock = match WriteLock::_open(self.0) {
            Ok(lock) => lock,
            Err(_) => {
                return Err(self.clone());
            }
        };
        Ok((true, write_lock))
    }
}

#[derive(Debug)]
struct WriteLock(FileLock);

impl WriteLock {
    fn _open(handle: HANDLE) -> Result<Self, String> {
        let handle = create_file_w(
            "",
            GENERIC_READ | GENERIC_WRITE,
            0,
            CREATE_ALWAYS,
            FILE_ATTRIBUTE_NORMAL,
        );
        if handle == INVALID_HANDLE_VALUE {
            let error_code = unsafe { winapi::um::errhandlingapi::GetLastError() };
            return Err(format!(
                "Error creating write lock for {}: {}",
                handle, error_code
            ));
        }
        let overlapped = OVERLAPPED {
            Internal: 0,
            InternalHigh: 0,
            Offset: 0,
            OffsetHigh: 0,
            hEvent: null_mut(),
        };
        let result = unsafe {
            winapi::um::ioapiset::LockFileEx(
                handle,
                winapi::um::winnt::LOCKFILE_EXCLUSIVE_LOCK,
                0,
                1,
                0,
                &mut overlapped,
            )
        };
        if result == FALSE {
            let error_code = unsafe { winapi::um::errhandlingapi::GetLastError() };
            return Err(format!("Error locking file for write: {}", error_code));
        }
        Ok(WriteLock(FileLock(handle)))
    }

    fn restore_read_lock(&self) -> ReadLock {
        self.unlock();
        ReadLock::_open("").unwrap()
    }
}
