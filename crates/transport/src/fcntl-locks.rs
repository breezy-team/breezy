use crate::{Error, Lock};
use lazy_static::lazy_static;
use log::debug;
use nix::fcntl::{flock, FlockArg};
use std::collections::{HashMap, HashSet};
use std::fs::{File, OpenOptions};
use std::os::unix::io::AsRawFd;
use std::path::{Path, PathBuf};

// TODO(jelmer): make this a debug flag
const STRICT_LOCKS: bool = false;

fn open(filename: &Path, options: &OpenOptions) -> std::result::Result<(PathBuf, File), Error> {
    let filename = breezy_osutils::path::realpath(filename)?;
    match options.open(&filename) {
        Ok(f) => Ok((filename, f)),
        Err(e) => match e.kind() {
            std::io::ErrorKind::PermissionDenied => Err(Error::LockFailed(filename, e.to_string())),
            std::io::ErrorKind::NotFound => {
                debug!(
                    "trying to create missing lock {}",
                    filename.to_string_lossy()
                );
                let f = OpenOptions::new()
                    .create(true)
                    .write(true)
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
    pub fn new(filename: &Path) -> Result<WriteLock, Error> {
        let filename = breezy_osutils::path::realpath(filename)?;
        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&filename) {
            return Err(Error::LockContention(filename));
        }
        if OPEN_READ_LOCKS.lock().unwrap().contains_key(&filename) {
            if STRICT_LOCKS {
                return Err(Error::LockContention(filename));
            } else {
                debug!(
                    "Write lock taken w/ an open read lock on: {}",
                    filename.to_string_lossy()
                );
            }
        }

        let (filename, f) = open(filename.as_path(), OpenOptions::new().read(true))?;
        OPEN_WRITE_LOCKS.lock().unwrap().insert(filename.clone());
        match flock(f.as_raw_fd(), FlockArg::LockExclusiveNonblock) {
            Ok(_) => Ok(WriteLock { filename, f }),
            Err(e) => {
                if e == nix::errno::Errno::EAGAIN || e == nix::errno::Errno::EACCES {
                    flock(f.as_raw_fd(), FlockArg::Unlock);
                }
                // we should be more precise about whats a locking
                // error and whats a random-other error
                Err(Error::LockContention(filename))
            }
        }
    }
}

impl Lock for WriteLock {
    fn unlock(&mut self) -> Result<(), Error> {
        OPEN_WRITE_LOCKS.lock().unwrap().remove(&self.filename);
        flock(self.f.as_raw_fd(), FlockArg::Unlock);
        Ok(())
    }
}

pub struct ReadLock {
    filename: PathBuf,
    f: File,
}

impl ReadLock {
    pub fn new(filename: &Path) -> std::result::Result<Self, Error> {
        let filename = breezy_osutils::path::realpath(filename)?;
        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&filename) {
            if STRICT_LOCKS {
                return Err(Error::LockContention(filename));
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
        match flock(f.as_raw_fd(), FlockArg::LockSharedNonblock) {
            Ok(_) => {}
            Err(_) => {
                // we should be more precise about whats a locking
                // error and whats a random-other error
                return Err(Error::LockContention(filename));
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
    pub fn temporary_write_lock(self) -> std::result::Result<TemporaryWriteLock, Error> {
        if OPEN_WRITE_LOCKS.lock().unwrap().contains(&self.filename) {
            panic!("file already locked: {}", self.filename.to_string_lossy());
        }
        TemporaryWriteLock::new(self)
    }
}

impl Lock for ReadLock {
    fn unlock(&mut self) -> std::result::Result<(), Error> {
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
        Ok(())
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
    pub fn new(read_lock: ReadLock) -> std::result::Result<Self, Error> {
        let filename = read_lock.filename.clone();
        if let Some(count) = OPEN_READ_LOCKS.lock().unwrap().get(&filename) {
            if *count > 1 {
                // Something else also has a read-lock, so we cannot grab a
                // write lock.
                return Err(Error::LockContention(filename.clone()));
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
            Err(e) => Err(Error::LockFailed(filename.clone(), e.to_string())),
        }?;

        // LOCK_NB will cause IOError to be raised if we can't grab a
        // lock right away.
        match flock(f.as_raw_fd(), FlockArg::LockExclusiveNonblock) {
            Ok(_) => Ok(()),
            Err(_) => Err(Error::LockContention(filename.clone())),
        };

        OPEN_WRITE_LOCKS.lock().unwrap().insert(filename.clone());

        Ok(Self {
            read_lock,
            filename: filename.clone(),
            f,
        })
    }

    /// Restore the original ReadLock.
    pub fn restore_read_lock(self) -> ReadLock {
        // For fcntl, since we never released the read lock, just release
        // the write lock, and return the original lock.
        flock(self.f.as_raw_fd(), FlockArg::Unlock);
        OPEN_WRITE_LOCKS.lock().unwrap().remove(&self.filename);
        self.read_lock
    }
}
