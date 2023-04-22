use crate::{Lock, LockError};
use log::debug;
use nix::fcntl::{flock, FlockArg};
use std::collections::{HashMap, HashSet};
use std::fs::{File, OpenOptions};
use std::os::unix::io::AsRawFd;
use std::path::{Path, PathBuf};

fn open(filename: &Path, options: &OpenOptions) -> std::result::Result<File, LockError> {
    let filename = breezy_osutils::realpath(filename);
    match options.open(filename) {
        Ok(f) => Ok((filename, f)),
        Err(e) => match e.kind() {
            std::io::ErrorKind::PermissionDenied => Err(LockError::LockFailed(filename.to_owned())),
            std::io::ErrorKind::NotFound => {
                debug!("trying to create missing lock {}", filename);
                Ok((
                    filename,
                    OpenOptions::new().create(true).write(true).open(filename)?,
                ))
            }
            _ => LockError::IoError(e),
        },
    }
}

const OPEN_WRITE_LOCKS: std::sync::Mutex<HashSet<PathBuf>> = std::sync::Mutex::new(HashSet::new());
const OPEN_READ_LOCKS: std::sync::Mutex<HashMap<PathBuf, usize>> =
    std::sync::Mutex::new(HashMap::new());

pub struct WriteLock {
    filename: PathBuf,
    f: File,
}

impl WriteLock {
    pub fn new(filename: &Path) -> Result<WriteLock, LockError> {
        let filename = breezy_osutils::path::realpath(filename);
        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&filename) {
            return Err(LockError::LockContention(filename));
        }
        if OPEN_READ_LOCKS.lock().unwrap().contains_key(&filename) {
            if debug::debug_flags().contains("strict_locks") {
                return Err(LockError::LockContention(filename));
            } else {
                debug!("Write lock taken w/ an open read lock on: {}", filename);
            }
        }

        let (filename, f) = open(filename, OpenOptions::new().read(true))?;
        OPEN_WRITE_LOCKS.lock().unwrap().insert(filename.clone());
        match flock(f.unwrap().as_raw_fd(), FlockArg::LockExclusiveNonblock) {
            Ok(_) => Ok(WriteLock { filename, f }),
            Err(e) => {
                if e == nix::errno::Errno::EAGAIN || e == nix::errno::Errno::EACCES {
                    flock(f.as_raw_fd(), FlockArg::Unlock);
                }
                // we should be more precise about whats a locking
                // error and whats a random-other error
                Err(LockError::LockContention(filename, e))
            }
        }
    }

    pub fn unlock(&mut self) {
        OPEN_WRITE_LOCKS.lock().unwrap().remove(&self.filename);
        flock(self.f.as_raw_fd(), FlockArg::Unlock);
    }
}

pub struct ReadLock {
    filename: PathBuf,
    f: File,
}

impl ReadLock {
    fn new(filename: &str) -> std::result::Result<Self, LockError> {
        let filename = breezy_osutils::path::realpath(filename);
        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&filename) {
            if debug::debug_flags().contains("strict_locks") {
                return Err(LockError::LockContention(filename));
            } else {
                debug!("Read lock taken w/ an open write lock on: {}", filename);
            }
        }

        OPEN_READ_LOCKS
            .lock()
            .unwrap()
            .entry(filename.clone())
            .and_modify(|count| *count += 1)
            .or_insert(1);

        let f = open(filename, OpenOptions::new().read(true))?;
        match flock(f.as_raw_fd(), FlockArg::LockSharedNonblock) {
            Ok(_) => {}
            Err(e) => {
                // we should be more precise about whats a locking
                // error and whats a random-other error
                return Err(LockError::LockContention(filename));
            }
        }
        Ok(ReadLock { filename, f })
    }

    fn unlock(&mut self) {
        match OPEN_READ_LOCKS.lock().unwrap().get(&self.filename) {
            Some(count) => {
                if *count == 1 {
                    OPEN_READ_LOCKS.lock().unwrap().remove(&self.filename);
                } else {
                    OPEN_READ_LOCKS
                        .lock()
                        .unwrap()
                        .insert(self.filename.clone(), count - 1);
                }
            }
            None => panic!("no read lock on {}", self.filename.to_string_lossy()),
        }
        flock(self.f.as_raw_fd(), FlockArg::Unlock);
    }

    /// Try to grab a write lock on the file.
    ///
    /// On platforms that support it, this will upgrade to a write lock
    /// without unlocking the file.
    /// Otherwise, this will release the read lock, and try to acquire a
    /// write lock.
    ///
    /// Returns: A token which can be used to switch back to a read lock.
    fn temporary_write_lock(mut self) -> std::result::Result<Self, LockError> {
        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&self.filename) {
            panic!("file already locked: {}", self.filename.to_string_lossy());
        }
        match TemporaryWriteLock::new(self) {
            Ok(wlock) => Ok(wlock),
            Err(e) => return Err(LockError::LockFailed(self.filename, e)),
        }
    }
}

/// A token used when grabbing a temporary_write_lock.
///
/// Call restore_read_lock() when you are done with the write lock.
struct TemporaryWriteLock {
    read_lock: ReadLock,
    filename: PathBuf,
    f: File,
}

impl TemporaryWriteLock {
    pub fn new(read_lock: ReadLock) -> std::result::Result<Self, LockError> {
        let filename = read_lock.filename;
        let count = OPEN_READ_LOCKS.lock().unwrap().get(&filename).unwrap_or(&0);
        if *count > 1 {
            // Something else also has a read-lock, so we cannot grab a
            // write lock.
            return Err(LockError::LockContention(filename));
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
            Err(e) => Err(LockError::LockFailed(filename, e.to_string())),
        }?;

        // LOCK_NB will cause IOError to be raised if we can't grab a
        // lock right away.
        match flock(f.as_raw_fd(), FlockArg::LockExclusiveNonblock) {
            Ok(_) => Ok(()),
            Err(e) => Err(LockError::LockContention(filename)),
        };

        OPEN_WRITE_LOCKS.lock().unwrap().insert(filename);

        Ok(Self {
            read_lock,
            filename,
            f,
        })
    }

    /// Restore the original ReadLock.
    pub fn restore_read_lock(mut self) -> ReadLock {
        // For fcntl, since we never released the read lock, just release
        // the write lock, and return the original lock.
        flock(self.f.as_raw_fd(), FlockArg::Unlock);
        OPEN_WRITE_LOCKS.lock().unwrap().remove(&self.filename);
        self.read_lock
    }
}
