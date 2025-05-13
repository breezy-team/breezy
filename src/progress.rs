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

/// Model component of a progress indicator.
///
/// Most code that needs to indicate progress should update one of these,
/// and it will in turn update the display, if one is present.
///
/// Code updating the task may also set fields as hints about how to display
/// it: show_pct, show_spinner, show_eta, show_count, show_bar.  UIs
/// will not necessarily respect all these fields.
pub trait ProgressTask {
    /// Report updated task message and if relevent progress counters.
    fn update(&self, msg: &str, current_cnt: Option<u64>, total_cnt: Option<u64>);

    /// Report that the task has made progress
    fn tick(&self);

    /// Report that the task is finished.
    fn finished(&self);

    /// Create a sub-task of this task
    fn make_sub_task(&self) -> Box<dyn ProgressTask>;

    /// Clear the progress display.
    fn clear(&self);
}

/// Progress-bar standin that does nothing.
///
/// This was previously often constructed by application code if no progress
/// bar was explicitly passed in.  That's no longer recommended: instead, just
/// create a progress task from the ui_factory.  This class can be used in
/// test code that needs to fake a progress task for some reason.
pub struct DummyProgress;

impl ProgressTask for DummyProgress {
    fn update(&self, _msg: &str, _current_cnt: Option<u64>, _total_cnt: Option<u64>) {}

    fn tick(&self) {}

    fn finished(&self) {}

    fn make_sub_task(&self) -> Box<dyn ProgressTask> {
        Box::new(DummyProgress)
    }

    fn clear(&self) {}
}
