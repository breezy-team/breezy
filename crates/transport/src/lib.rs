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

pub trait Transport: 'static + Send {
}

pub mod local;
