use crate::lock::LockError;
use crate::{
    map_io_err_to_transport_err, Error, Lock, ReadStream, Result, SmartMedium, Stat, Transport,
    UrlFragment, WriteStream,
};
use breezy_urlutils::{escape, unescape};

use std::collections::HashMap;
use std::convert::TryFrom;
use std::fs::File;
use std::fs::Permissions;
use std::io::{Read, Seek};

use std::path::{Path, PathBuf};
use url::Url;
use walkdir;

pub struct LocalTransport {
    base: Url,
    path: PathBuf,
}

impl TryFrom<&Path> for LocalTransport {
    type Error = Error;
    fn try_from(path: &Path) -> Result<Self> {
        let url = breezy_urlutils::local_path_to_url(path).map_err(|e| {
            map_io_err_to_transport_err(e, Some(path.to_path_buf().to_str().unwrap()))
        })?;
        LocalTransport::new(&url)
    }
}

impl TryFrom<Url> for LocalTransport {
    type Error = Error;
    fn try_from(url: Url) -> Result<Self> {
        LocalTransport::new(url.as_str())
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

impl WriteStream for File {
    fn sync_data(&self) -> std::io::Result<()> {
        self.sync_data()
    }
}

impl ReadStream for File {}

impl LocalTransport {
    pub fn new(base: &str) -> Result<Self> {
        let base = if base.ends_with('/') {
            base.to_string()
        } else {
            format!("{}/", base)
        };
        let mut path = breezy_urlutils::local_path_from_url(&base)?;
        if !path.to_string_lossy().ends_with('/') {
            path.push("")
        }
        let base = Url::parse(&base)?;
        Ok(LocalTransport { base, path })
    }

    fn _abspath(&self, relative_reference: &str) -> Result<PathBuf> {
        if relative_reference == "." || relative_reference.is_empty() {
            Ok(self.path.clone())
        } else {
            let mut ret = self.path.clone();

            let extra = breezy_urlutils::unescape(relative_reference)?;

            let extra = extra.trim_start_matches('/');

            ret.push(extra);

            Ok(ret)
        }
    }
}

impl std::fmt::Debug for LocalTransport {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "LocalTransport({})", self.base)
    }
}

fn lock_err_to_transport_err(e: LockError) -> Error {
    match e {
        LockError::Contention(p) => Error::LockContention(p),
        LockError::IoError(e) => Error::Io(e),
        LockError::Failed(p, w) => Error::LockFailed(p, w),
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
        let absurl = self.abspath(relpath)?;
        breezy_urlutils::local_path_from_url(absurl.as_str()).map_err(Error::from)
    }

    fn can_roundtrip_unix_modebits(&self) -> bool {
        #[cfg(unix)]
        return true;
        #[cfg(not(unix))]
        return false;
    }

    fn get(&self, relpath: &UrlFragment) -> Result<Box<dyn ReadStream + Send + Sync>> {
        let path = self._abspath(relpath)?;
        let f =
            std::fs::File::open(path).map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        Ok(Box::new(f))
    }

    fn mkdir(&self, relpath: &UrlFragment, permissions: Option<Permissions>) -> Result<()> {
        let path = self._abspath(relpath)?;
        std::fs::create_dir(&path).map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        if let Some(permissions) = permissions {
            std::fs::set_permissions(&path, permissions)
                .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        }
        Ok(())
    }

    fn has(&self, path: &UrlFragment) -> Result<bool> {
        let path = self._abspath(path)?;

        Ok(path.exists())
    }

    #[cfg(unix)]
    fn stat(&self, relpath: &UrlFragment) -> Result<Stat> {
        use std::ffi::OsStr;
        use std::os::unix::ffi::OsStrExt;
        let path = self._abspath(relpath)?;

        // Strip trailing slashes, so we can properly stat broken symlinks

        let path = if path.as_path().as_os_str().as_bytes().ends_with(b"/") {
            let b = path.as_path().as_os_str().as_bytes();
            let b = b.strip_suffix(b"/").unwrap();
            PathBuf::from(OsStr::from_bytes(b))
        } else {
            path
        };

        Ok(Stat::from(std::fs::symlink_metadata(path).map_err(
            |e| map_io_err_to_transport_err(e, Some(relpath)),
        )?))
    }

    fn clone(&self, offset: Option<&UrlFragment>) -> Result<Box<dyn Transport>> {
        let new_base = match offset {
            Some(offset) => self.abspath(offset)?,
            None => self.base.clone(),
        };
        Ok(Box::new(LocalTransport::new(new_base.as_str())?))
    }

    fn abspath(&self, relpath: &UrlFragment) -> Result<Url> {
        let path = self.path.join(unescape(relpath)?);
        let path = breezy_osutils::path::normpath(path);

        breezy_urlutils::local_path_to_url(path.as_path())
            .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))
            .map(|url| Url::parse(&url).unwrap())
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
    ) -> Result<u64> {
        let path = self._abspath(relpath)?;
        let mut tmpfile = tempfile::Builder::new()
            .tempfile_in(path.parent().unwrap())
            .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;

        let n = std::io::copy(f, &mut tmpfile)
            .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        let f = tmpfile
            .persist(&path)
            .map_err(|e| map_io_err_to_transport_err(e.error, Some(relpath)))?;
        if let Some(permissions) = permissions {
            f.set_permissions(permissions)
                .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        }
        Ok(n)
    }

    fn delete(&self, relpath: &UrlFragment) -> Result<()> {
        let path = self._abspath(relpath)?;
        std::fs::remove_file(path).map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))
    }

    fn rmdir(&self, relpath: &UrlFragment) -> Result<()> {
        let path = self._abspath(relpath)?;
        std::fs::remove_dir(path).map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))
    }

    fn rename(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()> {
        let abs_from = self._abspath(rel_from)?;
        let abs_to = self._abspath(rel_to)?;

        std::fs::rename(abs_from, abs_to)
            .map_err(|e| map_io_err_to_transport_err(e, Some(rel_from)))
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
        &self,
        path: &'a UrlFragment,
        offsets: Vec<(u64, usize)>,
        adjust_for_latency: bool,
        upper_limit: Option<u64>,
    ) -> Box<dyn Iterator<Item = Result<(u64, Vec<u8>)>> + Send + 'a> {
        let offsets = if adjust_for_latency {
            crate::readv::sort_expand_and_combine(
                offsets,
                upper_limit,
                self.recommended_page_size(),
            )
        } else {
            offsets
        };

        use nix::libc::off_t;
        use nix::sys::uio::pread;
        let abspath = match self._abspath(path) {
            Ok(p) => p,
            Err(err) => return Box::new(std::iter::once(Err(err))),
        };
        let file = match std::fs::File::open(abspath) {
            Ok(f) => f,
            Err(err) => {
                return Box::new(std::iter::once(Err(map_io_err_to_transport_err(
                    err,
                    Some(path),
                ))))
            }
        };

        Box::new(
            offsets
                .into_iter()
                .map(move |(offset, len)| -> Result<(u64, Vec<u8>)> {
                    let mut buf = vec![0; len];
                    match pread(&file, &mut buf[..], offset as off_t) {
                        Ok(n) if n == len => Ok((offset, buf)),
                        Ok(n) => Err(Error::ShortReadvError(
                            path.to_owned(),
                            offset,
                            len as u64,
                            n as u64,
                        )),
                        Err(e) => Err(map_io_err_to_transport_err(
                            std::io::Error::from_raw_os_error(e as i32),
                            Some(path),
                        )),
                    }
                }),
        )
    }

    fn append_file(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn std::io::Read,
        permissions: Option<Permissions>,
    ) -> Result<u64> {
        let path = self._abspath(relpath)?;
        let mut file = std::fs::OpenOptions::new()
            .append(true)
            .create(true)
            .open(path)
            .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        if let Some(permissions) = permissions {
            file.set_permissions(permissions)
                .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        }
        let pos = file
            .seek(std::io::SeekFrom::End(0))
            .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        std::io::copy(f, &mut file).map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        Ok(pos)
    }

    #[cfg(unix)]
    fn readlink(&self, relpath: &UrlFragment) -> Result<String> {
        use std::os::unix::ffi::OsStrExt;
        let path = self._abspath(relpath)?;
        let target =
            std::fs::read_link(path).map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        Ok(escape(target.as_os_str().as_bytes(), None))
    }

    fn hardlink(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()> {
        let from = self._abspath(rel_from)?;
        let to = self._abspath(rel_to)?;
        std::fs::hard_link(from, to).map_err(|e| map_io_err_to_transport_err(e, Some(rel_from)))
    }

    #[cfg(target_family = "unix")]
    fn symlink(&self, source: &UrlFragment, link_name: &UrlFragment) -> Result<()> {
        let abs_to = self.abspath(link_name)?;
        let abs_link_dirpath = breezy_urlutils::dirname(abs_to.as_str(), true);
        let source_rel = breezy_urlutils::file_relpath(
            abs_link_dirpath.as_str(),
            self.abspath(source)?.as_str(),
        )?;

        std::os::unix::fs::symlink(source_rel, self._abspath(link_name)?)
            .map_err(|e| map_io_err_to_transport_err(e, Some(link_name)))
    }

    fn iter_files_recursive(&self) -> Box<dyn Iterator<Item = Result<String>>> {
        use std::os::unix::ffi::OsStrExt;
        let wd = walkdir::WalkDir::new(&self.path);

        fn walkdir_err(e: walkdir::Error) -> Error {
            let ioerr: std::io::Error = e.into();
            map_io_err_to_transport_err(ioerr, None)
        }

        let base = self.path.clone();

        Box::new(wd.into_iter().filter_map(move |e| match e {
            Ok(e) => {
                if !e.file_type().is_dir() {
                    Some(Ok(escape(
                        e.path()
                            .strip_prefix(base.as_path())
                            .unwrap()
                            .as_os_str()
                            .as_bytes(),
                        None,
                    )))
                } else {
                    None
                }
            }
            Err(e) => Some(Err(walkdir_err(e))),
        }))
    }

    fn open_write_stream(
        &self,
        relpath: &UrlFragment,
        permissions: Option<Permissions>,
    ) -> Result<Box<dyn WriteStream + Send + Sync>> {
        let path = self._abspath(relpath)?;
        let file = File::create(path).map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        file.set_len(0)
            .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        if let Some(permissions) = permissions {
            file.set_permissions(permissions)
                .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        }
        Ok(Box::new(file))
    }

    fn delete_tree(&self, relpath: &UrlFragment) -> Result<()> {
        let path = self._abspath(relpath)?;
        std::fs::remove_dir_all(path).map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))
    }

    fn r#move(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()> {
        let from = self._abspath(rel_from)?;
        let to = self._abspath(rel_to)?;

        // TODO(jelmer): Should remove destination if necessary
        std::fs::rename(from, to).map_err(|e| map_io_err_to_transport_err(e, Some(rel_from)))
    }

    fn list_dir(&self, relpath: &UrlFragment) -> Box<dyn Iterator<Item = Result<String>>> {
        use std::os::unix::ffi::OsStrExt;
        let path = match self._abspath(relpath) {
            Ok(p) => p,
            Err(err) => return Box::new(std::iter::once(Err(err))),
        };
        let entries = match std::fs::read_dir(path)
            .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))
        {
            Ok(e) => e,
            Err(err) => return Box::new(std::iter::once(Err(err))),
        };
        Box::new(
            entries
                .map(|entry| entry.map_err(|e| map_io_err_to_transport_err(e, None)))
                .map(|entry| {
                    entry.map(|entry| escape(entry.file_name().as_os_str().as_bytes(), None))
                }),
        )
    }

    fn listable(&self) -> bool {
        true
    }

    fn get_smart_medium(&self) -> Result<Box<dyn SmartMedium>> {
        Err(Error::NoSmartMedium)
    }

    fn lock_read(&self, relpath: &UrlFragment) -> Result<Box<dyn Lock + Send + Sync>> {
        let path = self._abspath(relpath)?;
        let lock = crate::filelock::ReadLock::new(path.as_path(), false)
            .map_err(lock_err_to_transport_err)?;
        Ok(Box::new(lock))
    }

    fn lock_write(&self, relpath: &UrlFragment) -> Result<Box<dyn Lock + Send + Sync>> {
        let path = self._abspath(relpath)?;
        let lock = crate::filelock::WriteLock::new(path.as_path(), false)
            .map_err(lock_err_to_transport_err)?;
        Ok(Box::new(lock))
    }

    fn copy_to(
        &self,
        relpaths: &[&UrlFragment],
        target: &dyn Transport,
        permissions: Option<Permissions>,
    ) -> Result<usize> {
        if relpaths.is_empty() {
            return Ok(0);
        }
        match target.local_abspath(relpaths[0]) {
            // Fall back to default
            Err(Error::NotLocalUrl(_)) => {
                return super::copy_to(self, target, relpaths, permissions)
            }
            Err(e) => return Err(e),
            _ => {}
        }

        let mut count = 0;
        relpaths.iter().try_for_each(|relpath| {
            let path = self._abspath(relpath)?;
            let target_path = target.local_abspath(relpath)?;
            std::fs::copy(path, &target_path)
                .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
            if let Some(permissions) = permissions.clone() {
                std::fs::set_permissions(target_path, permissions)
                    .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
            }
            count += 1;
            Ok::<(), Error>(())
        })?;
        Ok(count)
    }

    fn copy(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()> {
        std::fs::copy(
            self._abspath(rel_from)?.as_path(),
            self._abspath(rel_to)?.as_path(),
        )
        .map_err(|e| map_io_err_to_transport_err(e, Some(rel_from)))?;
        Ok(())
    }
}
