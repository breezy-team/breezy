use pyo3::prelude::*;
use std::path::PathBuf;

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

    Ok(())
}
