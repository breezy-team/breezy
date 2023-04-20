use std::path::{PathBuf,Path};
use url::Url;
use crate::{Transport,UrlFragment,Error,Result};

pub struct LocalTransport {
    base: Url,
    path: PathBuf,
}

impl LocalTransport {
    fn local_abspath(&self, relpath: &UrlFragment) -> Result<PathBuf> {
        let path = self.path.join(relpath);
        Ok(path)
    }
}

impl From<&Path> for LocalTransport {
    fn from(path: &Path) -> Self {
        Self {
            base: Url::from_file_path(path).unwrap(),
            path: path.to_path_buf(),
        }
    }
}

impl From<Url> for LocalTransport {
    fn from(url: Url) -> Self {
        Self {
            base: url.clone(),
            path: url.to_file_path().unwrap(),
        }
    }
}

impl Clone for LocalTransport {
    fn clone(&self) -> Self {
        LocalTransport {
            path: self.path.clone(),
            base: self.base.clone(),
        }
    }
}

impl Transport for LocalTransport {
    fn external_url(&self) -> Result<Url> {
        Ok(self.base.clone())
    }

    fn base(&self) -> Url {
        self.base.clone()
    }

    fn get(&self, relpath: &UrlFragment) -> Result<Box<dyn std::io::Read>> {
        let path = self.path.join(relpath);
        let f = std::fs::File::open(path).map_err(Error::from)?;
        Ok(Box::new(f))
    }
}
