use crate::lock::{FileLock, Lock, LockError};
use lazy_static::lazy_static;
use log::debug;
use nix::fcntl::{fcntl, FcntlArg};
use std::collections::hash_map::Entry;
use std::collections::{HashMap, HashSet};
use std::fs::{File, OpenOptions};
use std::os::unix::io::AsRawFd;
use std::path::{Path, PathBuf};

fn open(filename: &Path, options: &OpenOptions) -> std::result::Result<(PathBuf, File), LockError> {
    let filename = breezy_osutils::path::realpath(filename)?;
    match options.open(&filename) {
        Ok(f) => Ok((filename, f)),
        Err(e) => match e.kind() {
            std::io::ErrorKind::PermissionDenied => Err(LockError::Failed(filename, e.to_string())),
            std::io::ErrorKind::NotFound => {
                // Maybe this is an old branch (before 2005)?
                debug!(
                    "trying to create missing lock {}",
                    filename.to_string_lossy()
                );
                let f = OpenOptions::new()
                    .create(true)
                    .write(true)
                    .read(true)
                    .open(&filename)?;
                Ok((filename, f))
            }
            _ => Err(e.into()),
        },
    }
}

lazy_static! {
    static ref OPEN_WRITE_LOCKS: std::sync::Mutex<HashSet<PathBuf>> =
        std::sync::Mutex::new(HashSet::new());
    static ref OPEN_READ_LOCKS: std::sync::Mutex<HashMap<PathBuf, usize>> =
        std::sync::Mutex::new(HashMap::new());
}

pub struct WriteLock {
    filename: PathBuf,
    f: File,
}

impl WriteLock {
    pub fn new(filename: &Path, strict_locks: bool) -> Result<WriteLock, LockError> {
        let filename = breezy_osutils::path::realpath(filename)?;
        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&filename) {
            return Err(LockError::Contention(filename));
        }
        if OPEN_READ_LOCKS.lock().unwrap().contains_key(&filename) {
            if strict_locks {
                return Err(LockError::Contention(filename));
            } else {
                debug!(
                    "Write lock taken w/ an open read lock on: {}",
                    filename.to_string_lossy()
                );
            }
        }

        let (filename, f) = open(
            filename.as_path(),
            OpenOptions::new().read(true).write(true),
        )?;
        OPEN_WRITE_LOCKS.lock().unwrap().insert(filename.clone());
        let flock = nix::libc::flock {
            l_type: nix::libc::F_WRLCK as i16,
            l_whence: nix::libc::SEEK_SET as i16,
            l_start: 0,
            l_len: 0,
            l_pid: 0,
        };
        match fcntl(f.as_raw_fd(), FcntlArg::F_SETLK(&flock)) {
            Ok(_) => Ok(WriteLock { filename, f }),
            Err(e) => {
                if e == nix::errno::Errno::EAGAIN || e == nix::errno::Errno::EACCES {
                    let flock = nix::libc::flock {
                        l_type: nix::libc::F_UNLCK as i16,
                        l_whence: nix::libc::SEEK_SET as i16,
                        l_start: 0,
                        l_len: 0,
                        l_pid: 0,
                    };
                    let _ = fcntl(f.as_raw_fd(), FcntlArg::F_SETLK(&flock));
                }
                // we should be more precise about whats a locking
                // error and whats a random-other error
                Err(LockError::Contention(filename))
            }
        }
    }
}

impl Lock for WriteLock {
    fn unlock(&mut self) -> Result<(), LockError> {
        OPEN_WRITE_LOCKS.lock().unwrap().remove(&self.filename);
        let flock = nix::libc::flock {
            l_type: nix::libc::F_UNLCK as i16,
            l_whence: nix::libc::SEEK_SET as i16,
            l_start: 0,
            l_len: 0,
            l_pid: 0,
        };
        let _ = fcntl(self.f.as_raw_fd(), FcntlArg::F_SETLK(&flock));
        Ok(())
    }
}

impl FileLock for WriteLock {
    fn file(&self) -> std::io::Result<Box<File>> {
        Ok(Box::new(self.f.try_clone()?))
    }

    fn path(&self) -> &Path {
        &self.filename
    }
}

pub struct ReadLock {
    filename: PathBuf,
    f: File,
}

impl ReadLock {
    pub fn new(filename: &Path, strict_locks: bool) -> std::result::Result<Self, LockError> {
        let filename = breezy_osutils::path::realpath(filename)?;
        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&filename) {
            if strict_locks {
                return Err(LockError::Contention(filename));
            } else {
                debug!(
                    "Read lock taken w/ an open write lock on: {}",
                    filename.to_string_lossy()
                );
            }
        }

        OPEN_READ_LOCKS
            .lock()
            .unwrap()
            .entry(filename.clone())
            .and_modify(|count| *count += 1)
            .or_insert(1);

        let (filename, f) = open(&filename, OpenOptions::new().read(true))?;
        let flock = nix::libc::flock {
            l_type: nix::libc::F_RDLCK as i16,
            l_whence: nix::libc::SEEK_SET as i16,
            l_start: 0,
            l_len: 0,
            l_pid: 0,
        };
        match fcntl(f.as_raw_fd(), FcntlArg::F_SETLK(&flock)) {
            Ok(_) => {}
            Err(_e) => {
                // we should be more precise about whats a locking
                // error and whats a random-other error
                return Err(LockError::Contention(filename));
            }
        }
        Ok(ReadLock { filename, f })
    }

    /// Try to grab a write lock on the file.
    ///
    /// On platforms that support it, this will upgrade to a write lock
    /// without unlocking the file.
    /// Otherwise, this will release the read lock, and try to acquire a
    /// write lock.
    ///
    /// Returns: A token which can be used to switch back to a read lock.
    pub fn temporary_write_lock(
        self,
    ) -> std::result::Result<TemporaryWriteLock, (Self, LockError)> {
        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&self.filename) {
            panic!("file already locked: {}", self.filename.to_string_lossy());
        }
        TemporaryWriteLock::new(self)
    }
}

impl Lock for ReadLock {
    fn unlock(&mut self) -> std::result::Result<(), LockError> {
        match OPEN_READ_LOCKS.lock().unwrap().entry(self.filename.clone()) {
            Entry::Occupied(mut entry) => {
                let count = entry.get_mut();
                if *count == 1 {
                    entry.remove();
                } else {
                    *count -= 1;
                }
            }
            Entry::Vacant(_) => panic!("no read lock on {}", self.filename.to_string_lossy()),
        }
        let flock = nix::libc::flock {
            l_type: nix::libc::F_UNLCK as i16,
            l_whence: nix::libc::SEEK_SET as i16,
            l_start: 0,
            l_len: 0,
            l_pid: 0,
        };
        let _ = fcntl(self.f.as_raw_fd(), FcntlArg::F_SETLK(&flock));

        Ok(())
    }
}

impl FileLock for ReadLock {
    fn file(&self) -> std::io::Result<Box<File>> {
        Ok(Box::new(self.f.try_clone()?))
    }

    fn path(&self) -> &Path {
        &self.filename
    }
}
/// A token used when grabbing a temporary_write_lock.
///
/// Call restore_read_lock() when you are done with the write lock.
pub struct TemporaryWriteLock {
    read_lock: ReadLock,
    filename: PathBuf,
    f: File,
}

impl TemporaryWriteLock {
    pub fn new(read_lock: ReadLock) -> std::result::Result<Self, (ReadLock, LockError)> {
        let filename = read_lock.filename.clone();
        if let Some(count) = OPEN_READ_LOCKS.lock().unwrap().get(&filename) {
            if *count > 1 {
                // Something else also has a read-lock, so we cannot grab a
                // write lock.
                return Err((read_lock, LockError::Contention(filename)));
            }
        }

        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&filename) {
            panic!("file already locked: {}", filename.to_string_lossy());
        }

        // See if we can open the file for writing. Another process might
        // have a read lock. We don't use self._open() because we don't want
        // to create the file if it exists. That would have already been
        // done by ReadLock
        let f = match OpenOptions::new()
            .write(true)
            .read(true)
            .create(true)
            .open(&filename)
        {
            Ok(f) => Ok(f),
            Err(e) => return Err((read_lock, e.into())),
        }?;

        // LOCK_NB will cause IOError to be raised if we can't grab a
        // lock right away.
        let flock = nix::libc::flock {
            l_type: nix::libc::F_RDLCK as i16,
            l_whence: nix::libc::SEEK_SET as i16,
            l_start: 0,
            l_len: 0,
            l_pid: 0,
        };

        match fcntl(f.as_raw_fd(), FcntlArg::F_SETLK(&flock)) {
            Ok(_) => Ok(()),
            Err(_) => {
                return Err((read_lock, LockError::Contention(filename)));
            }
        }?;

        OPEN_WRITE_LOCKS.lock().unwrap().insert(filename.clone());

        Ok(Self {
            read_lock,
            filename,
            f,
        })
    }

    /// Restore the original ReadLock.
    pub fn restore_read_lock(self) -> ReadLock {
        // For fcntl, since we never released the read lock, just release
        // the write lock, and return the original lock.
        let flock = nix::libc::flock {
            l_type: nix::libc::F_UNLCK as i16,
            l_whence: nix::libc::SEEK_SET as i16,
            l_start: 0,
            l_len: 0,
            l_pid: 0,
        };
        match fcntl(self.f.as_raw_fd(), FcntlArg::F_SETLK(&flock)) {
            Ok(_) => {}
            Err(e) => {
                debug!(
                    "error unlocking file {}: {}",
                    &self.filename.to_string_lossy(),
                    e
                );
            }
        }
        OPEN_WRITE_LOCKS.lock().unwrap().remove(&self.filename);
        self.read_lock
    }
}

impl FileLock for TemporaryWriteLock {
    fn file(&self) -> std::io::Result<Box<File>> {
        Ok(Box::new(self.f.try_clone()?))
    }

    fn path(&self) -> &Path {
        &self.filename
    }
}
