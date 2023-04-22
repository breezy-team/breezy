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

    Ok(())
}
