use pkg_version::*;
use pyo3::prelude::*;
use pyo3::types::*;

const MAJOR: u32 = pkg_version_major!();
const MINOR: u32 = pkg_version_minor!();
const PATCH: u32 = pkg_version_patch!();

fn check_version(py: Python<'_>) -> PyResult<()> {
    let breezy = PyModule::import(py, "breezy").map_err(|e| {
        eprintln!(
            "brz: ERROR: Couldn't import breezy and dependencies.\n\
             Please check the directory containing breezy is on your PYTHONPATH.\n"
        );
        e
    })?;

    let ver = breezy
        .getattr("version_info")?
        .extract::<Py<PyTuple>>()?
        .into_ref(py);

    if ver.len() < 3
        || ver.get_item(0).extract::<u32>()? != MAJOR
        || ver.get_item(1).extract::<u32>()? != MINOR
        || ver.get_item(2).extract::<u32>()? != PATCH
    {
        eprintln!(
            "\
            brz: WARNING: breezy version doesn't match the brz program.\n  \
            This may indicate an installation problem.\n  \
            breezy version is {}\n  \
            brz version is {}.{}.{}\n",
            breezy.getattr("_format_version_tuple")?.call1((ver,))?,
            MAJOR,
            MINOR,
            PATCH
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

fn posix_setup(py: Python<'_>) -> PyResult<()> {
    let os = PyModule::import(py, "os")?;

    if os.getattr("name")?.to_string() == "posix" {
        match setup_locale(py) {
            Err(e) => eprintln!(
                "brz: WARNING: {}\n  \
              Could not set the application locale.\n  \
              Although this should be no problem for bzr itself, it might\n  \
              cause problems with some plugins. To investigate the issue,\n  \
              look at the output of the locale(1p) tool.\n",
                e
            ),
            Ok(()) => (),
        };

        let sys = PyModule::import(py, "sys")?;
        sys.setattr("_brz_default_fs_enc", "utf-8")?;
    }
    Ok(())
}

// profiling = False
// if '--profile-imports' in sys.argv:
//     import profile_imports
//     profile_imports.install()
//     profiling = True

fn main() -> PyResult<()> {
    Python::with_gil(|py| {
        posix_setup(py)?;

        check_version(py)?;

        let main = PyModule::import(py, "breezy.__main__")?;
        main.getattr("main")?.call1(())?;
        Ok(())
    })
}
