use crate::lock::{Lock, LockError};
use std::collections::HashMap;
use std::fs::{Metadata, Permissions};
use std::io::{Read, Seek};
use std::os::unix::fs::PermissionsExt;
use std::time::UNIX_EPOCH;
use url::Url;

pub enum Error {
    InProcessTransport,

    NoSmartMedium,

    NotLocalUrl(String),

    NoSuchFile(Option<String>),

    FileExists(Option<String>),

    TransportNotPossible,

    UrlError(url::ParseError),

    UrlutilsError(breezy_urlutils::Error),

    PermissionDenied(Option<String>),

    Io(std::io::Error),

    PathNotChild,

    UnexpectedEof,

    ShortReadvError(String, u64, u64, u64),

    LockContention(std::path::PathBuf),

    LockFailed(std::path::PathBuf, String),

    IsADirectoryError(Option<String>),

    NotADirectoryError(Option<String>),

    DirectoryNotEmptyError(Option<String>),
}

pub type Result<T> = std::result::Result<T, Error>;

pub type UrlFragment = str;

pub fn map_io_err_to_transport_err(err: std::io::Error, path: Option<&str>) -> Error {
    match err.kind() {
        std::io::ErrorKind::NotFound => Error::NoSuchFile(path.map(|p| p.to_string())),
        std::io::ErrorKind::AlreadyExists => Error::FileExists(path.map(|p| p.to_string())),
        std::io::ErrorKind::PermissionDenied => {
            Error::PermissionDenied(path.map(|p| p.to_string()))
        }
        // use of unstable library feature 'io_error_more'
        // https://github.com/rust-lang/rust/issues/86442
        //
        // std::io::ErrorKind::NotADirectoryError => Error::NotADirectoryError(None),
        // std::io::ErrorKind::IsADirectoryError => Error::IsADirectoryError(None),
        _ => match err.raw_os_error() {
            Some(nix::libc::ENOTDIR) => Error::NotADirectoryError(path.map(|p| p.to_string())),
            Some(nix::libc::EISDIR) => Error::IsADirectoryError(path.map(|p| p.to_string())),
            Some(nix::libc::ENOTEMPTY) => {
                Error::DirectoryNotEmptyError(path.map(|p| p.to_string()))
            }
            _ => Error::Io(err),
        },
    }
}

impl From<url::ParseError> for Error {
    fn from(err: url::ParseError) -> Self {
        Error::UrlError(err)
    }
}

impl From<breezy_urlutils::Error> for Error {
    fn from(err: breezy_urlutils::Error) -> Self {
        Error::UrlutilsError(err)
    }
}

pub struct Stat {
    pub size: usize,
    pub mode: u32,
    pub mtime: Option<f64>,
}

impl From<Metadata> for Stat {
    fn from(metadata: Metadata) -> Self {
        Stat {
            size: metadata.len() as usize,
            mode: metadata.permissions().mode(),
            mtime: metadata.modified().map_or(None, |t| {
                Some(t.duration_since(UNIX_EPOCH).unwrap().as_secs_f64())
            }),
        }
    }
}

impl Stat {
    pub fn is_dir(&self) -> bool {
        (self.mode as nix::libc::mode_t) & nix::libc::S_IFMT == nix::libc::S_IFDIR
    }

    pub fn is_file(&self) -> bool {
        (self.mode as nix::libc::mode_t) & nix::libc::S_IFMT == nix::libc::S_IFREG
    }
}

pub trait WriteStream: std::io::Write {
    fn sync_data(&self) -> std::io::Result<()>;
}

pub trait ReadStream: Read + Seek {}

pub trait Transport: std::fmt::Debug + 'static + Send + Sync {
    /// Return a URL for self that can be given to an external process.
    ///
    /// There is no guarantee that the URL can be accessed from a different
    /// machine - e.g. file:/// urls are only usable on the local machine,
    /// sftp:/// urls when the server is only bound to localhost are only
    /// usable from localhost etc.
    ///
    /// NOTE: This method may remove security wrappers (e.g. on chroot
    /// transports) and thus should *only* be used when the result will not
    /// be used to obtain a new transport within breezy. Ideally chroot
    /// transports would know enough to cause the external url to be the exact
    /// one used that caused the chrooting in the first place, but that is not
    /// currently the case.
    ///
    /// Returns: A URL that can be given to another process.
    /// Raises:InProcessTransport: If the transport is one that cannot be
    ///     accessed out of the current process (e.g. a MemoryTransport)
    ///     then InProcessTransport is raised.
    fn external_url(&self) -> Result<Url>;

    fn can_roundtrip_unix_modebits(&self) -> bool;

    fn get_bytes(&self, relpath: &UrlFragment) -> Result<Vec<u8>> {
        let mut file = self.get(relpath)?;
        let mut result = Vec::new();
        file.read_to_end(&mut result)
            .map_err(|err| map_io_err_to_transport_err(err, Some(relpath)))?;
        Ok(result)
    }

    fn get(&self, relpath: &UrlFragment) -> Result<Box<dyn ReadStream + Send + Sync>>;

    fn base(&self) -> Url;

    /// Ensure that the directory this transport references exists.
    ///
    /// This will create a directory if it doesn't exist.
    /// Returns: True if the directory was created, False otherwise.
    fn ensure_base(&self, permissions: Option<Permissions>) -> Result<bool> {
        if let Err(err) = self.mkdir(".", permissions) {
            match err {
                Error::FileExists(_) => Ok(false),
                Error::PermissionDenied(_) => Ok(false),
                Error::TransportNotPossible => {
                    if self.has(".")? {
                        Ok(false)
                    } else {
                        Err(err)
                    }
                }
                _ => Err(err),
            }
        } else {
            Ok(true)
        }
    }

    fn create_prefix(&self, permissions: Option<Permissions>) -> Result<()> {
        let mut cur_transport = self.clone(None)?;
        let mut needed = vec![];
        loop {
            match cur_transport.mkdir(".", permissions.clone()) {
                Err(Error::NoSuchFile(_)) => {
                    let new_transport = Transport::clone(cur_transport.as_ref(), Some(".."))?;
                    assert_ne!(
                        new_transport.base(),
                        cur_transport.base(),
                        "Failed to create path prefix for {}",
                        cur_transport.base()
                    );
                    needed.push(cur_transport);
                    cur_transport = new_transport;
                }
                Err(Error::FileExists(_)) | Ok(()) => {
                    break;
                }
                Err(err) => {
                    return Err(err);
                }
            }
        }

        while let Some(transport) = needed.pop() {
            transport.ensure_base(permissions.clone())?;
        }

        Ok(())
    }

    fn has(&self, relpath: &UrlFragment) -> Result<bool>;

    fn has_any(&self, relpaths: &[&UrlFragment]) -> Result<bool> {
        for relpath in relpaths {
            if self.has(relpath)? {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn mkdir(&self, relpath: &UrlFragment, permissions: Option<Permissions>) -> Result<()>;

    fn stat(&self, relpath: &UrlFragment) -> Result<Stat>;

    fn clone(&self, offset: Option<&UrlFragment>) -> Result<Box<dyn Transport>>;

    fn abspath(&self, relpath: &UrlFragment) -> Result<Url>;

    fn relpath(&self, abspath: &Url) -> Result<String>;

    fn put_file(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn Read,
        permissions: Option<Permissions>,
    ) -> Result<u64>;

    fn put_bytes(
        &self,
        relpath: &UrlFragment,
        data: &[u8],
        permissions: Option<Permissions>,
    ) -> Result<()> {
        let mut f = std::io::Cursor::new(data);
        self.put_file(relpath, &mut f, permissions)?;
        Ok(())
    }

    fn put_file_non_atomic(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn Read,
        permissions: Option<Permissions>,
        create_parent_dir: Option<bool>,
        dir_permissions: Option<Permissions>,
    ) -> Result<()> {
        match self.put_file(relpath, f, permissions.clone()) {
            Ok(_) => Ok(()),
            Err(Error::NoSuchFile(filename)) => {
                if create_parent_dir.unwrap_or(false) {
                    if let Some(parent) = relpath.rsplit_once('/').map(|x| x.0) {
                        self.mkdir(parent, dir_permissions)?;
                        self.put_file(relpath, f, permissions)?;
                        Ok(())
                    } else {
                        Err(Error::NoSuchFile(filename))
                    }
                } else {
                    Err(Error::NoSuchFile(filename))
                }
            }
            Err(err) => Err(err),
        }
    }

    fn put_bytes_non_atomic(
        &self,
        relpath: &UrlFragment,
        data: &[u8],
        permissions: Option<Permissions>,
        create_parent_dir: Option<bool>,
        dir_permissions: Option<Permissions>,
    ) -> Result<()> {
        let mut f = std::io::Cursor::new(data);
        self.put_file_non_atomic(
            relpath,
            &mut f,
            permissions,
            create_parent_dir,
            dir_permissions,
        )
    }

    fn delete(&self, relpath: &UrlFragment) -> Result<()>;

    fn rmdir(&self, relpath: &UrlFragment) -> Result<()>;

    fn rename(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()>;

    fn set_segment_parameter(&mut self, key: &str, value: Option<&str>) -> Result<()>;

    fn get_segment_parameters(&self) -> Result<HashMap<String, String>>;

    /// Return the recommended page size for this transport.
    ///
    /// This is potentially different for every path in a given namespace.
    /// For example, local transports might use an operating system call to
    /// get the block size for a given path, which can vary due to mount
    /// points.
    ///
    /// Returns: The page size in bytes.
    fn recommended_page_size(&self) -> usize {
        4 * 1024
    }

    fn is_readonly(&self) -> bool {
        false
    }

    fn readv<'a>(
        &self,
        relpath: &'a UrlFragment,
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
        let buf = match self.get_bytes(relpath) {
            Err(err) => return Box::new(std::iter::once(Err(err))),
            Ok(file) => file,
        };
        let mut file = std::io::Cursor::new(buf);
        Box::new(
            offsets
                .into_iter()
                .map(move |(offset, length)| -> Result<(u64, Vec<u8>)> {
                    let mut buf = vec![0; length];
                    match file.seek(std::io::SeekFrom::Start(offset)) {
                        Ok(_) => {}
                        Err(err) => match err.kind() {
                            std::io::ErrorKind::UnexpectedEof => {
                                return Err(Error::ShortReadvError(
                                    relpath.to_owned(),
                                    offset,
                                    length as u64,
                                    file.position() - offset,
                                ))
                            }
                            _ => return Err(map_io_err_to_transport_err(err, Some(relpath))),
                        },
                    }
                    match file.read_exact(&mut buf) {
                        Ok(_) => Ok((offset, buf)),
                        Err(err) => match err.kind() {
                            std::io::ErrorKind::UnexpectedEof => Err(Error::ShortReadvError(
                                relpath.to_owned(),
                                offset,
                                length as u64,
                                file.position() - offset,
                            )),
                            _ => Err(map_io_err_to_transport_err(err, Some(relpath))),
                        },
                    }
                }),
        )
    }

    fn append_bytes(
        &self,
        relpath: &UrlFragment,
        data: &[u8],
        permissions: Option<Permissions>,
    ) -> Result<u64> {
        let mut f = std::io::Cursor::new(data);
        self.append_file(relpath, &mut f, permissions)
    }

    fn append_file(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn std::io::Read,
        permissions: Option<Permissions>,
    ) -> Result<u64>;

    fn readlink(&self, relpath: &UrlFragment) -> Result<String>;

    fn hardlink(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()>;

    fn symlink(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()>;

    fn iter_files_recursive(&self) -> Box<dyn Iterator<Item = Result<String>>>;

    fn open_write_stream(
        &self,
        relpath: &UrlFragment,
        permissions: Option<Permissions>,
    ) -> Result<Box<dyn WriteStream + Send + Sync>>;

    fn delete_tree(&self, relpath: &UrlFragment) -> Result<()>;

    fn r#move(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()>;

    fn copy_tree(&self, from_relpath: &UrlFragment, to_relpath: &UrlFragment) -> Result<()> {
        let source = self.clone(Some(from_relpath))?;
        let target = self.clone(Some(to_relpath))?;

        // create target directory with the same rwx bits as source
        // use umask to ensure bits other than rwx are ignored
        let stat = self.stat(from_relpath)?;
        target.mkdir(".", Some(Permissions::from_mode(stat.mode)))?;
        source.copy_tree_to_transport(target.as_ref())?;
        Ok(())
    }

    fn copy_tree_to_transport(&self, to_transport: &dyn Transport) -> Result<()> {
        let mut files = Vec::new();
        let mut directories = vec![".".to_string()];
        while let Some(dir) = directories.pop() {
            if dir != "." {
                to_transport.mkdir(dir.as_str(), None)?;
            }
            for entry in self.list_dir(dir.as_str()) {
                let entry = entry?;
                let full_path = format!("{}/{}", dir, entry);
                let stat = self.stat(&full_path)?;
                if stat.is_dir() {
                    directories.push(full_path);
                } else {
                    files.push(full_path);
                }
            }
        }
        self.copy_to(
            files
                .iter()
                .map(|x| x.as_str())
                .collect::<Vec<_>>()
                .as_slice(),
            to_transport,
            None,
        )?;
        Ok(())
    }

    fn copy_to(
        &self,
        relpaths: &[&UrlFragment],
        to_transport: &dyn Transport,
        permissions: Option<Permissions>,
    ) -> Result<usize> {
        copy_to(self, to_transport, relpaths, permissions)
    }

    fn list_dir(&self, relpath: &UrlFragment) -> Box<dyn Iterator<Item = Result<String>>>;

    fn listable(&self) -> bool {
        true
    }

    fn lock_read(&self, relpath: &UrlFragment) -> Result<Box<dyn Lock + Send + Sync>>;

    fn lock_write(&self, relpath: &UrlFragment) -> Result<Box<dyn Lock + Send + Sync>>;

    fn local_abspath(&self, relpath: &UrlFragment) -> Result<std::path::PathBuf>;

    fn get_smart_medium(&self) -> Result<Box<dyn SmartMedium>>;

    fn copy(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()>;
}

pub fn copy_to<T: Transport + ?Sized>(
    from_transport: &T,
    to_transport: &dyn Transport,
    relpaths: &[&UrlFragment],
    permissions: Option<Permissions>,
) -> Result<usize> {
    let mut count = 0;
    relpaths.iter().try_for_each(|relpath| -> Result<()> {
        let mut src = from_transport.get(relpath)?;
        let mut target = to_transport.open_write_stream(relpath, permissions.clone())?;
        std::io::copy(&mut src, &mut target)
            .map_err(|e| map_io_err_to_transport_err(e, Some(relpath)))?;
        count += 1;
        Ok(())
    })?;
    Ok(count)
}

pub trait SmartMedium {}

pub mod local;

#[cfg(feature = "pyo3")]
pub mod pyo3;
pub mod readv;

#[cfg(unix)]
#[path = "fcntl-locks.rs"]
pub mod filelock;

#[cfg(target_os = "windows")]
#[path = "win32-locks.rs"]
pub mod filelock;

pub mod lock;
