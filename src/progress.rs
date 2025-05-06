use std::io::Write;

/// Formats a time delta in seconds into a human-readable string.
///
/// # Arguments
///
/// * `delt` - An optional time delta in seconds. If None, returns "-:--:--".
///
/// # Returns
///
/// A string in the format "HH:MM:SS" representing the time delta.
pub fn str_tdelta(delt: Option<f64>) -> String {
    match delt {
        None => "-:--:--".to_string(),
        Some(delt) => {
            let delt = delt.round() as i32;
            format!("{}:{:02}:{:02}", delt / 3600, (delt / 60) % 60, delt % 60)
        }
    }
}

#[cfg(unix)]
use std::os::unix::io::AsRawFd;

#[cfg(unix)]
/// Checks if a file descriptor supports progress display.
///
/// This function determines if progress information can be displayed on the given
/// file descriptor by checking if it's a terminal and not a "dumb" terminal.
///
/// # Arguments
///
/// * `f` - A file descriptor that implements Write and AsRawFd.
///
/// # Returns
///
/// True if the file descriptor is a terminal and supports progress display,
/// false otherwise.
pub fn supports_progress<F: Write + AsRawFd>(f: &F) -> bool {
    match nix::unistd::isatty(f.as_raw_fd()) {
        Ok(true) => {
            if let Ok(term) = std::env::var("TERM") {
                term != "dumb"
            } else {
                true
            }
        }
        Ok(false) => false,
        Err(_) => false,
    }
}
