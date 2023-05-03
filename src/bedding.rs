use log::debug;
use std::env;
use std::fs::create_dir;
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

pub enum ConfigDirKind {
    Breezy,
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
