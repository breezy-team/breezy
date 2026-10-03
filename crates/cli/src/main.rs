use pyo3::exceptions::{PyKeyboardInterrupt, PySystemExit};
use pyo3::prelude::*;
use pyo3::types::*;
use std::io::Write;
use std::path::*;

const EXIT_ERROR: i32 = 3;

/// Like `eprintln!`, but without panicking when stderr can not be written to,
/// such as when it is a closed pipe. There is nowhere left to report that, and
/// the exit code still tells the caller that something went wrong.
macro_rules! report {
    ($($arg:tt)*) => {
        write_line(&mut std::io::stderr(), format_args!($($arg)*))
    };
}

fn write_line(out: &mut dyn Write, message: std::fmt::Arguments<'_>) {
    let _ = writeln!(out, "{message}");
}

/// The exit code for a `SystemExit`, as Python determines it: success without a
/// code, the code itself if it is an integer, and failure for anything else
/// (such as a message).
fn system_exit_code(py: Python<'_>, e: &PyErr) -> i32 {
    match e.value(py).getattr("code") {
        Ok(code) if code.is_none() => 0,
        Ok(code) => code.extract::<i32>().unwrap_or(1),
        Err(_) => 1,
    }
}

fn check_version(py: Python<'_>) -> PyResult<()> {
    let major: u32 = env!("CARGO_PKG_VERSION_MAJOR").parse::<u32>().unwrap();
    let minor: u32 = env!("CARGO_PKG_VERSION_MINOR").parse::<u32>().unwrap();
    let patch: u32 = env!("CARGO_PKG_VERSION_PATCH").parse::<u32>().unwrap();
    let breezy = PyModule::import(py, "breezy").inspect_err(|_e| {
        report!(
            "brz: ERROR: Couldn't import breezy and dependencies.\n\
             Please check the directory containing breezy is on your PYTHONPATH.\n"
        );
    })?;

    let ver = breezy
        .getattr("version_info")?
        .extract::<(u32, u32, u32, String, u32)>()?;

    if ver.0 != major || ver.1 != minor || ver.2 != patch {
        report!(
            "\
            brz: WARNING: breezy version doesn't match the brz program.\n  \
            This may indicate an installation problem.\n  \
            breezy version is {}\n  \
            brz version is {}.{}.{}\n",
            breezy.getattr("_format_version_tuple")?.call1((ver,))?,
            major,
            minor,
            patch
        );
    }
    Ok(())
}

fn setup_locale(py: Python<'_>) -> PyResult<()> {
    let locale = PyModule::import(py, "locale")?;
    locale
        .getattr("setlocale")?
        .call1((locale.getattr("LC_ALL")?, ""))?;
    Ok(())
}

fn prepend_path(py: Python<'_>, el: &Path) -> PyResult<()> {
    let sys = PyModule::import(py, "sys")?;

    let path_obj = sys.getattr("path")?;

    let current_path = path_obj.cast::<PyList>()?;

    current_path.insert(0, el.to_str().expect("invalid local path"))?;

    Ok(())
}

// Prepend sys.path with the brz path when useful.
fn update_path(py: Python<'_>) -> PyResult<()> {
    if let Ok(mut path) = std::env::current_exe() {
        path.pop(); // Drop executable name

        let mut package_path = path.clone();
        package_path.push("breezy");
        if package_path.is_dir() {
            prepend_path(py, path.as_path())?;
        }
    }

    Ok(())
}

fn posix_setup(py: Python<'_>) -> PyResult<()> {
    let os = PyModule::import(py, "os")?;

    if os.getattr("name")?.to_string() == "posix" {
        if let Err(e) = setup_locale(py) {
            report!(
                "brz: WARNING: {}\n  \
                Could not set the application locale.\n  \
                Although this should be no problem for bzr itself, it might\n  \
                cause problems with some plugins. To investigate the issue,\n  \
                look at the output of the locale(1p) tool.\n",
                e
            );
        };
    }
    Ok(())
}

fn main() {
    Python::initialize();

    Python::attach(|py| {
        let result = (|| -> PyResult<Bound<PyAny>> {
            posix_setup(py)?;

            update_path(py)?;

            check_version(py)?;

            let args: Vec<String> = std::env::args().collect();

            if args.contains(&String::from("--profile-imports")) {
                let profile_imports = PyModule::import(py, "profile_imports")?;
                profile_imports.getattr("install")?.call0()?;
            }

            let sys = PyModule::import(py, "sys")?;
            sys.setattr("argv", PyList::new(py, args)?)?;

            let main = PyModule::import(py, "breezy.__main__")?;
            main.getattr("main")?.call0()
        })();

        std::process::exit(match result {
            Ok(_) => 0,
            Err(e) if e.is_instance_of::<PySystemExit>(py) => {
                report!("brz: {}", e);
                system_exit_code(py, &e)
            }
            Err(e) if e.is_instance_of::<PyKeyboardInterrupt>(py) => {
                report!("brz: interrupted");
                EXIT_ERROR
            }
            Err(e) => {
                report!("brz: ERROR: {}", e);
                EXIT_ERROR
            }
        });
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Closed;

    impl Write for Closed {
        fn write(&mut self, _buf: &[u8]) -> std::io::Result<usize> {
            Err(std::io::ErrorKind::BrokenPipe.into())
        }

        fn flush(&mut self) -> std::io::Result<()> {
            Err(std::io::ErrorKind::BrokenPipe.into())
        }
    }

    #[test]
    fn write_line_to_closed_stream() {
        write_line(&mut Closed, format_args!("brz: ERROR: {}", "lost"));
    }

    fn exit_code(code: &str) -> i32 {
        Python::initialize();
        Python::attach(|py| {
            let err = py
                .run(
                    &std::ffi::CString::new(format!("raise SystemExit({code})")).unwrap(),
                    None,
                    None,
                )
                .unwrap_err();
            system_exit_code(py, &err)
        })
    }

    #[test]
    fn system_exit_codes() {
        assert_eq!(0, exit_code(""));
        assert_eq!(0, exit_code("None"));
        assert_eq!(7, exit_code("7"));
        assert_eq!(1, exit_code("'bye'"));
    }
}
