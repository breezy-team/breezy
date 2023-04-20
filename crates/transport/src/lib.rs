use url::Url;
use std::fs::{Metadata, Permissions};
use std::os::unix::fs::PermissionsExt;

pub enum Error {
    InProcessTransport,

    NoSmartMedium,

    NotLocalUrl,

    NoSuchFile,

    FileExists,

    TransportNotPossible,

    NotImplemented,

    InvalidPath,

    UrlError(url::ParseError),

    PermissionDenied,

    Io(std::io::Error),

    PathNotChild,
}

pub type Result<T> = std::result::Result<T, Error>;

pub type UrlFragment = str;

impl From<std::io::Error> for Error {
    fn from(err: std::io::Error) -> Self {
        match err.kind() {
            std::io::ErrorKind::NotFound => Error::NoSuchFile,
            std::io::ErrorKind::AlreadyExists => Error::FileExists,
            std::io::ErrorKind::PermissionDenied => Error::PermissionDenied,
            _ => Error::Io(err),
        }
    }
}

impl From<url::ParseError> for Error {
    fn from(err: url::ParseError) -> Self {
        Error::UrlError(err)
    }
}

pub struct Stat {
    pub size: usize,
    pub mode: u32
}

impl From<Metadata> for Stat {
    fn from(metadata: Metadata) -> Self {
        Stat { size: metadata.len() as usize, mode: metadata.permissions().mode() }
    }
}

pub trait Transport: 'static + Send {
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
        file.read_to_end(&mut result).map_err(Error::from)?;
        Ok(result)
    }

    fn get(&self, relpath: &UrlFragment) -> Result<Box<dyn std::io::Read>>;

    fn base(&self) -> Url;

    /// Ensure that the directory this transport references exists.
    ///
    /// This will create a directory if it doesn't exist.
    /// Returns: True if the directory was created, False otherwise.
    fn ensure_base(&self, permissions: Option<Permissions>) -> Result<bool> {
        if let Err(err) = self.mkdir(".", permissions) {
            match err {
                Error::FileExists => Ok(false),
                Error::PermissionDenied => Ok(false),
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

    fn has(&self, relpath: &UrlFragment) -> Result<bool>;

    fn mkdir(&self, relpath: &UrlFragment, permissions: Option<Permissions>) -> Result<()>;

    fn stat(&self, relpath: &UrlFragment) -> Result<Stat>;

    fn clone(&self, offset: Option<&UrlFragment>) -> Result<Box<dyn Transport>>;

    fn abspath(&self, relpath: &UrlFragment) -> Result<Url>;
}

pub trait LocalTransport : Transport {
    fn local_abspath(&self, relpath: &UrlFragment) -> Result<std::path::PathBuf>;
}

pub trait SmartMedium {}

pub trait SmartTransport : Transport {
    fn get_smart_medium(&self) -> Result<Box<dyn SmartMedium>>;
}

pub mod local;
