/// The information recorded about a held lock.
///
/// This information is recorded into the lock when it's taken, and it can be
/// read back by any process with access to the lockdir.  It can be used, for
/// example, to tell the user who holds the lock, or to try to detect whether
/// the lock holder is still alive.
use std::collections::HashMap;

use log::debug;
use serde::{Deserialize, Serialize};
use std::time::SystemTime;

/// Information about a process holding a lock.
///
/// This struct contains metadata about the process that has acquired a lock,
/// including identification information and timing data.
#[derive(PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct LockHeldInfo {
    /// The process ID of the lock holder.
    pub pid: Option<u32>,
    /// The username of the lock holder.
    pub user: Option<String>,
    /// A unique identifier for this lock instance.
    pub nonce: Option<String>,
    /// The hostname of the machine holding the lock.
    pub hostname: Option<String>,
    /// The time when the lock was acquired.
    pub start_time: Option<SystemTime>,

    /// Additional information about the lock holder.
    #[serde(flatten)]
    pub extra_holder_info: HashMap<String, String>,
}

/// Errors that can occur when working with locks.
pub enum Error {
    /// The lock file is corrupted or cannot be parsed.
    LockCorrupt(String),
}

type Nonce = [u8];

impl LockHeldInfo {
    /// Returns the nonce associated with this lock, if any.
    ///
    /// The nonce is a unique identifier for this lock instance.
    pub fn nonce(&self) -> Option<&Nonce> {
        self.nonce.as_ref().map(|p| p.as_bytes())
    }

    /// Turn the holder info into a dict of human-readable attributes.
    ///
    /// For example, the start time is presented relative to the current time,
    /// rather than as seconds since the epoch.
    ///
    /// Returns a list of [user, hostname, pid, time_ago] all as readable
    /// strings.
    pub fn to_readable_dict(&self) -> HashMap<String, String> {
        let mut ret: HashMap<String, String> = HashMap::new();
        let time_ago = if let Some(start_time) = self.start_time {
            let delta = std::time::SystemTime::now()
                .duration_since(start_time)
                .unwrap();
            breezy_osutils::time::format_delta(delta.as_secs() as i64)
        } else {
            "(unknown)".to_string()
        };
        ret.insert("time_ago".to_string(), time_ago);
        ret.insert(
            "user".to_string(),
            self.user.as_deref().unwrap_or("<unknown>").to_string(),
        );
        ret.insert(
            "hostname".to_string(),
            self.hostname.as_deref().unwrap_or("<unknown>").to_string(),
        );
        ret.insert(
            "pid".to_string(),
            self.pid
                .as_ref()
                .map(|x| x.to_string())
                .unwrap_or("<unknown>".to_string()),
        );
        ret
    }

    /// Return a new LockHeldInfo for a lock taken by this process.
    ///
    /// # Arguments
    ///
    /// * `extra_holder_info` - Additional information to store with the lock.
    pub fn for_this_process(extra_holder_info: HashMap<String, String>) -> Self {
        let start_time = std::time::SystemTime::now();
        Self {
            hostname: Some(breezy_osutils::get_host_name().unwrap()),
            pid: Some(std::process::id()),
            nonce: Some(breezy_osutils::rand_chars(20)),
            start_time: Some(start_time),
            user: Some(get_username_for_lock_info()),
            extra_holder_info,
        }
    }

    /// Serializes the lock information to bytes.
    ///
    /// The bytes are in YAML format and can be written to a lock file.
    pub fn to_bytes(&self) -> Vec<u8> {
        serde_yaml::to_string(&self).unwrap().into_bytes()
    }

    /// Construct from the contents of the held file.
    ///
    /// # Arguments
    ///
    /// * `info_file_bytes` - The raw bytes from the lock file.
    ///
    /// # Errors
    ///
    /// Returns an `Error` if the lock file is corrupted or cannot be parsed.
    pub fn from_info_file_bytes(info_file_bytes: &[u8]) -> Result<Self, Error> {
        let ret: serde_yaml::Value = match serde_yaml::from_slice(info_file_bytes) {
            Ok(v) => v,
            Err(e) => {
                debug!("Corrupt lock info file: {:?}", info_file_bytes);
                return Err(Error::LockCorrupt(format!(
                    "could not parse lock info file: {:?}",
                    e
                )));
            }
        };
        if ret.is_null() {
            // see bug 185013; we fairly often end up with the info file being
            // empty after an interruption; we could log a message here but
            // there may not be much we can say
            Ok(Self::default())
        } else {
            serde_yaml::from_value(ret)
                .map_err(|e| Error::LockCorrupt(format!("could not parse lock info file: {:?}", e)))
        }
    }

    /// True if this process seems to be the current lock holder.
    pub fn is_locked_by_this_process(&self) -> bool {
        self.hostname == Some(breezy_osutils::get_host_name().unwrap())
            && self.pid == Some(std::process::id())
            && self.user == Some(get_username_for_lock_info())
    }

    /// True if the lock holder process is known to be dead.
    ///
    /// False if it's either known to be still alive, or if we just can't tell.
    ///
    /// We can be fairly sure the lock holder is dead if it declared the same
    /// hostname and there is no process with the given pid alive.  If people
    /// have multiple machines with the same hostname this may cause trouble.
    ///
    /// This doesn't check whether the lock holder is in fact the same process
    /// calling this method.  (In that case it will return true.)
    pub fn is_lock_holder_known_dead(&self) -> bool {
        if self.hostname != Some(breezy_osutils::get_host_name().unwrap()) {
            return false;
        }
        if self.hostname == Some("localhost".to_string()) {
            // Too ambiguous.
            return false;
        }
        if self.user != Some(get_username_for_lock_info()) {
            // Could well be another local process by a different user, but
            // just to be safe we won't conclude about this either.
            return false;
        }
        if self.pid.is_none() {
            debug!("no pid recorded in {}", self);
            return false;
        }
        let pid = nix::unistd::Pid::from_raw(self.pid.unwrap() as i32);
        breezy_osutils::is_local_pid_dead(pid)
    }
}

impl std::fmt::Display for LockHeldInfo {
    /// Return a user-oriented description of this object.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> Result<(), std::fmt::Error> {
        let d = self.to_readable_dict();

        write!(
            f,
            "held by {} on {} (process #{}), acquired {}",
            d.get("user").unwrap(),
            d.get("hostname").unwrap(),
            d.get("pid").unwrap(),
            d.get("time_ago").unwrap()
        )?;

        Ok(())
    }
}

fn get_username_for_lock_info() -> String {
    breezy_osutils::get_user_name()
}
