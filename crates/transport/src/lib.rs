use std::collections::HashMap;
use std::fs::{Metadata, Permissions};
use std::io::{BufRead, Read, Seek};
use std::os::unix::fs::PermissionsExt;
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
}

pub type Result<T> = std::result::Result<T, Error>;

pub type UrlFragment = str;

impl From<std::io::Error> for Error {
    fn from(err: std::io::Error) -> Self {
        match err.kind() {
            std::io::ErrorKind::NotFound => Error::NoSuchFile(None),
            std::io::ErrorKind::AlreadyExists => Error::FileExists(None),
            std::io::ErrorKind::PermissionDenied => Error::PermissionDenied(None),
            _ => Error::Io(err),
        }
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

impl From<atomicwrites::Error<std::io::Error>> for Error {
    fn from(err: atomicwrites::Error<std::io::Error>) -> Self {
        match err {
            atomicwrites::Error::Internal(err) => err.into(),
            atomicwrites::Error::User(err) => err.into(),
        }
    }
}

pub struct Stat {
    pub size: usize,
    pub mode: u32,
}

impl From<Metadata> for Stat {
    fn from(metadata: Metadata) -> Self {
        Stat {
            size: metadata.len() as usize,
            mode: metadata.permissions().mode(),
        }
    }
}

pub trait Transport: 'static + Send + Sync {
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

    fn get_bytes(&self, relpath: &UrlFragment) -> Result<Vec<u8>> {
        let mut file = self.get(relpath)?;
        let mut result = Vec::new();
        file.read_to_end(&mut result)?;
        Ok(result)
    }

    fn get(&self, relpath: &UrlFragment) -> Result<Box<dyn Read + Send + Sync>>;

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
        let mut needed = Vec::new();
        loop {
            let new_transport = Transport::clone(cur_transport.as_ref(), Some(".."))?;
            if new_transport.base() == cur_transport.base() {
                panic!("Failed to create path prefix for {}", cur_transport.base());
            }
            if let Err(err) = new_transport.mkdir(".", permissions.clone()) {
                match err {
                    Error::NoSuchFile(_) => {
                        needed.push(cur_transport);
                        cur_transport = new_transport;
                    }
                    Error::FileExists(_) => {
                        break;
                    }
                    _ => {
                        return Err(err);
                    }
                }
            } else {
                break;
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
    ) -> Result<()>;

    fn put_bytes(
        &self,
        relpath: &UrlFragment,
        data: &[u8],
        permissions: Option<Permissions>,
    ) -> Result<()> {
        let mut f = std::io::Cursor::new(data);
        self.put_file(relpath, &mut f, permissions)
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
                    if let Some(parent) = relpath.rsplitn(2, '/').nth(1) {
                        self.mkdir(parent, dir_permissions)?;
                        self.put_file(relpath, f, permissions.clone())
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
        &'a self,
        relpath: &UrlFragment,
        offsets: &'a [(u64, usize)],
    ) -> Box<dyn Iterator<Item = Result<Vec<u8>>> + '_> {
        let buf = match self.get_bytes(relpath) {
            Err(err) => return Box::new(std::iter::once(Err(err.into()))),
            Ok(file) => file,
        };
        let mut file = std::io::Cursor::new(buf);
        Box::new(
            offsets
                .iter()
                .map(move |(offset, length)| -> Result<Vec<u8>> {
                    let mut buf = vec![0; *length];
                    file.seek(std::io::SeekFrom::Start(*offset))?;
                    file.read_exact(&mut buf)?;
                    Ok(buf)
                }),
        )
    }

    fn append_bytes(
        &self,
        relpath: &UrlFragment,
        data: &[u8],
        permissions: Option<Permissions>,
    ) -> Result<()> {
        let mut f = std::io::Cursor::new(data);
        self.append_file(relpath, &mut f, permissions)
    }

    fn append_file(
        &self,
        relpath: &UrlFragment,
        f: &mut dyn std::io::Read,
        permissions: Option<Permissions>,
    ) -> Result<()>;

    fn readlink(&self, relpath: &UrlFragment) -> Result<String>;

    fn hardlink(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()>;

    fn symlink(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()>;

    fn iter_files_recursive(&self) -> Box<dyn Iterator<Item = Result<String>>>;

    fn open_write_stream(
        &self,
        relpath: &UrlFragment,
        permissions: Option<Permissions>,
    ) -> Result<Box<dyn std::io::Write + Send + Sync>>;

    fn delete_tree(&self, relpath: &UrlFragment) -> Result<()>;

    fn move_(&self, rel_from: &UrlFragment, rel_to: &UrlFragment) -> Result<()>;
}

pub trait ListableTransport: Transport {
    fn list_dir(&self, relpath: &UrlFragment) -> Box<dyn Iterator<Item = Result<String>>>;

    fn listable(&self) -> bool {
        true
    }
}

pub trait Lock {
    fn unlock(&mut self) -> Result<()>;
}

pub trait LockableTransport: Transport {
    fn lock_read(&self, relpath: &UrlFragment) -> Result<Box<dyn Lock + Send + Sync>>;

    fn lock_write(&self, relpath: &UrlFragment) -> Result<Box<dyn Lock + Send + Sync>>;

    fn is_read_locked(&self, relpath: &UrlFragment) -> Result<bool>;
}

pub trait LocalTransport: Transport {
    fn local_abspath(&self, relpath: &UrlFragment) -> Result<std::path::PathBuf>;
}

pub trait SmartMedium {}

pub trait SmartTransport: Transport {
    fn get_smart_medium(&self) -> Result<Box<dyn SmartMedium>>;
}

pub mod local;

#[cfg(feature = "pyo3")]
pub mod pyo3;
