use log::Log;
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3_file::PyFileLikeObject;
use std::io::Write;
use std::path::PathBuf;

import_exception!(breezy.errors, NoWhoami);

#[pyfunction(name = "disable_i18n")]
fn i18n_disable_i18n() {
    breezy::i18n::disable();
}

#[pyfunction(name = "dgettext")]
fn i18n_dgettext(domain: &str, msgid: &str) -> PyResult<String> {
    Ok(breezy::i18n::dgettext(domain, msgid))
}

#[pyfunction(name = "install")]
fn i18n_install(lang: Option<&str>, locale_base: Option<PathBuf>) -> PyResult<()> {
    let locale_base = locale_base.as_ref().map(|p| p.as_path());
    breezy::i18n::install(lang, locale_base)?;
    Ok(())
}

#[pyfunction(name = "install_plugin")]
fn i18n_install_plugin(name: &str, locale_base: Option<PathBuf>) -> PyResult<()> {
    let locale_base = locale_base.as_ref().map(|p| p.as_path());
    breezy::i18n::install_plugin(name, locale_base)?;
    Ok(())
}

#[pyfunction(name = "gettext")]
fn i18n_gettext(msgid: &str) -> PyResult<String> {
    Ok(breezy::i18n::gettext(msgid))
}

#[pyfunction(name = "ngettext")]
fn i18n_ngettext(msgid: &str, msgid_plural: &str, n: u32) -> PyResult<String> {
    Ok(breezy::i18n::ngettext(msgid, msgid_plural, n))
}

#[pyfunction]
fn ensure_config_dir_exists(path: Option<PathBuf>) -> PyResult<()> {
    breezy::bedding::ensure_config_dir_exists(path.as_ref().map(|p| p.as_path()))?;
    Ok(())
}

#[pyfunction]
fn config_dir() -> PyResult<PathBuf> {
    Ok(breezy::bedding::config_dir()?)
}

#[pyfunction]
fn _config_dir() -> PyResult<(PathBuf, String)> {
    Ok(breezy::bedding::_config_dir().map(|(p, k)| (p, k.to_string()))?)
}

#[pyfunction]
fn bazaar_config_dir() -> PyResult<PathBuf> {
    Ok(breezy::bedding::bazaar_config_dir()?)
}

#[pyfunction]
fn config_path() -> PyResult<PathBuf> {
    Ok(breezy::bedding::config_path()?)
}

#[pyfunction]
fn locations_config_path() -> PyResult<PathBuf> {
    Ok(breezy::bedding::locations_config_path()?)
}

#[pyfunction]
fn authentication_config_path() -> PyResult<PathBuf> {
    Ok(breezy::bedding::authentication_config_path()?)
}

#[pyfunction]
fn user_ignore_config_path() -> PyResult<PathBuf> {
    Ok(breezy::bedding::user_ignore_config_path()?)
}

#[pyfunction]
fn crash_dir() -> PyResult<PathBuf> {
    Ok(breezy::bedding::crash_dir())
}

#[pyfunction]
fn cache_dir() -> PyResult<PathBuf> {
    Ok(breezy::bedding::cache_dir()?)
}

#[pyfunction]
fn get_default_mail_domain(mailname_file: Option<PathBuf>) -> Option<String> {
    breezy::bedding::get_default_mail_domain(mailname_file.as_deref())
}

#[pyfunction]
fn default_email() -> PyResult<String> {
    match breezy::bedding::default_email() {
        Some(email) => Ok(email),
        None => Err(NoWhoami::new_err(())),
    }
}

#[pyfunction]
fn auto_user_id() -> PyResult<(Option<String>, Option<String>)> {
    Ok(breezy::bedding::auto_user_id()?)
}

#[pyfunction]
fn initialize_brz_log_filename() -> PyResult<PathBuf> {
    Ok(breezy::trace::initialize_brz_log_filename()?)
}

#[pyfunction]
fn rollover_trace_maybe(path: PathBuf) -> PyResult<()> {
    Ok(breezy::trace::rollover_trace_maybe(path.as_path())?)
}

#[pyclass]
struct PyLogFile(std::fs::File);

#[pymethods]
impl PyLogFile {
    fn write(&mut self, data: &[u8]) -> PyResult<usize> {
        Ok(self.0.write(data)?)
    }

    fn flush(&mut self) -> PyResult<()> {
        Ok(self.0.flush()?)
    }
}

#[pyfunction]
fn open_or_create_log_file(path: PathBuf) -> PyResult<PyLogFile> {
    Ok(PyLogFile(breezy::trace::open_or_create_log_file(
        path.as_path(),
    )?))
}

#[pyfunction]
fn open_brz_log() -> PyResult<Option<PyLogFile>> {
    Ok(breezy::trace::open_brz_log().map(PyLogFile))
}

#[pyfunction]
fn set_brz_log_filename(path: Option<PathBuf>) -> PyResult<()> {
    Ok(breezy::trace::set_brz_log_filename(path.as_deref()))
}

#[pyfunction]
fn get_brz_log_filename() -> PyResult<Option<PathBuf>> {
    Ok(breezy::trace::get_brz_log_filename())
}

#[pyclass]
struct BreezyTraceHandler(
    Box<std::sync::Arc<breezy::trace::BreezyTraceLogger<Box<dyn Write + Send>>>>,
);

#[pymethods]
impl BreezyTraceHandler {
    #[new]
    fn new(f: PyObject) -> PyResult<Self> {
        let f = PyFileLikeObject::with_requirements(f, false, true, false)?;
        Ok(Self(Box::new(std::sync::Arc::new(
            breezy::trace::BreezyTraceLogger::new(Box::new(f)),
        ))))
    }

    #[getter]
    fn get_level(&self) -> PyResult<u32> {
        Ok(20) // DEBUG
    }

    fn close(&mut self) -> PyResult<()> {
        // TODO(jelmer): close underlying file?
        Ok(())
    }

    fn handle(&self, py: Python, pyr: PyObject) -> PyResult<()> {
        let formatted = pyr
            .getattr(py, "msg")?
            .call_method1(py, "format", (pyr.getattr(py, "args")?,))?
            .extract::<String>(py)?;

        let mut rb = log::Record::builder();
        let mut r = &mut rb;

        if let Ok(level) = pyr.getattr(py, "levelno") {
            r = r.level(match level.extract::<u32>(py)? {
                10 => log::Level::Debug,
                20 => log::Level::Info,
                30 => log::Level::Warn,
                40 => log::Level::Error,
                50 => log::Level::Error, // CRITICAL
                _ => log::Level::Trace,  // UNKNOWN
            });
        }

        if let Ok(path) = pyr.as_ref(py).getattr("pathname") {
            r = r.file(Some(path.extract::<&str>()?));
        }

        if let Ok(func) = pyr.getattr(py, "lineno") {
            r = r.line(Some(func.extract::<u32>(py)?));
        }

        if let Ok(module) = pyr.as_ref(py).getattr("module") {
            r = r.module_path(Some(module.extract::<&str>()?));
        }

        self.0.log(&r.args(format_args!("{}", formatted)).build());
        Ok(())
    }
}

#[pymodule]
fn _cmd_rs(_py: Python, m: &PyModule) -> PyResult<()> {
    let i18n = PyModule::new(_py, "i18n")?;
    i18n.add_function(wrap_pyfunction!(i18n_install, i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_install_plugin, i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_gettext, i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_ngettext, i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_disable_i18n, i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_dgettext, i18n)?)?;
    m.add_submodule(i18n)?;
    m.add_function(wrap_pyfunction!(ensure_config_dir_exists, m)?)?;
    m.add_function(wrap_pyfunction!(config_dir, m)?)?;
    m.add_function(wrap_pyfunction!(bazaar_config_dir, m)?)?;
    m.add_function(wrap_pyfunction!(_config_dir, m)?)?;
    m.add_function(wrap_pyfunction!(config_path, m)?)?;
    m.add_function(wrap_pyfunction!(locations_config_path, m)?)?;
    m.add_function(wrap_pyfunction!(authentication_config_path, m)?)?;
    m.add_function(wrap_pyfunction!(user_ignore_config_path, m)?)?;
    m.add_function(wrap_pyfunction!(crash_dir, m)?)?;
    m.add_function(wrap_pyfunction!(cache_dir, m)?)?;
    m.add_function(wrap_pyfunction!(get_default_mail_domain, m)?)?;
    m.add_function(wrap_pyfunction!(default_email, m)?)?;
    m.add_function(wrap_pyfunction!(auto_user_id, m)?)?;
    m.add_function(wrap_pyfunction!(initialize_brz_log_filename, m)?)?;
    m.add_function(wrap_pyfunction!(rollover_trace_maybe, m)?)?;
    m.add_function(wrap_pyfunction!(open_or_create_log_file, m)?)?;
    m.add_function(wrap_pyfunction!(open_brz_log, m)?)?;
    m.add_function(wrap_pyfunction!(set_brz_log_filename, m)?)?;
    m.add_function(wrap_pyfunction!(get_brz_log_filename, m)?)?;
    m.add_class::<BreezyTraceHandler>()?;

    Ok(())
}
