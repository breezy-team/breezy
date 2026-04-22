//! Best-effort Windows file locks for breezy-transport.
//!
//! Windows sharing-mode restrictions mean that many of the cross-process
//! safety guarantees Breezy expects from fcntl locks are already implicit in
//! how files are opened. This module implements an in-process advisory lock
//! set that matches the shape of the Unix `fcntl-locks` module without
//! requiring privileged winapi primitives. It is deliberately conservative:
//! locks are process-local, but cross-process lock violations on Windows
//! surface as open/write failures via the normal sharing rules.

use crate::lock::{FileLock, Lock, LockError};
use lazy_static::lazy_static;
use log::debug;
use std::collections::hash_map::Entry;
use std::collections::{HashMap, HashSet};
use std::fs::{File, OpenOptions};
use std::path::{Path, PathBuf};

fn open(filename: &Path, options: &OpenOptions) -> Result<(PathBuf, File), LockError> {
    let filename = breezy_osutils::path::realpath(filename)?;
    match options.open(&filename) {
        Ok(f) => Ok((filename, f)),
        Err(e) => match e.kind() {
            std::io::ErrorKind::PermissionDenied => Err(LockError::Failed(filename, e.to_string())),
            std::io::ErrorKind::NotFound => {
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
        Ok(WriteLock { filename, f })
    }
}

impl Lock for WriteLock {
    fn unlock(&mut self) -> Result<(), LockError> {
        OPEN_WRITE_LOCKS.lock().unwrap().remove(&self.filename);
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
    pub fn new(filename: &Path, strict_locks: bool) -> Result<Self, LockError> {
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
        Ok(ReadLock { filename, f })
    }

    /// Try to grab a write lock on the file.
    pub fn temporary_write_lock(self) -> Result<TemporaryWriteLock, (Self, LockError)> {
        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&self.filename) {
            panic!("file already locked: {}", self.filename.to_string_lossy());
        }
        TemporaryWriteLock::new(self)
    }
}

impl Lock for ReadLock {
    fn unlock(&mut self) -> Result<(), LockError> {
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
    pub fn new(read_lock: ReadLock) -> Result<Self, (ReadLock, LockError)> {
        let filename = read_lock.filename.clone();
        if let Some(count) = OPEN_READ_LOCKS.lock().unwrap().get(&filename) {
            if *count > 1 {
                return Err((read_lock, LockError::Contention(filename)));
            }
        }

        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&filename) {
            panic!("file already locked: {}", filename.to_string_lossy());
        }

        let f = match OpenOptions::new()
            .write(true)
            .read(true)
            .create(true)
            .open(&filename)
        {
            Ok(f) => f,
            Err(e) => return Err((read_lock, e.into())),
        };

        OPEN_WRITE_LOCKS.lock().unwrap().insert(filename.clone());

        Ok(Self {
            read_lock,
            filename,
            f,
        })
    }

    /// Restore the original ReadLock.
    pub fn restore_read_lock(self) -> ReadLock {
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
