use crate::Result;

pub trait Lock {
    fn unlock(&mut self) -> Result<()>;
}

struct BogusLock {}

impl Lock for BogusLock {
    fn unlock(&mut self) -> Result<()> {
        Ok(())
    }
}

pub trait FileLock {
    fn file(&self) -> std::io::Result<Box<std::fs::File>>;

    fn path(&self) -> &std::path::Path;
}
