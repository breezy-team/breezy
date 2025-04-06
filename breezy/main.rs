use pyo3::exceptions::{PyKeyboardInterrupt, PySystemExit};
use pyo3::prelude::*;
use pyo3::types::*;
use std::path::*;

const EXIT_ERROR: i32 = 3;

fn check_version(py: Python<'_>) -> PyResult<()> {
    let major: u32 = env!("CARGO_PKG_VERSION_MAJOR").parse::<u32>().unwrap();
    let minor: u32 = env!("CARGO_PKG_VERSION_MINOR").parse::<u32>().unwrap();
    let patch: u32 = env!("CARGO_PKG_VERSION_PATCH").parse::<u32>().unwrap();
    let breezy = PyModule::import(py, "breezy").map_err(|e| {
        eprintln!(
            "brz: ERROR: Couldn't import breezy and dependencies.\n\
             Please check the directory containing breezy is on your PYTHONPATH.\n"
        );
        e
    })?;

    let ver = breezy
        .getattr("version_info")?
        .extract::<(u32, u32, u32, String, u32)>()?;

    if ver.0 != major || ver.1 != minor || ver.2 != patch {
        eprintln!(
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

    let current_path = path_obj.downcast::<PyList>()?;

    current_path.insert(0, el.to_str().expect("invalid local path"))?;

    Ok(())
}

// Prepend sys.path with the brz path when useful.
fn update_path(py: Python<'_>) -> PyResult<()> {
    let mut path = std::env::current_exe()?;

    path.pop(); // Drop executable name

    let mut package_path = path.clone();
    package_path.push("breezy");
    if package_path.is_dir() {
        prepend_path(py, path.as_path())?;
    }

    Ok(())
}

fn posix_setup(py: Python<'_>) -> PyResult<()> {
    let os = PyModule::import(py, "os")?;

    if os.getattr("name")?.to_string() == "posix" {
        if let Err(e) = setup_locale(py) {
            eprintln!(
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
    pyo3::prepare_freethreaded_python();

    fn main(py: Python) -> PyResult<Bound<PyAny>> {
        posix_setup(py)?;

        update_path(py)?;

        check_version(py)?;

        let args: Vec<String> = std::env::args().collect();

        if args.contains(&String::from("--profile-imports")) {
            let profile_imports = PyModule::import(py, "profile_imports")?;
            profile_imports.getattr("install")?.call1(())?;
        }

        let sys = PyModule::import(py, "sys")?;
        sys.setattr("argv", PyList::new(py, args)?)?;

        let main = PyModule::import(py, "breezy.__main__")?;
        main.getattr("main")?.call1(())
    }

    Python::with_gil(|py| {
        let result = main(py);
        std::process::exit(match result {
            Ok(_) => 0,
            Err(e) if e.is_instance_of::<PySystemExit>(py) => {
                eprintln!("brz: {}", e);
                e.value(py)
                    .getattr("code")
                    .unwrap()
                    .extract::<i32>()
                    .unwrap()
            }
            Err(e) if e.is_instance_of::<PyKeyboardInterrupt>(py) => {
                eprintln!("brz: interrupted");
                EXIT_ERROR
            }
            Err(e) => {
                eprintln!("brz: ERROR: {}", e);
                EXIT_ERROR
            }
        });
    });
}
