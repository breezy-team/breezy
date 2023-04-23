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
