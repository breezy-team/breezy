use byteorder::{BigEndian, ReadBytesExt, WriteBytesExt};
use std::io::Cursor;
use std::io::{Read, Seek, SeekFrom, Write};
use std::os::unix::io::AsRawFd;
use std::os::unix::io::FromRawFd;
use std::sync::Mutex;

#[derive(Debug)]
pub enum Error {
    Io(std::io::Error),
    Utf8(std::str::Utf8Error),
    Other(u32, String, String),
    Eof(String, String),
    NoSuchFile(String, String),
    PermissionDenied(String, String),
    Failure(String, String),
    BadMessage(String, String),
    NoConnection(String, String),
    ConnectionLost(String, String),
    OpUnsupported(String, String),
    InvalidHandle(String, String),
    NoSuchPath(String, String),
    FileAlreadyExists(String, String),
    WriteProtect(String, String),
    NoMedia(String, String),
    NoSpaceOnFilesystem(String, String),
    QuotaExceeded(String, String),
    UnknownPrincipal(String, String),
    LockConflict(String, String),
    DirNotEmpty(String, String),
    NotADirectory(String, String),
    InvalidFilename(String, String),
    LinkLoop(String, String),
    CannotDelete(String, String),
    InvalidParameter(String, String),
    FileIsADirectory(String, String),
    ByteRangeLockConflict(String, String),
    ByteRangeLockRefused(String, String),
    DeletePending(String, String),
    FileCorrupt(String, String),
    OwnerInvalid(String, String),
    GroupInvalid(String, String),
    NoMatchingByteRangeLock(String, String),
}

impl From<std::io::Error> for Error {
    fn from(err: std::io::Error) -> Self {
        Error::Io(err)
    }
}

impl From<std::str::Utf8Error> for Error {
    fn from(err: std::str::Utf8Error) -> Self {
        Error::Utf8(err)
    }
}

type Result<R> = std::result::Result<R, Error>;

pub trait Channel: Read + Write + AsRawFd + Send + Sync {}

pub const SSH_FILEXFER_ATTR_SIZE: u32 = 0x00000001;
// Note: SSH_FILEXFER_ATTR_UIDGID is deprecated in favor of SSH_FILEXFER_ATTR_OWNERGROUP, and not
// included in the RFC
pub const SSH_FILEXFER_ATTR_UIDGID: u32 = 0x00000002;
pub const SSH_FILEXFER_ATTR_PERMISSIONS: u32 = 0x00000004;
pub const SSH_FILEXFER_ATTR_ACCESSTIME: u32 = 0x00000008;
pub const SSH_FILEXFER_ATTR_CREATETIME: u32 = 0x00000010;
pub const SSH_FILEXFER_ATTR_MODIFYTIME: u32 = 0x00000020;
pub const SSH_FILEXFER_ATTR_ACL: u32 = 0x00000040;
pub const SSH_FILEXFER_ATTR_OWNERGROUP: u32 = 0x00000080;
pub const SSH_FILEXFER_ATTR_SUBSECOND_TIMES: u32 = 0x00000100;
pub const SSH_FILEXFER_ATTR_BITS: u32 = 0x00000200;
pub const SSH_FILEXFER_ATTR_ALLOCATION_SIZE: u32 = 0x00000400;
pub const SSH_FILEXFER_ATTR_TEXT_HINT: u32 = 0x00000800;
pub const SSH_FILEXFER_ATTR_MIME_TYPE: u32 = 0x00001000;
pub const SSH_FILEXFER_ATTR_LINK_COUNT: u32 = 0x00002000;
pub const SSH_FILEXFER_ATTR_UNTRANSLATED_NAME: u32 = 0x00004000;
pub const SSH_FILEXFER_ATTR_CTIME: u32 = 0x00008000;
pub const SSH_FILEXFER_ATTR_EXTENDED: u32 = 0x80000000;

const SSH_FILEXFER_ATTR_KNOWN_TEXT: u8 = 0x00;
const SSH_FILEXFER_ATTR_GUESSED_TEXT: u8 = 0x01;
const SSH_FILEXFER_ATTR_KNOWN_BINARY: u8 = 0x02;
const SSH_FILEXFER_ATTR_GUESSED_BINARY: u8 = 0x03;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum TextHint {
    KnownText,
    GuessedText,
    KnownBinary,
    GuessedBinary,
}

impl From<TextHint> for u8 {
    fn from(hint: TextHint) -> Self {
        match hint {
            TextHint::KnownText => SSH_FILEXFER_ATTR_KNOWN_TEXT,
            TextHint::GuessedText => SSH_FILEXFER_ATTR_GUESSED_TEXT,
            TextHint::KnownBinary => SSH_FILEXFER_ATTR_KNOWN_BINARY,
            TextHint::GuessedBinary => SSH_FILEXFER_ATTR_GUESSED_BINARY,
        }
    }
}

impl From<u8> for TextHint {
    fn from(hint: u8) -> Self {
        match hint {
            SSH_FILEXFER_ATTR_KNOWN_TEXT => TextHint::KnownText,
            SSH_FILEXFER_ATTR_GUESSED_TEXT => TextHint::GuessedText,
            SSH_FILEXFER_ATTR_KNOWN_BINARY => TextHint::KnownBinary,
            SSH_FILEXFER_ATTR_GUESSED_BINARY => TextHint::GuessedBinary,
            _ => panic!("Invalid text hint"),
        }
    }
}

pub const SSH_FILEXFER_ATTR_FLAGS_READONLY: u32 = 0x00000001;
pub const SSH_FILEXFER_ATTR_FLAGS_SYSTEM: u32 = 0x00000002;
pub const SSH_FILEXFER_ATTR_FLAGS_HIDDEN: u32 = 0x00000004;
pub const SSH_FILEXFER_ATTR_FLAGS_CASE_INSENSITIVE: u32 = 0x00000008;
pub const SSH_FILEXFER_ATTR_FLAGS_ARCHIVE: u32 = 0x00000010;
pub const SSH_FILEXFER_ATTR_FLAGS_ENCRYPTED: u32 = 0x00000020;
pub const SSH_FILEXFER_ATTR_FLAGS_COMPRESSED: u32 = 0x00000040;
pub const SSH_FILEXFER_ATTR_FLAGS_SPARSE: u32 = 0x00000080;
pub const SSH_FILEXFER_ATTR_FLAGS_APPEND_ONLY: u32 = 0x00000100;
pub const SSH_FILEXFER_ATTR_FLAGS_IMMUTABLE: u32 = 0x00000200;
pub const SSH_FILEXFER_ATTR_FLAGS_SYNC: u32 = 0x00000400;
pub const SSH_FILEXFER_ATTR_FLAGS_TRANSLATION_ERR: u32 = 0x00000800;

const SSH_FILEXFER_TYPE_REGULAR: u8 = 1;
const SSH_FILEXFER_TYPE_DIRECTORY: u8 = 2;
const SSH_FILEXFER_TYPE_SYMLINK: u8 = 3;
const SSH_FILEXFER_TYPE_SPECIAL: u8 = 4;
const SSH_FILEXFER_TYPE_UNKNOWN: u8 = 5;
const SSH_FILEXFER_TYPE_SOCKET: u8 = 6;
const SSH_FILEXFER_TYPE_CHAR_DEVICE: u8 = 7;
const SSH_FILEXFER_TYPE_BLOCK_DEVICE: u8 = 8;
const SSH_FILEXFER_TYPE_FIFO: u8 = 9;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Regular,
    Directory,
    Symlink,
    Special,
    Unknown,
    Socket,
    CharDevice,
    BlockDevice,
    Fifo,
}

impl Default for Kind {
    fn default() -> Self {
        Kind::Unknown
    }
}

impl From<Kind> for u8 {
    fn from(val: Kind) -> Self {
        match val {
            Kind::Regular => SSH_FILEXFER_TYPE_REGULAR,
            Kind::Directory => SSH_FILEXFER_TYPE_DIRECTORY,
            Kind::Symlink => SSH_FILEXFER_TYPE_SYMLINK,
            Kind::Special => SSH_FILEXFER_TYPE_SPECIAL,
            Kind::Unknown => SSH_FILEXFER_TYPE_UNKNOWN,
            Kind::Socket => SSH_FILEXFER_TYPE_SOCKET,
            Kind::CharDevice => SSH_FILEXFER_TYPE_CHAR_DEVICE,
            Kind::BlockDevice => SSH_FILEXFER_TYPE_BLOCK_DEVICE,
            Kind::Fifo => SSH_FILEXFER_TYPE_FIFO,
        }
    }
}

impl From<u8> for Kind {
    fn from(kind: u8) -> Self {
        match kind {
            SSH_FILEXFER_TYPE_REGULAR => Kind::Regular,
            SSH_FILEXFER_TYPE_DIRECTORY => Kind::Directory,
            SSH_FILEXFER_TYPE_SYMLINK => Kind::Symlink,
            SSH_FILEXFER_TYPE_SPECIAL => Kind::Special,
            SSH_FILEXFER_TYPE_UNKNOWN => Kind::Unknown,
            SSH_FILEXFER_TYPE_SOCKET => Kind::Socket,
            SSH_FILEXFER_TYPE_CHAR_DEVICE => Kind::CharDevice,
            SSH_FILEXFER_TYPE_BLOCK_DEVICE => Kind::BlockDevice,
            SSH_FILEXFER_TYPE_FIFO => Kind::Fifo,
            f => panic!("Unknown file type {}", f),
        }
    }
}

const SSH_FXP_INIT: u8 = 1;
const SSH_FXP_VERSION: u8 = 2;
const SSH_FXP_OPEN: u8 = 3;
const SSH_FXP_CLOSE: u8 = 4;
const SSH_FXP_READ: u8 = 5;
const SSH_FXP_WRITE: u8 = 6;
const SSH_FXP_LSTAT: u8 = 7;
const SSH_FXP_FSTAT: u8 = 8;
const SSH_FXP_SETSTAT: u8 = 9;
const SSH_FXP_FSETSTAT: u8 = 10;
const SSH_FXP_OPENDIR: u8 = 11;
const SSH_FXP_READDIR: u8 = 12;
const SSH_FXP_REMOVE: u8 = 13;
const SSH_FXP_MKDIR: u8 = 14;
const SSH_FXP_RMDIR: u8 = 15;
const SSH_FXP_REALPATH: u8 = 16;
const SSH_FXP_STAT: u8 = 17;
const SSH_FXP_RENAME: u8 = 18;
const SSH_FXP_READLINK: u8 = 19;
const SSH_FXP_SYMLINK: u8 = 20;
const SSH_FXP_LINK: u8 = 21;
const SSH_FXP_BLOCK: u8 = 22;
const SSH_FXP_UNBLOCK: u8 = 23;
const SSH_FXP_STATUS: u8 = 101;
const SSH_FXP_HANDLE: u8 = 102;
const SSH_FXP_DATA: u8 = 103;
const SSH_FXP_NAME: u8 = 104;
const SSH_FXP_ATTRS: u8 = 105;
const SSH_FXP_EXTENDED: u8 = 200;
const SSH_FXP_EXTENDED_REPLY: u8 = 201;

const SSH_FX_OK: u32 = 0;
const SSH_FX_EOF: u32 = 1;
const SSH_FX_NO_SUCH_FILE: u32 = 2;
const SSH_FX_PERMISSION_DENIED: u32 = 3;
const SSH_FX_FAILURE: u32 = 4;
const SSH_FX_BAD_MESSAGE: u32 = 5;
const SSH_FX_NO_CONNECTION: u32 = 6;
const SSH_FX_CONNECTION_LOST: u32 = 7;
const SSH_FX_OP_UNSUPPORTED: u32 = 8;
const SSH_FX_INVALID_HANDLE: u32 = 9;
const SSH_FX_NO_SUCH_PATH: u32 = 10;
const SSH_FX_FILE_ALREADY_EXISTS: u32 = 11;
const SSH_FX_WRITE_PROTECT: u32 = 12;
const SSH_FX_NO_MEDIA: u32 = 13;
const SSH_FX_NO_SPACE_ON_FILESYSTEM: u32 = 14;
const SSH_FX_QUOTA_EXCEEDED: u32 = 15;
const SSH_FX_UNKNOWN_PRINCIPAL: u32 = 16;
const SSH_FX_LOCK_CONFLICT: u32 = 17;
const SSH_FX_DIR_NOT_EMPTY: u32 = 18;
const SSH_FX_NOT_A_DIRECTORY: u32 = 19;
const SSH_FX_INVALID_FILENAME: u32 = 20;
const SSH_FX_LINK_LOOP: u32 = 21;
const SSH_FX_CANNOT_DELETE: u32 = 22;
const SSH_FX_INVALID_PARAMETER: u32 = 23;
const SSH_FX_FILE_IS_A_DIRECTORY: u32 = 24;
const SSH_FX_BYTE_RANGE_LOCK_CONFLICT: u32 = 25;
const SSH_FX_BYTE_RANGE_LOCK_REFUSED: u32 = 26;
const SSH_FX_DELETE_PENDING: u32 = 27;
const SSH_FX_FILE_CORRUPT: u32 = 28;
const SSH_FX_OWNER_INVALID: u32 = 29;
const SSH_FX_GROUP_INVALID: u32 = 30;
const SSH_FX_NO_MATCHING_BYTE_RANGE_LOCK: u32 = 31;

pub const SFTP_FLAG_READ: u32 = 0x00000001;
pub const SFTP_FLAG_WRITE: u32 = 0x00000002;
pub const SFTP_FLAG_APPEND: u32 = 0x00000004;
pub const SFTP_FLAG_CREAT: u32 = 0x00000008;
pub const SFTP_FLAG_TRUNC: u32 = 0x00000010;
pub const SFTP_FLAG_EXCL: u32 = 0x00000020;

pub const SSH_FXF_RENAME_OVERWRITE: u32 = 0x00000001;
pub const SSH_FXF_RENAME_ATOMIC: u32 = 0x00000002;
pub const SSH_FXF_RENAME_NATIVE: u32 = 0x00000004;

pub const SSH_FXF_ACCESS_DISPOSITION: u32 = 0x00000007;
pub const SSH_FXF_CREATE_NEW: u32 = 0x00000000;
pub const SSH_FXF_CREATE_TRUNCATE: u32 = 0x00000001;
pub const SSH_FXF_OPEN_EXISTING: u32 = 0x00000002;
pub const SSH_FXF_OPEN_OR_CREATE: u32 = 0x00000003;
pub const SSH_FXF_TRUNCATE_EXISTING: u32 = 0x00000004;
pub const SSH_FXF_APPEND_DATA: u32 = 0x00000008;
pub const SSH_FXF_APPEND_DATA_ATOMIC: u32 = 0x00000010;
pub const SSH_FXF_TEXT_MODE: u32 = 0x00000020;
pub const SSH_FXF_BLOCK_READ: u32 = 0x00000040;
pub const SSH_FXF_BLOCK_WRITE: u32 = 0x00000080;
pub const SSH_FXF_BLOCK_DELETE: u32 = 0x00000100;
pub const SSH_FXF_BLOCK_ADVISORY: u32 = 0x00000200;
pub const SSH_FXF_NOFOLLOW: u32 = 0x00000400;
pub const SSH_FXF_DELETE_ON_CLOSE: u32 = 0x00000800;
pub const SSH_FXF_ACCESS_AUDIT_ALARM_INFO: u32 = 0x00001000;
pub const SSH_FXF_ACCESS_BACKUP: u32 = 0x00002000;
pub const SSH_FXF_BACKUP_STREAM: u32 = 0x00004000;
pub const SSH_FXF_OVERRIDE_OWNER: u32 = 0x00008000;

pub const ACE4_READ_DATA: u32 = 0x00000001;
pub const ACE4_LIST_DIRECTORY: u32 = 0x00000001;
pub const ACE4_WRITE_DATA: u32 = 0x00000002;
pub const ACE4_ADD_FILE: u32 = 0x00000002;
pub const ACE4_APPEND_DATA: u32 = 0x00000004;
pub const ACE4_ADD_SUBDIRECTORY: u32 = 0x00000004;
pub const ACE4_READ_NAMED_ATTRS: u32 = 0x00000008;
pub const ACE4_WRITE_NAMED_ATTRS: u32 = 0x00000010;
pub const ACE4_EXECUTE: u32 = 0x00000020;
pub const ACE4_DELETE_CHILD: u32 = 0x00000040;
pub const ACE4_READ_ATTRIBUTES: u32 = 0x00000080;
pub const ACE4_WRITE_ATTRIBUTES: u32 = 0x00000100;
pub const ACE4_DELETE: u32 = 0x00010000;
pub const ACE4_READ_ACL: u32 = 0x00020000;
pub const ACE4_WRITE_ACL: u32 = 0x00040000;
pub const ACE4_WRITE_OWNER: u32 = 0x00080000;
pub const ACE4_SYNCHRONIZE: u32 = 0x00100000;

#[derive(Debug, PartialEq, Eq, Clone, Default)]
pub struct Attributes {
    pub size: Option<u64>,

    pub uid: Option<u32>,
    pub gid: Option<u32>,

    pub allocation_size: Option<u64>,
    pub owner: Option<String>,
    pub group: Option<String>,
    pub permissions: Option<u32>,
    pub access_time: Option<(u64, Option<u32>)>,
    pub create_time: Option<(u64, Option<u32>)>,
    pub modify_time: Option<(u64, Option<u32>)>,
    pub ctime: Option<(u64, Option<u32>)>,
    // TODO(jelmer): Expand acl data
    pub acl: Option<Vec<u8>>,
    pub attrib_bits: Option<u32>,
    pub attrib_bits_valid: Option<u32>,
    pub text_hint: Option<TextHint>,
    pub mime_type: Option<String>,
    pub link_count: Option<u32>,
    pub untranslated_name: Option<Vec<u8>>,
    pub extended: Option<Vec<(String, String)>>,
}

impl Attributes {
    pub fn new() -> Self {
        Self {
            uid: None,
            gid: None,
            size: None,
            allocation_size: None,
            owner: None,
            group: None,
            permissions: None,
            access_time: None,
            create_time: None,
            modify_time: None,
            ctime: None,
            acl: None,
            attrib_bits: None,
            attrib_bits_valid: None,
            text_hint: None,
            mime_type: None,
            link_count: None,
            untranslated_name: None,
            extended: None,
        }
    }

    pub fn serialize(&self) -> std::io::Result<Vec<u8>> {
        let mut valid_attribute_flags: u32 = 0;

        let buf = Vec::new();
        let mut writer = Cursor::new(buf);

        writer.write_u32::<BigEndian>(valid_attribute_flags)?;

        // The RFC specifies that there is a "file_type" byte here,
        // but implementations don't seem to use it.

        if let Some(size) = self.size {
            writer.write_u64::<BigEndian>(size)?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_SIZE;
        }

        if let Some(allocation_size) = self.allocation_size {
            writer.write_u64::<BigEndian>(allocation_size)?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_ALLOCATION_SIZE;
        }

        // The RFC doesn't document UIDGID, but implementations use it.
        if let Some(uid) = self.uid {
            writer.write_u32::<BigEndian>(uid)?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_UIDGID;
        }

        if let Some(gid) = self.gid {
            writer.write_u32::<BigEndian>(gid)?;
            assert!(valid_attribute_flags & SSH_FILEXFER_ATTR_UIDGID != 0);
        } else {
            assert!(valid_attribute_flags & SSH_FILEXFER_ATTR_UIDGID == 0);
        }

        if let Some(owner) = self.owner.as_ref() {
            writer.write_u32::<BigEndian>(owner.len() as u32)?;
            writer.write_all(owner.as_bytes())?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_OWNERGROUP;
        }

        if let Some(group) = self.group.as_ref() {
            writer.write_u32::<BigEndian>(group.len() as u32)?;
            writer.write_all(group.as_bytes())?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_OWNERGROUP;
        }

        if let Some(permissions) = self.permissions {
            writer.write_u32::<BigEndian>(permissions)?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_PERMISSIONS;
        }

        if let Some(access_time) = self.access_time {
            writer.write_u64::<BigEndian>(access_time.0)?;
            if let Some(access_time_nseconds) = access_time.1 {
                writer.write_u32::<BigEndian>(access_time_nseconds)?;
                valid_attribute_flags |= SSH_FILEXFER_ATTR_SUBSECOND_TIMES;
            }
            valid_attribute_flags |= SSH_FILEXFER_ATTR_ACCESSTIME;
        }

        if let Some(create_time) = self.create_time {
            writer.write_u64::<BigEndian>(create_time.0)?;
            if let Some(create_time_nseconds) = create_time.1 {
                assert!(valid_attribute_flags & SSH_FILEXFER_ATTR_SUBSECOND_TIMES != 0);
                writer.write_u32::<BigEndian>(create_time_nseconds)?;
            } else {
                assert!(valid_attribute_flags & SSH_FILEXFER_ATTR_SUBSECOND_TIMES == 0);
            }
            valid_attribute_flags |= SSH_FILEXFER_ATTR_CREATETIME;
        }

        if let Some(modify_time) = self.modify_time {
            writer.write_u64::<BigEndian>(modify_time.0)?;
            if let Some(modify_time_nseconds) = modify_time.1 {
                assert!(valid_attribute_flags & SSH_FILEXFER_ATTR_SUBSECOND_TIMES != 0);
                writer.write_u32::<BigEndian>(modify_time_nseconds)?;
            } else {
                assert!(valid_attribute_flags & SSH_FILEXFER_ATTR_SUBSECOND_TIMES == 0);
            }
            valid_attribute_flags |= SSH_FILEXFER_ATTR_MODIFYTIME;
        }

        if let Some(ctime) = self.ctime {
            writer.write_u64::<BigEndian>(ctime.0)?;
            if let Some(ctime_nseconds) = ctime.1 {
                assert!(valid_attribute_flags & SSH_FILEXFER_ATTR_SUBSECOND_TIMES != 0);
                writer.write_u32::<BigEndian>(ctime_nseconds)?;
            } else {
                assert!(valid_attribute_flags & SSH_FILEXFER_ATTR_SUBSECOND_TIMES == 0);
            }
            valid_attribute_flags |= SSH_FILEXFER_ATTR_CTIME;
        }

        if let Some(acl) = self.acl.as_ref() {
            writer.write_u32::<BigEndian>(acl.len() as u32)?;
            writer.write_all(acl.as_slice())?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_ACL;
        }

        if let Some(attrib_bits) = self.attrib_bits {
            writer.write_u32::<BigEndian>(attrib_bits)?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_BITS;
        }

        if let Some(attrib_bits_valid) = self.attrib_bits_valid {
            writer.write_u32::<BigEndian>(attrib_bits_valid)?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_BITS;
        }

        if let Some(text_hint) = self.text_hint {
            writer.write_u8(text_hint.into())?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_TEXT_HINT;
        }

        if let Some(mime_type) = self.mime_type.as_ref() {
            writer.write_u32::<BigEndian>(mime_type.len() as u32)?;
            writer.write_all(mime_type.as_bytes())?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_MIME_TYPE;
        }

        if let Some(link_count) = self.link_count {
            writer.write_u32::<BigEndian>(link_count)?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_LINK_COUNT;
        }

        if let Some(untranslated_name) = self.untranslated_name.as_ref() {
            writer.write_u32::<BigEndian>(untranslated_name.len() as u32)?;
            writer.write_all(untranslated_name.as_slice())?;
            valid_attribute_flags |= SSH_FILEXFER_ATTR_UNTRANSLATED_NAME;
        }

        if let Some(extended) = self.extended.as_ref() {
            writer.write_u32::<BigEndian>(extended.len() as u32)?;
            for (key, value) in extended.iter() {
                writer.write_u32::<BigEndian>(key.len() as u32)?;
                writer.write_all(key.as_bytes())?;
                writer.write_u32::<BigEndian>(value.len() as u32)?;
                writer.write_all(value.as_bytes())?;
            }
            valid_attribute_flags |= SSH_FILEXFER_ATTR_EXTENDED;
        }

        writer.seek(SeekFrom::Start(0))?;
        writer.write_u32::<BigEndian>(valid_attribute_flags)?;

        Ok(writer.into_inner())
    }

    fn deserialize(reader: &mut Cursor<&[u8]>) -> std::io::Result<Self> {
        let valid_attribute_flags = reader.read_u32::<BigEndian>()?;

        let size = if valid_attribute_flags & SSH_FILEXFER_ATTR_SIZE != 0 {
            Some(reader.read_u64::<BigEndian>()?)
        } else {
            None
        };

        let (uid, gid) = if valid_attribute_flags & SSH_FILEXFER_ATTR_UIDGID != 0 {
            (
                Some(reader.read_u32::<BigEndian>()?),
                Some(reader.read_u32::<BigEndian>()?),
            )
        } else {
            (None, None)
        };

        let allocation_size = if valid_attribute_flags & SSH_FILEXFER_ATTR_ALLOCATION_SIZE != 0 {
            Some(reader.read_u64::<BigEndian>()?)
        } else {
            None
        };

        let owner = if valid_attribute_flags & SSH_FILEXFER_ATTR_OWNERGROUP != 0 {
            let len = reader.read_u32::<BigEndian>()?;
            let mut owner = vec![0; len as usize];
            reader.read_exact(&mut owner)?;
            Some(String::from_utf8(owner).map_err(|e| {
                std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    format!("Invalid owner: {}", e),
                )
            })?)
        } else {
            None
        };

        let group = if valid_attribute_flags & SSH_FILEXFER_ATTR_OWNERGROUP != 0 {
            let len = reader.read_u32::<BigEndian>()?;
            let mut group = vec![0; len as usize];
            reader.read_exact(&mut group)?;
            Some(String::from_utf8(group).map_err(|e| {
                std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    format!("Invalid group: {}", e),
                )
            })?)
        } else {
            None
        };

        let permissions = if valid_attribute_flags & SSH_FILEXFER_ATTR_PERMISSIONS != 0 {
            Some(reader.read_u32::<BigEndian>()?)
        } else {
            None
        };

        let access_time = if valid_attribute_flags & SSH_FILEXFER_ATTR_ACCESSTIME != 0 {
            let atime = reader.read_u64::<BigEndian>()?;
            let atime_nseconds = if valid_attribute_flags & SSH_FILEXFER_ATTR_SUBSECOND_TIMES != 0 {
                Some(reader.read_u32::<BigEndian>()?)
            } else {
                None
            };
            Some((atime, atime_nseconds))
        } else {
            None
        };

        let create_time = if valid_attribute_flags & SSH_FILEXFER_ATTR_CREATETIME != 0 {
            let createtime = reader.read_u64::<BigEndian>()?;
            let createtime_nseconds =
                if valid_attribute_flags & SSH_FILEXFER_ATTR_SUBSECOND_TIMES != 0 {
                    Some(reader.read_u32::<BigEndian>()?)
                } else {
                    None
                };
            Some((createtime, createtime_nseconds))
        } else {
            None
        };

        let modify_time = if valid_attribute_flags & SSH_FILEXFER_ATTR_MODIFYTIME != 0 {
            let mtime = reader.read_u64::<BigEndian>()?;
            let mtime_nseconds = if valid_attribute_flags & SSH_FILEXFER_ATTR_SUBSECOND_TIMES != 0 {
                Some(reader.read_u32::<BigEndian>()?)
            } else {
                None
            };
            Some((mtime, mtime_nseconds))
        } else {
            None
        };

        let ctime = if valid_attribute_flags & SSH_FILEXFER_ATTR_CTIME != 0 {
            let ctime = reader.read_u64::<BigEndian>()?;
            let ctime_nseconds = if valid_attribute_flags & SSH_FILEXFER_ATTR_SUBSECOND_TIMES != 0 {
                Some(reader.read_u32::<BigEndian>()?)
            } else {
                None
            };
            Some((ctime, ctime_nseconds))
        } else {
            None
        };

        let acl = if valid_attribute_flags & SSH_FILEXFER_ATTR_ACL != 0 {
            let len = reader.read_u32::<BigEndian>()?;
            let mut acl = vec![0; len as usize];
            reader.read_exact(&mut acl)?;
            Some(acl)
        } else {
            None
        };

        let attrib_bits = if valid_attribute_flags & SSH_FILEXFER_ATTR_BITS != 0 {
            Some(reader.read_u32::<BigEndian>()?)
        } else {
            None
        };

        let attrib_bits_valid = if valid_attribute_flags & SSH_FILEXFER_ATTR_BITS != 0 {
            Some(reader.read_u32::<BigEndian>()?)
        } else {
            None
        };

        let text_hint = if valid_attribute_flags & SSH_FILEXFER_ATTR_TEXT_HINT != 0 {
            Some(reader.read_u8()?)
        } else {
            None
        };

        let mime_type = if valid_attribute_flags & SSH_FILEXFER_ATTR_MIME_TYPE != 0 {
            let len = reader.read_u32::<BigEndian>()?;
            let mut mime_type = vec![0; len as usize];
            reader.read_exact(&mut mime_type)?;
            Some(String::from_utf8(mime_type).map_err(|e| {
                std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    format!("Invalid mime type: {}", e),
                )
            })?)
        } else {
            None
        };

        let link_count = if valid_attribute_flags & SSH_FILEXFER_ATTR_LINK_COUNT != 0 {
            Some(reader.read_u32::<BigEndian>()?)
        } else {
            None
        };

        let untranslated_name = if valid_attribute_flags & SSH_FILEXFER_ATTR_UNTRANSLATED_NAME != 0
        {
            let len = reader.read_u32::<BigEndian>()?;
            let mut untranslated_name = vec![0; len as usize];
            reader.read_exact(&mut untranslated_name)?;
            Some(untranslated_name)
        } else {
            None
        };

        let extended = if valid_attribute_flags & SSH_FILEXFER_ATTR_EXTENDED != 0 {
            let len = reader.read_u32::<BigEndian>()?;
            let mut extended = Vec::with_capacity(len as usize);
            for _i in 0..len {
                let key_len = reader.read_u32::<BigEndian>()?;
                let mut key = vec![0; key_len as usize];
                reader.read_exact(&mut key)?;
                let val_len = reader.read_u32::<BigEndian>()?;
                let mut val = vec![0; val_len as usize];
                reader.read_exact(&mut val)?;
                extended.push((
                    String::from_utf8(key).unwrap(),
                    String::from_utf8(val).unwrap(),
                ));
            }
            Some(extended)
        } else {
            None
        };

        Ok(Self {
            size,
            uid,
            gid,
            allocation_size,
            owner,
            group,
            permissions,
            access_time,
            create_time,
            modify_time,
            ctime,
            acl,
            attrib_bits,
            attrib_bits_valid,
            text_hint: text_hint.map(|h| h.into()),
            mime_type,
            link_count,
            untranslated_name,
            extended,
        })
    }
}

pub struct SftpClient {
    channel: Mutex<Box<dyn Channel>>,
    last_request_id: std::sync::atomic::AtomicU32,
    version: u32,
    extensions: Vec<(String, String)>,
}

fn parse_ssh_fxp_readdir(respdata: &[u8]) -> Result<Vec<(String, String, Attributes)>> {
    let mut reader = std::io::Cursor::new(respdata);
    let count = reader.read_u32::<BigEndian>()?;
    let mut files = Vec::with_capacity(count as usize);
    for _i in 0..count {
        let filename_len = reader.read_u32::<BigEndian>()?;
        let mut filename = vec![0; filename_len as usize];
        reader.read_exact(&mut filename)?;
        let filename = String::from_utf8(filename).map_err(|e| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("Invalid filename: {}", e),
            )
        })?;
        let longname_len = reader.read_u32::<BigEndian>()?;
        let mut longname = vec![0; longname_len as usize];
        reader.read_exact(&mut longname)?;
        let longname = String::from_utf8(longname).map_err(|e| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("Invalid longname: {}", e),
            )
        })?;
        let attrs = Attributes::deserialize(&mut reader)?;
        files.push((filename, longname, attrs));
    }
    Ok(files)
}

fn parse_ssh_fxp_name(respdata: &[u8]) -> Result<Vec<(String, Attributes)>> {
    let mut reader = std::io::Cursor::new(respdata);
    let count = reader.read_u32::<BigEndian>()?;
    let mut files = Vec::with_capacity(count as usize);
    for _i in 0..count {
        let filename_len = reader.read_u32::<BigEndian>()?;
        let mut filename = vec![0; filename_len as usize];
        reader.read_exact(&mut filename)?;
        let filename = String::from_utf8(filename).map_err(|e| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("Invalid filename: {}", e),
            )
        })?;
        let attrs = Attributes::deserialize(&mut reader)?;
        files.push((filename, attrs));
    }
    Ok(files)
}

fn parse_ssh_fxp_data(respdata: &[u8]) -> Result<Vec<u8>> {
    let mut reader = std::io::Cursor::new(respdata);
    let len = reader.read_u32::<BigEndian>()?;
    let mut data = vec![0; len as usize];
    reader.read_exact(&mut data)?;
    Ok(data)
}

fn parse_ssh_fxp_attrs(respdata: &[u8]) -> Result<Attributes> {
    let mut reader = std::io::Cursor::new(respdata);
    Attributes::deserialize(&mut reader).map_err(Error::Io)
}

fn parse_ssh_fxp_handle(respdata: &[u8]) -> Result<Vec<u8>> {
    let mut reader = std::io::Cursor::new(respdata);
    let handle_len = reader.read_u32::<BigEndian>()?;
    let mut handle = vec![0u8; handle_len as usize];
    reader.read_exact(&mut handle)?;
    Ok(handle)
}

fn parse_ssh_fxp_status(respdata: &[u8]) -> Result<()> {
    let mut reader = std::io::Cursor::new(respdata);
    let status = reader.read_u32::<BigEndian>()?;
    let err_msg_len = reader.read_u32::<BigEndian>()?;
    let mut err_msg = vec![0; err_msg_len as usize];
    reader.read_exact(&mut err_msg)?;
    let err_msg = String::from_utf8(err_msg).map_err(|e| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("Invalid error message: {}", e),
        )
    })?;
    let lang_tag_len = reader.read_u32::<BigEndian>()?;
    let mut lang_tag = vec![0; lang_tag_len as usize];
    reader.read_exact(&mut lang_tag)?;
    let lang_tag = String::from_utf8(lang_tag).map_err(|e| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("Invalid lang tag: {}", e),
        )
    })?;
    match status {
        SSH_FX_OK => Ok(()),
        SSH_FX_EOF => Err(Error::Eof(err_msg, lang_tag)),
        SSH_FX_NO_SUCH_FILE => Err(Error::NoSuchFile(err_msg, lang_tag)),
        SSH_FX_PERMISSION_DENIED => Err(Error::PermissionDenied(err_msg, lang_tag)),
        SSH_FX_FAILURE => Err(Error::Failure(err_msg, lang_tag)),
        SSH_FX_BAD_MESSAGE => Err(Error::BadMessage(err_msg, lang_tag)),
        SSH_FX_NO_CONNECTION => Err(Error::NoConnection(err_msg, lang_tag)),
        SSH_FX_CONNECTION_LOST => Err(Error::ConnectionLost(err_msg, lang_tag)),
        SSH_FX_OP_UNSUPPORTED => Err(Error::OpUnsupported(err_msg, lang_tag)),
        SSH_FX_INVALID_HANDLE => Err(Error::InvalidHandle(err_msg, lang_tag)),
        SSH_FX_NO_SUCH_PATH => Err(Error::NoSuchPath(err_msg, lang_tag)),
        SSH_FX_FILE_ALREADY_EXISTS => Err(Error::FileAlreadyExists(err_msg, lang_tag)),
        SSH_FX_WRITE_PROTECT => Err(Error::WriteProtect(err_msg, lang_tag)),
        SSH_FX_NO_MEDIA => Err(Error::NoMedia(err_msg, lang_tag)),
        SSH_FX_NO_SPACE_ON_FILESYSTEM => Err(Error::NoSpaceOnFilesystem(err_msg, lang_tag)),
        SSH_FX_QUOTA_EXCEEDED => Err(Error::QuotaExceeded(err_msg, lang_tag)),
        SSH_FX_UNKNOWN_PRINCIPAL => Err(Error::UnknownPrincipal(err_msg, lang_tag)),
        SSH_FX_LOCK_CONFLICT => Err(Error::LockConflict(err_msg, lang_tag)),
        SSH_FX_DIR_NOT_EMPTY => Err(Error::DirNotEmpty(err_msg, lang_tag)),
        SSH_FX_NOT_A_DIRECTORY => Err(Error::NotADirectory(err_msg, lang_tag)),
        SSH_FX_INVALID_FILENAME => Err(Error::InvalidFilename(err_msg, lang_tag)),
        SSH_FX_LINK_LOOP => Err(Error::LinkLoop(err_msg, lang_tag)),
        SSH_FX_CANNOT_DELETE => Err(Error::CannotDelete(err_msg, lang_tag)),
        SSH_FX_INVALID_PARAMETER => Err(Error::InvalidParameter(err_msg, lang_tag)),
        SSH_FX_FILE_IS_A_DIRECTORY => Err(Error::FileIsADirectory(err_msg, lang_tag)),
        SSH_FX_BYTE_RANGE_LOCK_CONFLICT => Err(Error::ByteRangeLockConflict(err_msg, lang_tag)),
        SSH_FX_BYTE_RANGE_LOCK_REFUSED => Err(Error::ByteRangeLockRefused(err_msg, lang_tag)),
        SSH_FX_DELETE_PENDING => Err(Error::DeletePending(err_msg, lang_tag)),
        SSH_FX_FILE_CORRUPT => Err(Error::FileCorrupt(err_msg, lang_tag)),
        SSH_FX_OWNER_INVALID => Err(Error::OwnerInvalid(err_msg, lang_tag)),
        SSH_FX_GROUP_INVALID => Err(Error::GroupInvalid(err_msg, lang_tag)),
        SSH_FX_NO_MATCHING_BYTE_RANGE_LOCK => {
            Err(Error::NoMatchingByteRangeLock(err_msg, lang_tag))
        }
        _ => Err(Error::Other(status, err_msg, lang_tag)),
    }
}

type RequestId = u32;

impl Channel for std::fs::File {}

fn read_raw_packet(channel: &mut dyn Channel) -> std::io::Result<(u8, Vec<u8>)> {
    let mut buf = [0u8; 4];
    channel.read_exact(&mut buf)?;
    let len = i32::from_be_bytes(buf);

    let mut buf = vec![0u8; len as usize];
    channel.read_exact(&mut buf)?;

    let kind = buf[0];

    Ok((kind, buf[1..].to_vec()))
}

fn write_raw_packet(channel: &mut dyn Channel, kind: u8, buf: &[u8]) -> std::io::Result<()> {
    channel.write_u32::<BigEndian>(buf.len() as u32 + 1)?;
    channel.write_u8(kind)?;
    channel.write_all(buf)?;
    Ok(())
}

fn initialize(channel: &mut dyn Channel) -> std::io::Result<(u32, Vec<(String, String)>)> {
    let mut buf = Vec::new();
    buf.write_u32::<BigEndian>(3)?;
    write_raw_packet(channel, SSH_FXP_INIT, buf.as_slice())?;
    channel.flush()?;
    let (kind, buf) = read_raw_packet(channel)?;
    if kind != SSH_FXP_VERSION {
        return Err(std::io::Error::new(
            std::io::ErrorKind::Other,
            format!("Unexpected response to init: {}", kind),
        ));
    }
    let mut reader = std::io::Cursor::new(buf);
    let version = reader.read_u32::<BigEndian>()?;
    if version != 3 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::Other,
            format!("SFTP version mismatch (expected 3, got: {})", version),
        ));
    }
    let mut extensions = Vec::new();
    while reader.position() < reader.get_ref().len() as u64 {
        let key_len = reader.read_u32::<BigEndian>()?;
        let mut key = vec![0u8; key_len as usize];
        reader.read_exact(&mut key)?;
        let value_len = reader.read_u32::<BigEndian>()?;
        let mut value = vec![0u8; value_len as usize];
        reader.read_exact(&mut value)?;
        extensions.push((
            String::from_utf8(key).unwrap(),
            String::from_utf8(value).unwrap(),
        ));
    }
    Ok((version, extensions))
}

impl SftpClient {
    pub fn new(mut channel: Box<dyn Channel>) -> std::io::Result<Self> {
        let (version, extensions) = initialize(&mut *channel)?;
        Ok(Self {
            channel: Mutex::new(channel),
            version,
            extensions,
            last_request_id: std::sync::atomic::AtomicU32::new(0),
        })
    }

    pub fn extensions(&self) -> &[(String, String)] {
        &self.extensions
    }

    pub fn version(&self) -> u32 {
        self.version
    }

    pub fn from_fd(fd: i32) -> std::io::Result<Self> {
        let file = unsafe { std::fs::File::from_raw_fd(fd) };
        Self::new(Box::new(file))
    }

    /// Create a new directory
    pub fn mkdir(&self, path: &str, attr: &Attributes) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());
        buf.extend_from_slice(&attr.serialize()?);

        let (respcmd, respdata) = self.process(SSH_FXP_MKDIR, buf.as_slice())?;

        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    /// Remove a directory
    pub fn rmdir(&self, path: &str) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());

        let (respcmd, respdata) = self.process(SSH_FXP_RMDIR, buf.as_slice())?;

        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn readlink(&self, path: &str) -> Result<String> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());

        let (respcmd, respdata) = self.process(SSH_FXP_READLINK, buf.as_slice())?;

        match respcmd {
            SSH_FXP_NAME => {
                let names = parse_ssh_fxp_name(respdata.as_slice())?;
                Ok(names[0].0.clone())
            }
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice())
                .map(|_| panic!("Unexpected status response")),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn symlink(&self, path: &str, target: &str) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());
        buf.write_u32::<BigEndian>(target.len() as u32)?;
        buf.extend_from_slice(target.as_bytes());

        let (respcmd, respdata) = self.process(SSH_FXP_SYMLINK, buf.as_slice())?;

        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn hardlink(&self, path: &str, target: &str) -> Result<()> {
        self.link(path, target, false)
    }

    pub fn link(&self, path: &str, target: &str, symlink: bool) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());
        buf.write_u32::<BigEndian>(target.len() as u32)?;
        buf.extend_from_slice(target.as_bytes());
        buf.write_u8(if symlink { 1 } else { 0 })?;

        let (respcmd, respdata) = self.process(SSH_FXP_LINK, buf.as_slice())?;

        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn open(&self, path: &str, flags: u32, attr: &Attributes) -> Result<File> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());
        buf.write_u32::<BigEndian>(flags)?;
        buf.extend_from_slice(&attr.serialize()?);
        let (respcmd, respdata) = self.process(SSH_FXP_OPEN, buf.as_slice())?;
        match respcmd {
            SSH_FXP_HANDLE => Ok(File(parse_ssh_fxp_handle(respdata.as_slice())?)),
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice())
                .map(|_| panic!("Unexpected status response")),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    fn process(&self, cmd: u8, body: &[u8]) -> std::io::Result<(u8, Vec<u8>)> {
        let request_id = self
            .last_request_id
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);

        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(request_id).unwrap();
        buf.extend_from_slice(body);

        {
            write_raw_packet(&mut **self.channel.lock().unwrap(), cmd, buf.as_slice())?;
        }

        {
            let (cmd, buf) = read_raw_packet(&mut **self.channel.lock().unwrap())?;

            assert!(buf[..4] == request_id.to_be_bytes());

            Ok((cmd, buf[4..].to_vec()))
        }
    }

    pub fn realpath(
        &self,
        path: &str,
        control_byte: Option<u8>,
        compose_path: Option<&str>,
    ) -> Result<String> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());
        if let Some(control_byte) = control_byte {
            buf.write_u8(control_byte)?;
        }
        if let Some(compose_path) = compose_path {
            buf.write_u32::<BigEndian>(compose_path.len() as u32)?;
            buf.extend_from_slice(compose_path.as_bytes());
        }

        let (respcmd, respdata) = self.process(SSH_FXP_REALPATH, buf.as_slice())?;

        match respcmd {
            SSH_FXP_NAME => {
                let names = parse_ssh_fxp_name(respdata.as_slice())?;
                Ok(names[0].0.clone())
            }
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice())
                .map(|_| panic!("Unexpected status response")),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn setstat(&self, path: &str, attr: &Attributes) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());
        buf.extend_from_slice(&attr.serialize()?);

        let (respcmd, respdata) = self.process(SSH_FXP_SETSTAT, buf.as_slice())?;

        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn stat(&self, path: &str, flags: Option<u32>) -> Result<Attributes> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());
        buf.write_u32::<BigEndian>(flags.unwrap_or(0))?;

        let (respcmd, respdata) = self.process(SSH_FXP_STAT, buf.as_slice())?;

        match respcmd {
            SSH_FXP_ATTRS => parse_ssh_fxp_attrs(respdata.as_slice()),
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice())
                .map(|_| panic!("Unexpected status response")),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn remove(&self, path: &str) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());

        let (respcmd, respdata) = self.process(SSH_FXP_REMOVE, buf.as_slice())?;

        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn rename(&self, oldpath: &str, newpath: &str, flags: Option<u32>) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(oldpath.len() as u32)?;
        buf.extend_from_slice(oldpath.as_bytes());
        buf.write_u32::<BigEndian>(newpath.len() as u32)?;
        buf.extend_from_slice(newpath.as_bytes());
        buf.write_u32::<BigEndian>(
            flags.unwrap_or(
                SSH_FXF_RENAME_ATOMIC | SSH_FXF_RENAME_NATIVE | SSH_FXF_RENAME_OVERWRITE,
            ),
        )?;

        let (respcmd, respdata) = self.process(SSH_FXP_RENAME, buf.as_slice())?;

        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn lstat(&self, path: &str, flags: Option<u32>) -> Result<Attributes> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());
        buf.write_u32::<BigEndian>(flags.unwrap_or(0))?;

        let (respcmd, respdata) = self.process(SSH_FXP_LSTAT, buf.as_slice())?;

        match respcmd {
            SSH_FXP_ATTRS => parse_ssh_fxp_attrs(respdata.as_slice()),
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice())
                .map(|_| panic!("Unexpected status response")),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn opendir(&self, path: &str) -> Result<Directory> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(path.len() as u32)?;
        buf.extend_from_slice(path.as_bytes());

        let (respcmd, respdata) = self.process(SSH_FXP_OPENDIR, buf.as_slice())?;

        match respcmd {
            SSH_FXP_HANDLE => Ok(Directory(parse_ssh_fxp_handle(respdata.as_slice())?)),
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice())
                .map(|_| panic!("Unexpected status response")),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn extended(&self, request: &str, data: &[u8]) -> Result<Option<Vec<u8>>> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(request.len() as u32)?;
        buf.extend_from_slice(request.as_bytes());
        buf.extend_from_slice(data);

        let (respcmd, respdata) = self.process(SSH_FXP_EXTENDED, buf.as_slice())?;

        match respcmd {
            SSH_FXP_EXTENDED_REPLY => Ok(Some(respdata)),
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()).map(|_| None),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn block(&self, file: &File, offset: u64, length: u64, lockmask: u32) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(file.0.len() as u32)?;
        buf.extend_from_slice(&file.0);
        buf.write_u64::<BigEndian>(offset)?;
        buf.write_u64::<BigEndian>(length)?;
        buf.write_u32::<BigEndian>(lockmask)?;

        let (respcmd, respdata) = self.process(SSH_FXP_BLOCK, buf.as_slice())?;
        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn unblock(&self, file: &File, offset: u64, length: u64) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(file.0.len() as u32)?;
        buf.extend_from_slice(&file.0);
        buf.write_u64::<BigEndian>(offset)?;
        buf.write_u64::<BigEndian>(length)?;

        let (respcmd, respdata) = self.process(SSH_FXP_UNBLOCK, buf.as_slice())?;
        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn fsetstat(&self, file: &File, attr: &Attributes) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(file.0.len() as u32)?;
        buf.extend_from_slice(&file.0);
        buf.extend_from_slice(&attr.serialize()?);

        let (respcmd, respdata) = self.process(SSH_FXP_FSETSTAT, buf.as_slice())?;
        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn fstat(&self, file: &File, flags: Option<u32>) -> Result<Attributes> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(file.0.len() as u32)?;
        buf.extend_from_slice(&file.0);
        buf.write_u32::<BigEndian>(flags.unwrap_or(0))?;

        let (respcmd, respdata) = self.process(SSH_FXP_FSTAT, buf.as_slice())?;
        match respcmd {
            SSH_FXP_ATTRS => parse_ssh_fxp_attrs(respdata.as_slice()),
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice())
                .map(|_| panic!("Unexpected status response")),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn pwrite(&self, file: &File, offset: u64, data: &[u8]) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(file.0.len() as u32)?;
        buf.extend_from_slice(&file.0);
        buf.write_u64::<BigEndian>(offset).unwrap();
        buf.write_u32::<BigEndian>(data.len() as u32).unwrap();
        buf.extend_from_slice(data);

        let (respcmd, respdata) = self.process(SSH_FXP_WRITE, buf.as_slice())?;

        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn pread(&self, file: &File, offset: u64, length: u32) -> Result<Vec<u8>> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(file.0.len() as u32)?;
        buf.extend_from_slice(&file.0);
        buf.write_u64::<BigEndian>(offset).unwrap();
        buf.write_u32::<BigEndian>(length).unwrap();

        let (respcmd, respdata) = self.process(SSH_FXP_READ, buf.as_slice())?;

        match respcmd {
            SSH_FXP_DATA => parse_ssh_fxp_data(respdata.as_slice()),
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice())
                .map(|_| panic!("Unexpected status response")),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn fclose(&self, file: &File) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(file.0.len() as u32)?;
        buf.extend_from_slice(&file.0);

        let (respcmd, respdata) = self.process(SSH_FXP_CLOSE, buf.as_slice())?;
        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn flineseek(&self, file: &File, lineno: u64) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(file.0.len() as u32)?;
        buf.extend_from_slice(&file.0);
        buf.write_u64::<BigEndian>(lineno)?;

        self.extended("text-seek", buf.as_slice())?;
        Ok(())
    }

    pub fn closedir(&self, dir: &Directory) -> Result<()> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(dir.0.len() as u32)?;
        buf.extend_from_slice(&dir.0);

        let (respcmd, respdata) = self.process(SSH_FXP_CLOSE, buf.as_slice())?;
        match respcmd {
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice()),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }

    pub fn readdir(&self, dir: &Directory) -> Result<Vec<(String, String, Attributes)>> {
        let mut buf = Vec::new();
        buf.write_u32::<BigEndian>(dir.0.len() as u32)?;
        buf.extend_from_slice(&dir.0);

        let (respcmd, respdata) = self.process(SSH_FXP_READDIR, buf.as_slice())?;
        match respcmd {
            SSH_FXP_NAME => parse_ssh_fxp_readdir(respdata.as_slice()),
            SSH_FXP_STATUS => parse_ssh_fxp_status(respdata.as_slice())
                .map(|_| panic!("Unexpected status response")),
            _ => panic!("Unexpected response: {}", respcmd),
        }
    }
}

#[derive(Debug, Clone)]
pub struct File(Vec<u8>);

#[derive(Debug, Clone)]
pub struct Directory(Vec<u8>);
