pub trait Lock {
    fn unlock(&mut self) -> std::result::Result<(), LockError>;
}

pub enum LockError {
    Contention(std::path::PathBuf),
    Failed(std::path::PathBuf, String),
    IoError(std::io::Error),
}

pub type LockResult<L> = std::result::Result<L, LockError>;

impl From<std::io::Error> for LockError {
    fn from(err: std::io::Error) -> LockError {
        LockError::IoError(err)
    }
}

pub struct BogusLock;

impl Lock for BogusLock {
    fn unlock(&mut self) -> std::result::Result<(), LockError> {
        Ok(())
    }
}

pub trait FileLock {
    fn file(&self) -> std::io::Result<Box<std::fs::File>>;

    fn path(&self) -> &std::path::Path;
}
