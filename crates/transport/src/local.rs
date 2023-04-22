use crate::{BogusLock, Error, Lock, Result, SmartMedium, Stat, Transport, UrlFragment};
use atomicwrites::{AllowOverwrite, AtomicFile};
use path_clean::{clean, PathClean};
use std::collections::HashMap;
use std::fs::File;
use std::fs::Permissions;
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use url::Url;
use walkdir;

pub struct LocalTransport {
    base: Url,
    path: PathBuf,
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

    fn local_abspath(&self, relpath: &UrlFragment) -> Result<PathBuf> {
        let path = self.path.join(relpath);
        Ok(path.clean())
    }

    fn can_roundtrip_unix_modebits(&self) -> bool {
        #[cfg(unix)]
        return true;
        #[cfg(not(unix))]
        return false;
    }

    fn get(&self, relpath: &UrlFragment) -> Result<Box<dyn Read + Send + Sync>> {
        let path = self.local_abspath(relpath)?;
        let mut f = std::fs::File::open(path).map_err(Error::from)?;
        Ok(Box::new(f))
    }

    fn mkdir(&self, relpath: &UrlFragment, permissions: Option<Permissions>) -> Result<()> {
        let path = self.local_abspath(relpath)?;
        std::fs::create_dir(&path).map_err(Error::from)?;
        if let Some(permissions) = permissions {
            std::fs::set_permissions(&path, permissions)
                .map_err(Error::from)
                .map_err(Error::from)?;
        }
        Ok(())
    }

    fn has(&self, path: &UrlFragment) -> Result<bool> {
        let path = self.local_abspath(path)?;

        Ok(path.exists())
    }

    fn stat(&self, relpath: &UrlFragment) -> Result<Stat> {
        let path = self.local_abspath(relpath)?;
        Ok(Stat::from(
            std::fs::symlink_metadata(path).map_err(Error::from)?,
        ))
    }

    fn clone(&self, offset: Option<&UrlFragment>) -> Result<Box<dyn Transport>> {
        let new_path = match offset {
            Some(offset) => self.local_abspath(offset)?,
            None => self.path.to_path_buf(),
        };
        Ok(Box::new(LocalTransport::from(new_path.as_path())))
    }

    fn abspath(&self, relpath: &UrlFragment) -> Result<Url> {
        self.base.join(relpath).map_err(Error::from)
    }

    fn relpath(&self, abspath: &Url) -> Result<String> {
        let relpath = breezy_urlutils::file_relpath(self.base.as_str(), abspath.as_str())
            .map_err(Error::from)?;
        Ok(relpath)
    }

    fn put_file(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn Read,
        permissions: Option<Permissions>,
    ) -> Result<()> {
        let path = self.local_abspath(relpath)?;
        let af = AtomicFile::new(path, AllowOverwrite);
        af.write(|outf| {
            if let Some(permissions) = permissions {
                outf.set_permissions(permissions)?;
            }
            std::io::copy(f, outf)
        })
        .map_err(Error::from)?;
        Ok(())
    }

    fn delete(&self, relpath: &UrlFragment) -> Result<()> {
        let path = self.local_abspath(relpath)?;
        std::fs::remove_file(path).map_err(Error::from)
    }

    fn rmdir(&self, relpath: &UrlFragment) -> Result<()> {
        let path = self.local_abspath(relpath)?;
        std::fs::remove_dir(path).map_err(Error::from)
    }

    fn rename(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()> {
        let abs_from = self.local_abspath(rel_from)?;
        let abs_to = self.local_abspath(rel_to)?;

        std::fs::rename(abs_from, abs_to).map_err(Error::from)
    }

    fn set_segment_parameter(&mut self, key: &str, value: Option<&str>) -> Result<()> {
        let (raw, mut params) = breezy_urlutils::split_segment_parameters(self.base.as_str())?;
        if let Some(value) = value {
            params.insert(key, value);
        } else {
            params.remove(key);
        }
        self.base = Url::parse(&breezy_urlutils::join_segment_parameters(raw, &params)?)?;
        Ok(())
    }

    fn get_segment_parameters(&self) -> Result<HashMap<String, String>> {
        let (_, params) = breezy_urlutils::split_segment_parameters(self.base.as_str())?;
        Ok(params
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect())
    }

    #[cfg(unix)]
    fn readv<'a>(
        &'a self,
        path: &UrlFragment,
        offsets: &'a [(u64, usize)],
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>>> + '_> {
        use nix::libc::off_t;
        use nix::sys::uio::pread;
        use std::os::unix::io::AsRawFd;
        let abspath = match self.local_abspath(path) {
            Ok(p) => p,
            Err(err) => return Box::new(std::iter::once(Err(err))),
        };
        let file = match std::fs::File::open(abspath) {
            Ok(f) => f,
            Err(err) => return Box::new(std::iter::once(Err(err.into()))),
        };
        let fd = file.as_raw_fd();

        Box::new(offsets.iter().map(move |&(offset, len)| {
            let mut buf = vec![0; len];
            match pread(fd, &mut buf[..], offset as off_t) {
                Ok(n) if n == len as usize => Ok(buf),
                Ok(_) => Err(Error::UnexpectedEof),
                Err(e) => Err(std::io::Error::from_raw_os_error(e as i32).into()),
            }
        }))
    }

    fn append_file(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn std::io::Read,
        permissions: Option<Permissions>,
    ) -> Result<()> {
        let path = self.local_abspath(relpath)?;
        let mut file = std::fs::OpenOptions::new()
            .append(true)
            .open(path)
            .map_err(Error::from)?;
        if let Some(permissions) = permissions {
            file.set_permissions(permissions)?;
        }
        std::io::copy(f, &mut file).map_err(Error::from)?;
        Ok(())
    }

    #[cfg(unix)]
    fn readlink(&self, relpath: &UrlFragment) -> Result<String> {
        use std::os::unix::ffi::OsStrExt;
        let path = self.local_abspath(relpath)?;
        let target = std::fs::read_link(path).map_err(Error::from)?;
        Ok(breezy_urlutils::escape(target.as_os_str().as_bytes(), None))
    }

    fn hardlink(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()> {
        let from = self.local_abspath(rel_from)?;
        let to = self.local_abspath(rel_to)?;
        std::fs::hard_link(from, to).map_err(Error::from)
    }

    #[cfg(target_family = "unix")]
    fn symlink(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()> {
        let from = self.local_abspath(rel_from)?;
        let to = self.local_abspath(rel_to)?;
        std::os::unix::fs::symlink(from, to).map_err(Error::from)
    }

    fn iter_files_recursive(&self) -> Box<dyn Iterator<Item = Result<String>>> {
        let wd = walkdir::WalkDir::new(&self.path);

        fn walkdir_err(e: walkdir::Error) -> Error {
            let ioerr: std::io::Error = e.into();
            Error::from(ioerr)
        }

        Box::new(wd.into_iter().map(|e| {
            e.map_err(walkdir_err)
                .map(|e| e.path().to_string_lossy().to_string())
        }))
    }

    fn open_write_stream(
        &self,
        relpath: &UrlFragment,
        permissions: Option<Permissions>,
    ) -> Result<Box<dyn std::io::Write + Send + Sync>> {
        let path = self.local_abspath(relpath)?;
        let file = File::create(path).map_err(Error::from)?;
        file.set_len(0)?;
        if let Some(permissions) = permissions {
            file.set_permissions(permissions)?;
        }
        Ok(Box::new(file))
    }

    fn delete_tree(&self, relpath: &UrlFragment) -> Result<()> {
        let path = self.local_abspath(relpath)?;
        std::fs::remove_dir_all(path).map_err(Error::from)
    }

    fn r#move(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()> {
        let from = self.local_abspath(rel_from)?;
        let to = self.local_abspath(rel_to)?;

        // TODO(jelmer): Should remove destination if necessary
        std::fs::rename(from, to).map_err(Error::from)
    }

    fn copy_tree(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()> {
        let from = self.local_abspath(rel_from)?;
        let to = self.local_abspath(rel_to)?;
        unimplemented!()
    }

    fn list_dir(&self, relpath: &UrlFragment) -> Box<dyn Iterator<Item = Result<String>>> {
        let path = match self.local_abspath(relpath) {
            Ok(p) => p,
            Err(err) => return Box::new(std::iter::once(Err(err))),
        };
        let entries = match std::fs::read_dir(path).map_err(Error::from) {
            Ok(e) => e,
            Err(err) => return Box::new(std::iter::once(Err(err))),
        };
        Box::new(
            entries
                .map(|entry| entry.map_err(Error::from))
                .map(|entry| entry.map(|entry| entry.file_name().into_string().unwrap())),
        )
    }

    fn listable(&self) -> bool {
        true
    }

    fn get_smart_medium(&self) -> Result<Box<dyn SmartMedium>> {
        Err(Error::NoSmartMedium)
    }

    fn lock_read(&self, relpath: &UrlFragment) -> Result<Box<dyn Lock + Send + Sync>> {
        Ok(Box::new(BogusLock {}))
    }

    fn lock_write(&self, relpath: &UrlFragment) -> Result<Box<dyn Lock + Send + Sync>> {
        Err(Error::TransportNotPossible)
    }

    // TODO(jelmer): Implement optimized version of copy_to()
}
