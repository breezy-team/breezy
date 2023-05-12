pub mod readv;

#[cfg(unix)]
#[path = "fcntl-locks.rs"]
pub mod filelock;

#[cfg(win32)]
#[path = "win32-locks.rs"]
pub mod filelock;

pub mod lock;
