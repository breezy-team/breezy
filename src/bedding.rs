use log::debug;
use std::env;

use std::fs::create_dir;

use std::io::BufRead;

use std::path::{Path, PathBuf};

// TODO(jelmer): Rely on the directories crate instead

/// Make sure a configuration directory exists.
///
/// This makes sure that the directory exists.
/// On windows, since configuration directories are 2 levels deep,
/// it makes sure both the directory and the parent directory exists.
pub fn ensure_config_dir_exists(path: Option<&Path>) -> std::io::Result<()> {
    let path = match path {
        Some(p) => p.to_owned(),
        None => config_dir()?,
    };

    if !path.is_dir() {
        let parent_dir = path.parent().ok_or(std::io::Error::new(
            std::io::ErrorKind::Other,
            "no parent directory",
        ))?;
        if !parent_dir.is_dir() {
            debug!("creating config parent directory: {:?}", parent_dir);
            create_dir(parent_dir)?;
            breezy_osutils::file::copy_ownership_from_path(parent_dir, None)?;
        }
        debug!("creating config directory: {:?}", path);
        create_dir(&path)?;
        breezy_osutils::file::copy_ownership_from_path(&path, None)?;
    }
    Ok(())
}

/// Returns the per-user configuration directory for Bazaar.
pub fn bazaar_config_dir() -> std::io::Result<PathBuf> {
    // Return per-user configuration directory as a String

    // By default this is %APPDATA%/bazaar/2.0 on Windows, ~/.bazaar on Mac OS X
    // and Linux.  On Mac OS X and Linux, if there is a $XDG_CONFIG_HOME/bazaar
    // directory, that will be used instead

    // TODO: Global option --config-dir to override this.

    let base = env::var("BZR_HOME").map(PathBuf::from).ok();

    #[cfg(target_os = "windows")]
    {
        match base {
            None => {
                let appdata = win32utils::get_appdata_location().ok();
                let home = win32utils::get_home_location().ok();
                let mut base_path = match appdata {
                    Some(path) => path,
                    None => match home {
                        Some(path) => path,
                        None => "".to_string(),
                    },
                };
                base_path.push_str(r"\bazaar\2.0");
                return base_path;
            }
            Some(base_path) => {
                let mut path = base_path;
                path.push_str(r"\bazaar\2.0");
                return path;
            }
        }
    }

    match base {
        None => {
            let xdg_dir = env::var("XDG_CONFIG_HOME").map_or_else(
                |_| {
                    let hd = breezy_osutils::get_home_dir().expect("no home directory");
                    hd.join(".config")
                },
                PathBuf::from,
            );
            let bazaar_path = xdg_dir.join("bazaar");
            if bazaar_path.is_dir() {
                debug!(
                    "Using configuration in XDG directory {}.",
                    &bazaar_path.display()
                );
                return Ok(bazaar_path);
            }
            let home_dir = breezy_osutils::get_home_dir().expect("no home directory");
            Ok(home_dir.join(".bazaar"))
        }
        Some(base_path) => Ok(base_path.join(".bazaar")),
    }
}

/// The kind of configuration directory.
pub enum ConfigDirKind {
    /// The Breezy configuration directory.
    Breezy,
    /// The Bazaar configuration directory.
    Bazaar,
}

impl ToString for ConfigDirKind {
    fn to_string(&self) -> String {
        match self {
            ConfigDirKind::Breezy => "breezy",
            ConfigDirKind::Bazaar => "bazaar",
        }
        .to_string()
    }
}

/// Return per-user configuration directory as unicode string
///
/// By default this is %APPDATA%/breezy on Windows, $XDG_CONFIG_HOME/breezy on
/// Mac OS X and Linux. If the breezy config directory doesn't exist but
/// the bazaar one (see bazaar_config_dir()) does, use that instead.
pub fn _config_dir() -> std::io::Result<(PathBuf, ConfigDirKind)> {
    // TODO: Global option --config-dir to override this.
    let base = env::var("BRZ_HOME").map(PathBuf::from).ok();
    #[cfg(windows)]
    {
        let base = base.or_else(win32utils::get_appdata_location);
        if base.is_none() {
            return Err("Unable to determine AppData location".into());
        }
    }
    let base = base.unwrap_or_else(|| {
        env::var("XDG_CONFIG_HOME").ok().map_or_else(
            || {
                breezy_osutils::get_home_dir()
                    .expect("no home directory")
                    .join(".config")
            },
            PathBuf::from,
        )
    });
    let breezy_dir = base.join("breezy");
    if breezy_dir.is_dir() {
        Ok((breezy_dir, ConfigDirKind::Breezy))
    } else {
        let bazaar_dir = bazaar_config_dir()?;
        if bazaar_dir.is_dir() {
            debug!(
                "Using Bazaar configuration directory ({})",
                bazaar_dir.display()
            );
            Ok((bazaar_dir, ConfigDirKind::Bazaar))
        } else {
            Ok((breezy_dir, ConfigDirKind::Breezy))
        }
    }
}

/// Return per-user configuration directory as unicode string
///
/// By default this is %APPDATA%/breezy on Windows, $XDG_CONFIG_HOME/breezy on
/// Mac OS X and Linux. If the breezy config directory doesn't exist but
/// the bazaar one (see bazaar_config_dir()) does, use that instead.
pub fn config_dir() -> std::io::Result<PathBuf> {
    Ok(_config_dir()?.0)
}

/// Returns the path to the configuration file (breezy.conf or bazaar.conf).
pub fn config_path() -> std::io::Result<PathBuf> {
    let (path, kind) = _config_dir()?;
    Ok(match kind {
        ConfigDirKind::Breezy => path.join("breezy.conf"),
        ConfigDirKind::Bazaar => path.join("bazaar.conf"),
    })
}

/// Return per-user configuration ini file filename.
pub fn locations_config_path() -> std::io::Result<PathBuf> {
    Ok(config_dir()?.join("locations.conf"))
}

/// Return per-user authentication ini file filename.
pub fn authentication_config_path() -> std::io::Result<PathBuf> {
    Ok(config_dir()?.join("authentication.conf"))
}

/// Return per-user authentication ini file filename.
pub fn user_ignore_config_path() -> std::io::Result<PathBuf> {
    Ok(config_dir()?.join("ignore"))
}

/// Returns the directory name to store crash files.
pub fn crash_dir() -> PathBuf {
    // Return the directory name to store crash files.
    // This doesn't implicitly create it.
    //
    // On Windows it's in the config directory; elsewhere it's /var/crash
    // which may be monitored by apport. It can be overridden by
    // $APPORT_CRASH_DIR.

    #[cfg(windows)]
    {
        config_dir().join("Crash")
    }

    #[cfg(not(windows))]
    {
        // XXX: hardcoded in apport_python_hook.py; therefore here too -- mbp
        // 2010-01-31
        match env::var("APPORT_CRASH_DIR") {
            Ok(val) => PathBuf::from(val),
            Err(_) => Path::new("/var/crash").to_path_buf(),
        }
    }
}

/// Returns the per-user cache directory.
pub fn cache_dir() -> std::io::Result<PathBuf> {
    let mut base: Option<PathBuf>;

    #[cfg(windows)]
    {
        let mut base: Option<PathBuf> = env::var("BRZ_HOME").ok().map(PathBuf::from);
        if base.is_none() {
            base = win32utils::get_local_appdata_location();
        }
        if base.is_none() {
            base = win32utils::get_home_location();
        }
    }

    #[cfg(not(windows))]
    {
        base = if let Ok(xdg_cache_home) = env::var("XDG_CACHE_HOME") {
            Some(PathBuf::from(xdg_cache_home))
        } else {
            None
        };
        if base.is_none() {
            base = Some(
                breezy_osutils::get_home_dir()
                    .expect("no home directory")
                    .join(".cache"),
            );
        }
    }

    let cache_dir = base.unwrap().join("breezy");

    // GZ 2019-06-15: Move responsibility for ensuring dir exists elsewhere?
    std::fs::create_dir_all(&cache_dir)
        .map_err(|e| std::io::Error::new(e.kind(), format!("{}: {}", e, cache_dir.display())))?;

    Ok(cache_dir)
}

/// Returns the default email address, if available.
pub fn default_email() -> Option<String> {
    let brz_email = env::var("BRZ_EMAIL");
    if let Ok(email) = brz_email {
        return Some(email);
    }

    let email = env::var("EMAIL");
    if let Ok(email) = email {
        return Some(email);
    }

    match env::var("BRZ_DISABLE_AUTO_USER_ID") {
        Ok(e) if e == "1" => return None,
        _ => {}
    }

    match auto_user_id() {
        Ok((Some(name), Some(email))) => Some(format!("{} <{}>", name, email)),
        Ok((None, Some(email))) => Some(email),
        _ => None,
    }
}

/// Calculate automatic user identification.
///
/// Returns a tuple of `(realname, email)`, either of which may be `None` if they can't be
/// determined.
///
/// Only used when none is set in the environment or the id file.
///
/// This only returns an email address if we can be fairly sure the
/// address is reasonable, ie if /etc/mailname is set on unix.
///
/// This doesn't use the FQDN as the default domain because that may be
/// slow, and it doesn't use the hostname alone because that's not normally
/// a reasonable address.
#[cfg(not(windows))]
pub fn auto_user_id() -> std::io::Result<(Option<String>, Option<String>)> {
    let default_mail_domain = match get_default_mail_domain(None) {
        Some(domain) => domain,
        None => return Ok((None, None)),
    };
    let uid = nix::unistd::getuid();

    let w = match nix::unistd::User::from_uid(uid) {
        Ok(Some(w)) => w,
        Ok(None) => {
            debug!("no passwd entry for uid {}?", uid);
            return Ok((None, None));
        }
        Err(_) => {
            return Err(std::io::Error::new(
                std::io::ErrorKind::Other,
                format!("cannot get passwd entry for uid {}", uid),
            ))
        }
    };

    let username = w.name;
    let realname = match w.gecos.to_str() {
        Ok(gecos_str) => {
            let comma = gecos_str.find(',');
            if let Some(comma) = comma {
                Some(gecos_str[..comma].trim().to_string())
            } else {
                Some(gecos_str.trim().to_string())
            }
        }
        Err(_) => {
            debug!("cannot decode passwd entry {:?}", w.gecos.to_str());
            None
        }
    };

    let email = Some(format!("{}@{}", username, default_mail_domain));

    Ok((realname, email))
}

/// If possible, return the assumed default email domain.
///
/// Returns `Some(domain)` if the default mail domain can be read from the
/// specified `mailname_file`, otherwise `None`.
///
/// Args:
///   mailname_file: path to the mailname file to read, or `None` to use the default path
/// Returns: string mail domain, or None.
#[cfg(not(windows))]
pub fn get_default_mail_domain(mailname_file: Option<&Path>) -> Option<String> {
    let mailname_file = mailname_file.unwrap_or(Path::new("/etc/mailname"));

    if let Ok(file) = std::fs::File::open(mailname_file) {
        let reader = std::io::BufReader::new(file);
        if let Some(Ok(domain)) = reader.lines().next() {
            Some(domain.trim().to_string())
        } else {
            None
        }
    } else {
        None
    }
}
