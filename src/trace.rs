use log::info;
use std::fs::{File, OpenOptions};
use std::io::Read;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::RwLock;

use std::fs::{metadata, rename};

pub fn initialize_brz_log_filename() -> Result<PathBuf, std::io::Error> {
    let brz_log = std::env::var("BRZ_LOG").ok();
    if let Some(brz_log) = brz_log {
        Ok(PathBuf::from(brz_log))
    } else {
        let cache_dir = crate::bedding::cache_dir()?;
        Ok(cache_dir.join("brz.log"))
    }
}

pub fn rollover_trace_maybe(trace_fname: &Path) -> io::Result<()> {
    /// Roll over the trace log file if it exceeds a certain size.

    const MAX_LOG_SIZE: u64 = 4 * (1 << 20); // 4 MB

    let size = metadata(trace_fname)?.len();
    if size <= MAX_LOG_SIZE {
        return Ok(());
    }

    let old_fname = trace_fname.with_extension("log.old");
    rename(trace_fname, old_fname)?;
    Ok(())
}

/// Open existing log file, or create with ownership and permissions
///
/// It inherits the ownership and permissions (masked by umask) from the containing directory
/// to cope better with being run under sudo with `$HOME` still set to the user's homedir.
pub fn open_or_create_log_file<P: AsRef<Path>>(filename: P) -> std::io::Result<File> {
    let mut flags = OpenOptions::new();

    flags.append(true);

    loop {
        match flags.open(filename.as_ref()) {
            Ok(fd) => return Ok(fd),
            Err(e) if e.kind() == io::ErrorKind::NotFound => {
                let mut flags = OpenOptions::new();
                flags.create(true).truncate(true).write(true);

                match flags.open(&filename) {
                    Ok(fd) => {
                        // Copy ownership from containing directory.
                        breezy_osutils::file::copy_ownership_from_path(&filename, None)?;
                        return Ok(fd);
                    }
                    Err(e) if e.kind() == io::ErrorKind::AlreadyExists => continue,
                    Err(e) => return Err(e),
                }
            }
            Err(e) => return Err(e),
        }
    }
}

static BRZ_LOG_FILENAME: once_cell::sync::Lazy<RwLock<Option<PathBuf>>> =
    once_cell::sync::Lazy::new(|| RwLock::new(None));

pub fn get_brz_log_filename() -> Option<PathBuf> {
    let guard = BRZ_LOG_FILENAME.read().unwrap();
    guard.clone()
}

pub fn set_brz_log_filename(filename: Option<&Path>) {
    let mut guard = BRZ_LOG_FILENAME.write().unwrap();
    *guard = filename.map(|p| p.to_path_buf());
}

/// Open the brz.log trace file.
///
/// If the log is more than a particular length, the old file is renamed to `brz.log.old`
/// and a new file is started. Otherwise, we append to the existing file.
///
/// This sets the global `_brz_log_filename`.
pub fn open_brz_log() -> Option<File> {
    let filename = initialize_brz_log_filename().ok()?;
    set_brz_log_filename(Some(filename.as_path()));
    rollover_trace_maybe(&filename).ok();

    let mut brz_log_file = match open_or_create_log_file(&filename) {
        Ok(fd) => fd,
        Err(e) => {
            // If we are failing to open the log, then most likely logging has not
            // been set up yet. So we just write to stderr rather than using 'warning()'.
            // If we use warning(), users get the unhelpful 'no handlers registered for "brz"'
            // when something goes wrong on the server. (bug #503886)
            eprintln!("failed to open trace file: {}: {}", filename.display(), e);
            return None;
        }
    };

    // Write a header to the log file if it is empty.
    if brz_log_file
        .metadata()
        .ok()
        .is_some_and(|md| md.len() == 0)
    {
        if let Err(e) = writeln!(
            brz_log_file,
            "this is a debug log for diagnosing/reporting problems in brz"
        ) {
            eprintln!("failed to write to trace file: {}", e);
        }
        if let Err(e) = writeln!(
            brz_log_file,
            "you can delete or truncate this file, or include sections in"
        ) {
            eprintln!("failed to write to trace file: {}", e);
        }
        if let Err(e) = writeln!(
            brz_log_file,
            "bug reports to https://bugs.launchpad.net/brz/+filebug"
        ) {
            eprintln!("failed to write to trace file: {}", e);
        }
    }

    Some(brz_log_file)
}

pub struct BreezyTraceLogger<F> {
    file: Mutex<F>,
    start_time: chrono::DateTime<chrono::Local>,
    short: bool,
}

impl<F: Write> BreezyTraceLogger<F> {
    pub fn new(mut file: F, short: bool) -> Self {
        let start_time = chrono::Local::now();
        if !short {
            let start_time = breezy_osutils::time::format_local_date(
                start_time.timestamp(),
                None,
                breezy_osutils::time::Timezone::Local,
                None,
                true,
            );
            file.write_all((start_time + "\n").as_bytes())
                .expect("failed to write to trace file");
        }
        Self {
            file: Mutex::new(file),
            short,
            start_time,
        }
    }

    pub fn mutter(&self, msg: &str) {
        let elapsed = chrono::Local::now().signed_duration_since(self.start_time);

        let mut file = self.file.lock().unwrap();
        writeln!(
            file,
            "{:.3}  {msg}",
            elapsed.num_seconds() as f64 + elapsed.num_microseconds().unwrap() as f64 / 1_000_000.0
        )
        .expect("failed to write to trace file");

        file.flush().expect("failed to flush trace file");
    }
}

impl Default for BreezyTraceLogger<File> {
    fn default() -> Self {
        let file = open_brz_log();
        Self::new(
            file.unwrap_or_else(|| panic!("failed to open trace file")),
            false,
        )
    }
}

impl Default for BreezyTraceLogger<Box<dyn Write + Send>> {
    fn default() -> Self {
        let file = open_brz_log();
        Self::new(
            Box::new(file.unwrap_or_else(|| panic!("failed to open trace file"))),
            false,
        )
    }
}

impl<F: Write + Send> log::Log for BreezyTraceLogger<F> {
    fn enabled(&self, metadata: &log::Metadata<'_>) -> bool {
        metadata.level() <= log::Level::Debug
    }

    fn log(&self, record: &log::Record<'_>) {
        if self.enabled(record.metadata()) {
            // Mimic the python log format:
            // r'[%(process)5d] %(asctime)s.%(msecs)03d %(levelname)s: %(message)s'
            let now = chrono::Local::now();
            let level = match record.level() {
                log::Level::Error => "ERROR",
                log::Level::Warn => "WARNING",
                log::Level::Info => "INFO",
                log::Level::Debug => "DEBUG",
                log::Level::Trace => "TRACE",
            };
            if self.short {
                self.file
                    .lock()
                    .unwrap()
                    .write_all(format!("{:>8}  {}\n", level, record.args()).as_bytes())
                    .expect("failed to write to trace file");
            } else {
                self.file
                    .lock()
                    .unwrap()
                    .write_all(
                        format!(
                            "[{:5}] {}.{:03} {}: {}\n",
                            std::process::id(),
                            now.format("%Y-%m-%d %H:%M:%S"),
                            now.timestamp_subsec_millis(),
                            level,
                            record.args()
                        )
                        .as_bytes(),
                    )
                    .expect("failed to write to trace file");
            }
        }
    }

    fn flush(&self) {
        self.file.lock().unwrap().flush().ok();
    }
}

struct BreezyStderrLogger {}

impl BreezyStderrLogger {
    pub fn new() -> Self {
        Self {}
    }
}

impl Default for BreezyStderrLogger {
    fn default() -> Self {
        Self::new()
    }
}

impl log::Log for BreezyStderrLogger {
    fn enabled(&self, metadata: &log::Metadata<'_>) -> bool {
        metadata.level() <= log::Level::Info
    }

    fn log(&self, record: &log::Record<'_>) {
        if self.enabled(record.metadata()) {
            eprintln!("{}", record.args());
        }
    }

    fn flush(&self) {
        std::io::stderr().flush().ok();
    }
}

const SHORT_FIELDS: [&str; 3] = ["VmPeak", "VmSize", "VmRSS"];

#[cfg(unix)]
pub fn debug_memory_proc(message: &str, short: bool) {
    if let Ok(mut status_file) = File::open(format!("/proc/{}/status", std::process::id())) {
        let mut status = String::new();
        if status_file.read_to_string(&mut status).is_ok() {
            if !message.is_empty() {
                info!("{}", message);
            }
            for line in status.lines() {
                if !short {
                    info!("{}", line);
                } else {
                    for field in &SHORT_FIELDS {
                        if line.starts_with(field) {
                            info!("{}", line);
                            break;
                        }
                    }
                }
            }
        }
    }
}
