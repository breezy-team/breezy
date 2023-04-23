use crate::lock::Lock;
use std::collections::HashMap;
use std::fs::{Metadata, Permissions};
use std::io::{Read, Seek};
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

    ShortReadvError(String, u64, u64, u64),

    LockContention(std::path::PathBuf),

    LockFailed(std::path::PathBuf, String),

    IsADirectoryError(Option<String>),

    NotADirectoryError(Option<String>),

    DirectoryNotEmptyError(Option<String>),
}

fn sort_expand_and_combine(
    offsets: Vec<(u64, usize)>,
    upper_limit: Option<u64>,
    recommended_page_size: usize,
) -> Vec<(u64, usize)> {
    // Sort the offsets by start address.
    let mut sorted_offsets = offsets.to_vec();
    sorted_offsets.sort_unstable_by_key(|&(offset, _)| offset);

    // Short circuit empty requests.
    if sorted_offsets.is_empty() {
        return Vec::new();
    }

    // Expand the offsets by page size at either end.
    let maximum_expansion = recommended_page_size;
    let mut new_offsets = Vec::with_capacity(sorted_offsets.len());
    for (offset, length) in sorted_offsets {
        let expansion = maximum_expansion.saturating_sub(length);
        let reduction = expansion / 2;
        let new_offset = offset.saturating_sub(reduction as u64);
        let new_length = length + expansion;
        let new_length = if let Some(upper_limit) = upper_limit {
            let new_end = new_offset.saturating_add(new_length as u64);
            let new_length = std::cmp::min(upper_limit, new_end) - new_offset;
            std::cmp::max(0, new_length as isize) as usize
        } else {
            new_length
        };
        if new_length > 0 {
            new_offsets.push((new_offset, new_length));
        }
    }

    // Combine the expanded offsets.
    let mut result = Vec::with_capacity(new_offsets.len());
    if let Some((mut current_offset, mut current_length)) = new_offsets.first().copied() {
        let mut current_finish = current_offset + current_length as u64;
        for (offset, length) in new_offsets.iter().skip(1) {
            let finish = offset + *length as u64;
            if *offset > current_finish {
                result.push((current_offset, current_length));
                current_offset = *offset;
                current_length = *length;
                current_finish = finish;
            } else if finish > current_finish {
                current_finish = finish;
                current_length = (current_finish - current_offset) as usize;
            }
        }
        result.push((current_offset, current_length));
    }
    result
}

pub type Result<T> = std::result::Result<T, Error>;

pub type UrlFragment = str;

impl From<std::io::Error> for Error {
    fn from(err: std::io::Error) -> Self {
        match err.kind() {
            std::io::ErrorKind::NotFound => Error::NoSuchFile(None),
            std::io::ErrorKind::AlreadyExists => Error::FileExists(None),
            std::io::ErrorKind::PermissionDenied => Error::PermissionDenied(None),
            // use of unstable library feature 'io_error_more'
            // https://github.com/rust-lang/rust/issues/86442
            //
            // std::io::ErrorKind::NotADirectoryError => Error::NotADirectoryError(None),
            // std::io::ErrorKind::IsADirectoryError => Error::IsADirectoryError(None),
            _ => match err.raw_os_error() {
                Some(libc::ENOTDIR) => Error::NotADirectoryError(None),
                Some(libc::EISDIR) => Error::IsADirectoryError(None),
                Some(libc::ENOTEMPTY) => Error::DirectoryNotEmptyError(None),
                _ => Error::Io(err),
            },
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

impl Stat {
    pub fn is_dir(&self) -> bool {
        self.mode & libc::S_IFMT == libc::S_IFDIR
    }

    pub fn is_file(&self) -> bool {
        self.mode & libc::S_IFMT == libc::S_IFREG
    }
}

pub trait WriteStream: std::io::Write {
    fn sync_all(&self) -> std::io::Result<()>;
}

pub trait ReadStream: Read + Seek {}

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

    fn can_roundtrip_unix_modebits(&self) -> bool;

    fn get_bytes(&self, relpath: &UrlFragment) -> Result<Vec<u8>> {
        let mut file = self.get(relpath)?;
        let mut result = Vec::new();
        file.read_to_end(&mut result)?;
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
        let mut needed = vec![cur_transport.clone(None)?];
        loop {
            let new_transport = Transport::clone(cur_transport.as_ref(), Some(".."))?;
            if new_transport.base() == cur_transport.base() {
                panic!("Failed to create path prefix for {}", cur_transport.base());
            }
            match new_transport.mkdir(".", permissions.clone()) {
                Err(Error::NoSuchFile(_)) => {
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
                    if let Some(parent) = relpath.rsplitn(2, '/').nth(1) {
                        self.mkdir(parent, dir_permissions)?;
                        self.put_file(relpath, f, permissions.clone())?;
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
    ) -> Box<dyn Iterator<Item = Result<(u64, Vec<u8>)>> + 'a> {
        let offsets = if adjust_for_latency {
            sort_expand_and_combine(offsets, upper_limit, self.recommended_page_size())
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
                            _ => return Err(Error::from(err)),
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
                            _ => Err(Error::from(err)),
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
    ) -> Result<()> {
        relpaths.iter().try_for_each(|relpath| -> Result<()> {
            let mut src = self.get(relpath)?;
            let mut target = to_transport.open_write_stream(relpath, permissions.clone())?;
            std::io::copy(&mut src, &mut target)?;
            Ok(())
        })?;
        Ok(())
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

pub trait SmartMedium {}

pub mod local;

#[cfg(feature = "pyo3")]
pub mod pyo3;

#[cfg(unix)]
#[path = "fcntl-locks.rs"]
pub mod locks;

pub mod lock;
