use std::path::{PathBuf,Path};
use std::fs::{Metadata, Permissions};
use url::Url;
use crate::{LocalTransport,Transport,Stat,UrlFragment,Error,Result};

pub struct FileSystemTransport {
    base: Url,
    path: PathBuf,
}

impl LocalTransport for FileSystemTransport {
    fn local_abspath(&self, relpath: &UrlFragment) -> Result<PathBuf> {
        let path = self.path.join(relpath);
        Ok(path)
    }
}

impl From<&Path> for FileSystemTransport {
    fn from(path: &Path) -> Self {
        Self {
            base: Url::from_file_path(path).unwrap(),
            path: path.to_path_buf(),
        }
    }
}

impl From<Url> for FileSystemTransport {
    fn from(url: Url) -> Self {
        Self {
            base: url.clone(),
            path: url.to_file_path().unwrap(),
        }
    }
}

impl Clone for FileSystemTransport {
    fn clone(&self) -> Self {
        FileSystemTransport {
            path: self.path.clone(),
            base: self.base.clone(),
        }
    }
}

impl Transport for FileSystemTransport {
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

    fn mkdir(&self, relpath: &UrlFragment, permissions: Option<Permissions>) -> Result<()> {
        let path = self.local_abspath(relpath)?;
        std::fs::create_dir(&path).map_err(Error::from)?;
        if let Some(permissions) = permissions {
            std::fs::set_permissions(&path, permissions).map_err(Error::from).map_err(Error::from)?;
        }
        Ok(())
    }

    fn has(&self, path: &UrlFragment) -> Result<bool> {
        let path = self.local_abspath(path)?;

        Ok(path.exists())
    }

    fn stat(&self, relpath: &UrlFragment) -> Result<Stat> {
        let path = self.local_abspath(relpath)?;
        Ok(Stat::from(std::fs::symlink_metadata(path).map_err(Error::from)?))
    }

    fn clone(&self, offset: Option<&UrlFragment>) -> Result<Box<dyn Transport>> {
        let new_path = match offset {
            Some(offset) => self.local_abspath(offset)?,
            None => self.path.to_path_buf(),
        };
        Ok(Box::new(FileSystemTransport::from(new_path.as_path())))
    }
}
