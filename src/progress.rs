use std::io::Write;

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
