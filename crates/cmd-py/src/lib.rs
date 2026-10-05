use breezy::graphshim::Graph;
use breezy::pybranch::PyBranch;
use breezy::pytree::PyTree;
use breezy::RevisionId;

use log::Log;
use pyo3::exceptions::{
    PyEOFError, PyIOError, PyNotImplementedError, PyRuntimeError, PyValueError,
};
use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::pyclass::CompareOp;
use pyo3::types::{PyBytes, PyString, PyTuple, PyType};
use pyo3_filelike::PyBinaryFile;
use std::io::Write;
use std::path::PathBuf;

import_exception!(breezy.errors, NoWhoami);
import_exception!(breezy.errors, LockCorrupt);
import_exception!(breezy.errors, NoSuchTag);
import_exception!(breezy.errors, TagAlreadyExists);

import_exception!(breezy.bugtracker, MalformedBugIdentifier);
import_exception!(breezy.bugtracker, InvalidBugTrackerURL);
import_exception!(breezy.bugtracker, InvalidBugUrl);
import_exception!(breezy.bugtracker, InvalidLineInBugsProperty);
import_exception!(breezy.bugtracker, InvalidBugStatus);

fn map_bugtracker_error(err: breezy::bugtracker::Error) -> PyErr {
    use breezy::bugtracker::Error;
    match err {
        Error::MalformedBugIdentifier { bug_id, reason } => {
            MalformedBugIdentifier::new_err((bug_id, reason))
        }
        Error::InvalidBugTrackerUrl { abbreviation, url } => {
            InvalidBugTrackerURL::new_err((abbreviation, url))
        }
        Error::InvalidBugUrl { url } => InvalidBugUrl::new_err((url,)),
        Error::InvalidLineInBugsProperty { line } => InvalidLineInBugsProperty::new_err((line,)),
        Error::InvalidBugStatus { status } => InvalidBugStatus::new_err((status,)),
    }
}

fn map_gettext_error(err: gettext::Error) -> PyErr {
    let err_msg = err.to_string();
    match err {
        gettext::Error::Eof => PyErr::new::<PyEOFError, _>(err_msg),
        gettext::Error::Io(_) => PyErr::new::<PyIOError, _>(err_msg),
        _ => PyErr::new::<PyRuntimeError, _>(err_msg),
    }
}

#[pyfunction(name = "disable_i18n")]
fn i18n_disable_i18n() {
    breezy::i18n::disable();
}

#[pyfunction(name = "dgettext")]
fn i18n_dgettext(domain: &str, msgid: &str) -> PyResult<String> {
    Ok(breezy::i18n::dgettext(domain, msgid))
}

#[pyfunction(name = "install")]
fn i18n_install(lang: &str, locale_base: PathBuf) -> PyResult<()> {
    breezy::i18n::install(lang, locale_base).map_err(map_gettext_error)?;
    Ok(())
}

#[pyfunction(name = "install_zzz")]
fn i18n_install_zzz() -> PyResult<()> {
    breezy::i18n::install_zzz();
    Ok(())
}

#[pyfunction(name = "install_zzz_for_doc")]
fn i18n_install_zzz_for_doc() -> PyResult<()> {
    breezy::i18n::install_zzz_for_doc();
    Ok(())
}

#[pyfunction(name = "install_plugin")]
#[pyo3(signature = (name, locale_base = None))]
fn i18n_install_plugin(name: &str, locale_base: Option<PathBuf>) -> PyResult<()> {
    breezy::i18n::install_plugin(name, locale_base).map_err(map_gettext_error)?;
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

#[pyfunction(name = "gettext_per_paragraph")]
fn i18n_gettext_per_paragraph(text: &str) -> PyResult<String> {
    Ok(breezy::i18n::gettext_per_paragraph(text))
}

#[pyfunction(name = "zzz")]
fn i18n_zzz(msgid: &str) -> PyResult<String> {
    Ok(breezy::i18n::zzz(msgid))
}

#[pyfunction]
#[pyo3(signature = (path = None))]
fn ensure_config_dir_exists(path: Option<PathBuf>) -> PyResult<()> {
    breezy::bedding::ensure_config_dir_exists(path.as_deref())?;
    Ok(())
}

#[pyfunction]
fn config_dir() -> PyResult<String> {
    let path = breezy::bedding::config_dir()?;

    path.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyValueError::new_err("Invalid config directory"))
}

#[pyfunction]
fn _config_dir() -> PyResult<(String, String)> {
    let (path, kind) = breezy::bedding::_config_dir()?;

    let path = path
        .to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyValueError::new_err("Invalid config directory"))?;

    Ok((path, kind.to_string()))
}

#[pyfunction]
fn bazaar_config_dir() -> PyResult<String> {
    let path = breezy::bedding::bazaar_config_dir()?;

    path.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyValueError::new_err("Invalid bazaar config directory"))
}

#[pyfunction]
fn config_path() -> PyResult<String> {
    let path = breezy::bedding::config_path()?;

    path.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyValueError::new_err("Invalid config path"))
}

#[pyfunction]
fn locations_config_path() -> PyResult<String> {
    let path = breezy::bedding::locations_config_path()?;

    path.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyValueError::new_err("Invalid locations config path"))
}

#[pyfunction]
fn authentication_config_path() -> PyResult<String> {
    let path = breezy::bedding::authentication_config_path()?;

    path.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyValueError::new_err("Invalid authentication config path"))
}

#[pyfunction]
fn user_ignore_config_path() -> PyResult<String> {
    let path = breezy::bedding::user_ignore_config_path()?;

    path.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyValueError::new_err("Invalid user ignore config path"))
}

#[pyfunction]
fn crash_dir() -> PyResult<String> {
    let path = breezy::bedding::crash_dir();

    path.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyValueError::new_err("Invalid crash directory"))
}

#[pyfunction]
fn cache_dir() -> PyResult<String> {
    let path = breezy::bedding::cache_dir()?;

    path.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyValueError::new_err("Invalid cache directory"))
}

#[pyfunction]
#[pyo3(signature = (mailname_file = None))]
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
fn initialize_brz_log_filename() -> PyResult<String> {
    let path = breezy::trace::initialize_brz_log_filename()?;

    path.to_str()
        .map(|s| s.to_string())
        .ok_or_else(|| PyValueError::new_err("Invalid log filename"))
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
    breezy::trace::set_brz_log_filename(path.as_deref());
    Ok(())
}

#[pyfunction]
fn get_brz_log_filename() -> PyResult<Option<String>> {
    let path = breezy::trace::get_brz_log_filename();

    path.map(|s| {
        s.to_str()
            .map(|s| s.to_string())
            .ok_or_else(|| PyValueError::new_err("Invalid log filename"))
    })
    .transpose()
}

#[pyclass]
struct BreezyTraceHandler(
    Box<std::sync::Arc<breezy::trace::BreezyTraceLogger<Box<dyn Write + Send>>>>,
);

fn format_exception(py: Python, ei: &Bound<PyTuple>) -> PyResult<String> {
    let io = py.import("io")?;
    let sio = io.call_method0("StringIO")?;

    let tb = py.import("traceback")?;
    tb.call_method1(
        "print_exception",
        (
            ei.get_item(0)?,
            ei.get_item(1)?,
            ei.get_item(2)?,
            py.None(),
            &sio,
        ),
    )?;

    let ret = sio.call_method0("getvalue")?.extract::<String>()?;

    sio.call_method0("close")?;

    Ok(ret)
}

fn log_exception_quietly(py: Python, log: &dyn log::Log, err: &PyErr) -> PyResult<()> {
    let traceback = py.import("traceback")?;
    let tb = traceback
        .call_method1(
            "format_exception",
            (err.get_type(py), err.value(py), err.traceback(py)),
        )?
        .extract::<Vec<String>>()?;
    log.log(
        &log::Record::builder()
            .args(format_args!("{}", tb.join("")))
            .level(log::Level::Debug)
            .target("brz")
            .build(),
    );
    log.flush();
    Ok(())
}

#[pymethods]
impl BreezyTraceHandler {
    #[new]
    fn new(f: Py<PyAny>, short: bool) -> PyResult<Self> {
        let f = PyBinaryFile::from(f);
        Ok(Self(Box::new(std::sync::Arc::new(
            breezy::trace::BreezyTraceLogger::new(Box::new(f), short),
        ))))
    }

    fn mutter(&self, msg: &str) -> PyResult<()> {
        self.0.mutter(msg);
        Ok(())
    }

    #[getter]
    fn get_level(&self) -> PyResult<u32> {
        Ok(10) // DEBUG
    }

    fn close(&mut self) -> PyResult<()> {
        // TODO(jelmer): close underlying file?
        Ok(())
    }

    fn flush(&mut self) -> PyResult<()> {
        self.0.flush();
        Ok(())
    }

    fn handle(&self, py: Python, pyr: Py<PyAny>) -> PyResult<()> {
        let msg = pyr.call_method0(py, "getMessage");

        let mut formatted = if let Err(err) = msg {
            log_exception_quietly(py, &self.0, &err)?;

            let msg = pyr.getattr(py, "msg")?;
            let args = pyr.getattr(py, "args")?;

            PyString::new(py, "Logging record unformattable: {} % {}")
                .call_method1(
                    "format",
                    (msg.bind(py).repr().ok(), args.bind(py).repr().ok()),
                )?
                .to_string()
        } else {
            msg.unwrap().extract::<String>(py)?
        };

        if let Ok(exc_info) = pyr.getattr(py, "exc_info") {
            if let Ok(exc_info) = exc_info.extract::<Bound<PyTuple>>(py) {
                if !formatted.ends_with('\n') {
                    formatted.push('\n');
                }
                formatted += format_exception(py, &exc_info)?.as_str();
            }
        }

        if let Ok(stack_info) = pyr.getattr(py, "stack_info") {
            if let Ok(stack_info) = stack_info.extract::<String>(py) {
                if !formatted.ends_with('\n') {
                    formatted.push('\n');
                }
                formatted += &stack_info;
            }
        }

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

        let path;
        if let Ok(p) = pyr.bind(py).getattr("pathname") {
            path = p.extract::<String>()?;
            r = r.file(Some(&path));
        }

        if let Ok(func) = pyr.getattr(py, "lineno") {
            r = r.line(Some(func.extract::<u32>(py)?));
        }

        let module;
        if let Ok(m) = pyr.bind(py).getattr("module") {
            module = m.extract::<String>()?;
            r = r.module_path(Some(&module));
        }

        let name;
        if let Ok(n) = pyr.bind(py).getattr("name") {
            name = n.extract::<String>()?;
            r = r.target(&name);
        }

        self.0.log(&r.args(format_args!("{}", formatted)).build());
        self.0.flush();
        Ok(())
    }
}

#[pyfunction]
fn set_debug_flag(flag: &str) -> PyResult<()> {
    breezy::debug::set_debug_flag(flag);
    Ok(())
}

#[pyfunction]
fn unset_debug_flag(flag: &str) -> PyResult<()> {
    breezy::debug::unset_debug_flag(flag);
    Ok(())
}

#[pyfunction]
fn get_debug_flags() -> PyResult<std::collections::HashSet<String>> {
    Ok(breezy::debug::get_debug_flags())
}

#[pyfunction]
fn clear_debug_flags() -> PyResult<()> {
    breezy::debug::clear_debug_flags();
    Ok(())
}

#[pyfunction]
fn debug_flag_enabled(flag: &str) -> PyResult<bool> {
    Ok(breezy::debug::debug_flag_enabled(flag))
}

#[pyfunction]
fn str_tdelta(delt: Option<f64>) -> PyResult<String> {
    Ok(breezy::progress::str_tdelta(delt))
}

#[pyfunction]
fn debug_memory_proc(message: &str, short: bool) {
    breezy::trace::debug_memory_proc(message, short)
}

#[pyfunction]
#[pyo3(signature = (location, scheme = None))]
fn rcp_location_to_url(location: &str, scheme: Option<&str>) -> PyResult<String> {
    let scheme = scheme.unwrap_or("ssh");
    breezy::location::rcp_location_to_url(location, scheme)
        .map_err(|e| PyValueError::new_err(format!("{:?}", e)))
        .map(|s| s.to_string())
}

#[pyfunction]
fn parse_cvs_location(location: &str) -> PyResult<(String, String, Option<String>, String)> {
    breezy::location::parse_cvs_location(location)
        .map_err(|e| PyValueError::new_err(format!("{:?}", e)))
}

#[pyfunction]
fn cvs_to_url(location: &str) -> PyResult<String> {
    breezy::location::cvs_to_url(location)
        .map_err(|e| PyValueError::new_err(format!("{:?}", e)))
        .map(|s| s.to_string())
}

#[pyfunction]
fn parse_rcp_location(location: &str) -> PyResult<(String, Option<String>, String)> {
    breezy::location::parse_rcp_location(location)
        .map_err(|e| PyValueError::new_err(format!("{:?}", e)))
}

#[pyfunction]
fn help_as_plain_text(text: &str) -> PyResult<String> {
    Ok(breezy::help::help_as_plain_text(text))
}

#[pyfunction]
#[pyo3(signature = (see_also = None))]
fn format_see_also(see_also: Option<Vec<String>>) -> PyResult<String> {
    let see_also = see_also
        .as_ref()
        .map(|x: &Vec<String>| x.iter().map(|s| s.as_str()).collect::<Vec<&str>>());
    if see_also.is_none() {
        return Ok("".to_string());
    }

    Ok(breezy::help::format_see_also(see_also.unwrap().as_slice()))
}

mod email_message;
mod help;
mod optparse;
mod registry;
mod utextwrap;

use optparse::{
    apply_verbosity, set_verbosity_level, split_revision_range, verbosity_level, PyOption,
    RegistryOption,
};
use registry::{
    calc_parent_name, get_named_object, registry_super, LazyObjectGetter, ObjectGetter, Registry,
};

#[pyclass]
struct TreeBuilder(breezy::treebuilder::TreeBuilder<PyTree>);

#[pymethods]
impl TreeBuilder {
    #[new]
    fn new() -> Self {
        TreeBuilder(breezy::treebuilder::TreeBuilder::new())
    }

    fn build(&mut self, recipe: Vec<String>) -> PyResult<()> {
        let recipe_ref = recipe.iter().map(|s| s.as_str()).collect::<Vec<&str>>();
        self.0
            .build(recipe_ref.as_slice())
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to build tree: {:?}", e)))
    }

    fn start_tree(&mut self, tree: Py<PyAny>) {
        let tree = PyTree::new(tree);
        self.0.start_tree(tree);
    }

    fn finish_tree(&mut self) {
        self.0.finish_tree();
    }
}

#[pyclass]
struct LockHeldInfo(breezy::lockdir::LockHeldInfo);

#[pymethods]
impl LockHeldInfo {
    #[classmethod]
    #[pyo3(signature = (extra_holder_info = None))]
    fn for_this_process(
        _cls: &Bound<PyType>,
        extra_holder_info: Option<std::collections::HashMap<String, String>>,
    ) -> Self {
        let mut extra_holder_info = extra_holder_info.unwrap_or_default();
        let pid = extra_holder_info
            .remove("pid")
            .map(|pid| pid.parse::<u32>().unwrap());
        let mut ret = breezy::lockdir::LockHeldInfo::for_this_process(extra_holder_info);

        if let Some(pid) = pid {
            ret.pid = Some(pid);
        }

        Self(ret)
    }

    fn to_readable_dict(&self) -> std::collections::HashMap<String, String> {
        self.0.to_readable_dict()
    }

    #[getter]
    fn nonce<'a>(&self, py: Python<'a>) -> Option<Bound<'a, PyBytes>> {
        self.0.nonce().map(|x| PyBytes::new(py, x))
    }

    #[getter]
    fn user(&self) -> Option<String> {
        self.0.user.clone()
    }

    #[setter]
    fn set_user(&mut self, user: Option<String>) {
        self.0.user = user;
    }

    #[getter]
    fn pid(&self) -> Option<u32> {
        self.0.pid
    }

    #[setter]
    fn set_pid(&mut self, pid: Option<u32>) {
        self.0.pid = pid;
    }

    #[getter]
    fn hostname(&self) -> Option<String> {
        self.0.hostname.clone()
    }

    #[setter]
    fn set_hostname(&mut self, hostname: Option<String>) {
        self.0.hostname = hostname;
    }

    fn to_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.0.to_bytes().as_slice())
    }

    fn __str__(&self) -> String {
        self.0.to_string()
    }

    fn __repr__(&self) -> String {
        format!("LockHeldInfo({:?})", self.0.to_readable_dict())
    }

    fn __richcmp__(&self, other: &LockHeldInfo, op: CompareOp) -> PyResult<bool> {
        match op {
            CompareOp::Eq => Ok(self.0 == other.0),
            CompareOp::Ne => Ok(self.0 != other.0),
            _ => Err(PyNotImplementedError::new_err(
                "Only == and != are supported",
            )),
        }
    }

    #[classmethod]
    fn from_info_file_bytes(
        _cls: &Bound<PyType>,
        py: Python,
        info_file_bytes: &[u8],
    ) -> PyResult<Self> {
        Ok(Self(
            breezy::lockdir::LockHeldInfo::from_info_file_bytes(info_file_bytes).map_err(|e| {
                let fb = PyBytes::new(py, info_file_bytes);

                match e {
                    breezy::lockdir::Error::LockCorrupt(s) => {
                        LockCorrupt::new_err((s, fb.unbind()))
                    }
                }
            })?,
        ))
    }

    fn is_locked_by_this_process(&self) -> bool {
        self.0.is_locked_by_this_process()
    }

    fn is_lock_holder_known_dead(&self) -> bool {
        self.0.is_lock_holder_known_dead()
    }
}

#[pyfunction]
fn remove_tags(
    branch: Py<PyAny>,
    graph: Py<PyAny>,
    old_tip: RevisionId,
    parents: Vec<RevisionId>,
) -> PyResult<Vec<String>> {
    breezy::uncommit::remove_tags(
        PyBranch::new(branch),
        &Graph::new(graph),
        old_tip,
        parents.as_slice(),
    )
    .map_err(|e| match e {
        breezy::tags::Error::NoSuchTag(n) => NoSuchTag::new_err(n),
        breezy::tags::Error::TagAlreadyExists(n) => TagAlreadyExists::new_err(n),
    })
}

#[pyfunction]
fn bugtracker_check_integer_bug_id(bug_id: &str) -> PyResult<()> {
    breezy::bugtracker::check_integer_bug_id(bug_id).map_err(map_bugtracker_error)
}

#[pyfunction]
fn bugtracker_check_project_integer_bug_id(bug_id: &str) -> PyResult<()> {
    breezy::bugtracker::check_project_integer_bug_id(bug_id).map_err(map_bugtracker_error)
}

#[pyfunction]
fn bugtracker_unique_integer_bug_url(base_url: &str, bug_id: &str) -> PyResult<String> {
    breezy::bugtracker::unique_integer_bug_url(base_url, bug_id).map_err(map_bugtracker_error)
}

#[pyfunction]
fn bugtracker_project_integer_bug_url(
    abbreviation: &str,
    base_url: &str,
    bug_id: &str,
) -> PyResult<String> {
    breezy::bugtracker::project_integer_bug_url(abbreviation, base_url, bug_id)
        .map_err(map_bugtracker_error)
}

#[pyfunction]
fn bugtracker_url_parametrized_integer_bug_url(
    base_url: &str,
    bug_area: &str,
    bug_id: &str,
) -> PyResult<String> {
    breezy::bugtracker::url_parametrized_integer_bug_url(base_url, bug_area, bug_id)
        .map_err(map_bugtracker_error)
}

#[pyfunction]
fn bugtracker_url_parametrized_bug_url(
    base_url: &str,
    bug_area: &str,
    bug_id: &str,
) -> PyResult<String> {
    breezy::bugtracker::url_parametrized_bug_url(base_url, bug_area, bug_id)
        .map_err(map_bugtracker_error)
}

#[pyfunction]
fn bugtracker_generic_bug_url(
    abbreviation: &str,
    base_url: &str,
    bug_id: &str,
) -> PyResult<String> {
    breezy::bugtracker::generic_bug_url(abbreviation, base_url, bug_id)
        .map_err(map_bugtracker_error)
}

#[pyfunction]
fn bugtracker_encode_fixes_bug_urls(bug_urls: Vec<(String, String)>) -> PyResult<String> {
    let refs: Vec<(&str, &str)> = bug_urls
        .iter()
        .map(|(u, t)| (u.as_str(), t.as_str()))
        .collect();
    breezy::bugtracker::encode_fixes_bug_urls(refs).map_err(map_bugtracker_error)
}

#[pyfunction]
fn bugtracker_decode_bug_urls(bug_lines: Vec<String>) -> PyResult<Vec<(String, String)>> {
    let refs: Vec<&str> = bug_lines.iter().map(|s| s.as_str()).collect();
    breezy::bugtracker::decode_bug_urls(refs).map_err(map_bugtracker_error)
}

/// Iterator that splits a command line into arguments.
///
/// This handles proper quoting and escaping of arguments on all platforms.
#[pyclass(module = "breezy._cmd_rs.cmdline")]
struct Splitter {
    inner: breezy::cmdline::Splitter,
}

#[pymethods]
impl Splitter {
    #[new]
    #[pyo3(signature = (command_line, single_quotes_allowed))]
    fn new(command_line: &str, single_quotes_allowed: bool) -> Self {
        Splitter {
            inner: breezy::cmdline::Splitter::new(command_line, single_quotes_allowed),
        }
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(mut slf: PyRefMut<'_, Self>) -> Option<(bool, String)> {
        slf.inner.next()
    }
}

/// Split a command line string into a list of arguments.
#[pyfunction]
#[pyo3(signature = (unsplit, single_quotes_allowed = true))]
fn split(unsplit: &str, single_quotes_allowed: bool) -> Vec<String> {
    breezy::cmdline::split(unsplit, single_quotes_allowed)
}

/// Compare two sequences of byte lines and return the unified diff lines.
///
/// Mirrors `breezy.diff.unified_diff_bytes` for the default (patience) matcher.
#[pyfunction]
#[pyo3(signature = (a, b, fromfile=Vec::new(), tofile=Vec::new(), fromfiledate=Vec::new(), tofiledate=Vec::new(), n=breezy::diff::DEFAULT_CONTEXT_AMOUNT, lineterm=vec![b'\n']))]
#[allow(clippy::too_many_arguments)]
fn unified_diff_bytes<'py>(
    py: Python<'py>,
    a: Vec<Vec<u8>>,
    b: Vec<Vec<u8>>,
    fromfile: Vec<u8>,
    tofile: Vec<u8>,
    fromfiledate: Vec<u8>,
    tofiledate: Vec<u8>,
    n: usize,
    lineterm: Vec<u8>,
) -> Vec<Bound<'py, PyBytes>> {
    let a_refs: Vec<&[u8]> = a.iter().map(|l| l.as_slice()).collect();
    let b_refs: Vec<&[u8]> = b.iter().map(|l| l.as_slice()).collect();
    breezy::diff::unified_diff_bytes(
        &a_refs,
        &b_refs,
        &fromfile,
        &tofile,
        &fromfiledate,
        &tofiledate,
        n,
        &lineterm,
    )
    .into_iter()
    .map(|line| PyBytes::new(py, &line))
    .collect()
}

/// Write a unified diff of two byte-line lists to a file-like object.
///
/// Implements the byte core of `breezy.diff.internal_diff`: the `/dev/null`
/// header workaround, the "No newline at end of file" marker, and the trailing
/// blank line. The binary check and label encoding stay on the Python side.
#[pyfunction]
#[pyo3(signature = (old_label, oldlines, new_label, newlines, to_file, context_lines=breezy::diff::DEFAULT_CONTEXT_AMOUNT))]
fn internal_diff(
    old_label: Vec<u8>,
    oldlines: Vec<Vec<u8>>,
    new_label: Vec<u8>,
    newlines: Vec<Vec<u8>>,
    to_file: Py<PyAny>,
    context_lines: usize,
) -> PyResult<()> {
    let old_refs: Vec<&[u8]> = oldlines.iter().map(|l| l.as_slice()).collect();
    let new_refs: Vec<&[u8]> = newlines.iter().map(|l| l.as_slice()).collect();
    let out =
        breezy::diff::internal_diff(&old_label, &old_refs, &new_label, &new_refs, context_lines);
    if let Some(out) = out {
        let mut writer = PyBinaryFile::from(to_file);
        writer.write_all(&out)?;
    }
    Ok(())
}

// A single hook point that clients register callbacks against.
//
// Its callbacks are a CallbackList; a hook point of a hooks object whose
// location is known takes over the callbacks installed lazily for it (see
// install_lazy_named_hook), so those installed later still reach it.
// Iterating yields the callables; the doc block is assembled by
// breezy::hooks::hookpoint_docs.
//
// NB: no `///` doc-comment here on purpose - a pyclass doc-comment becomes the
// class `__doc__`, which would shadow the per-instance `__doc__` getter below
// (HookPoint.__doc__ must return the hook's own doc string).
#[pyclass(name = "HookPoint", module = "breezy._cmd_rs.hooks", dict, subclass)]
struct PyHookPoint {
    #[pyo3(get)]
    name: String,
    #[pyo3(get)]
    introduced: Option<Py<PyAny>>,
    #[pyo3(get)]
    deprecated: Option<Py<PyAny>>,
    doc: String,
    callbacks: breezy::pyhooks::PyCallbackList,
    /// The lazily installed hook whose callbacks this hook point took over.
    #[pyo3(get)]
    lazy_key: Option<breezy::hooks::LazyHookKey>,
}

/// Format a version tuple via ``breezy._format_version_tuple``; `None` stays
/// `None`.
fn format_hook_version(py: Python<'_>, version: &Option<Py<PyAny>>) -> PyResult<Option<String>> {
    match version {
        Some(v) if !v.is_none(py) => Ok(Some(
            py.import("breezy")?
                .getattr("_format_version_tuple")?
                .call1((v.bind(py),))?
                .extract()?,
        )),
        _ => Ok(None),
    }
}

#[pymethods]
impl PyHookPoint {
    #[new]
    #[pyo3(signature = (name, doc, introduced, deprecated=None, lazy_key=None))]
    fn new(
        name: String,
        doc: String,
        introduced: Option<Py<PyAny>>,
        deprecated: Option<Py<PyAny>>,
        lazy_key: Option<breezy::hooks::LazyHookKey>,
    ) -> Self {
        let callbacks = match &lazy_key {
            Some(key) => breezy::pyhooks::lazy_hook_list(key),
            None => breezy::pyhooks::PyCallbackList::new(),
        };
        PyHookPoint {
            name,
            introduced,
            deprecated,
            doc,
            callbacks,
            lazy_key,
        }
    }

    /// Generate the documentation block for this hook point.
    fn docs(&self, py: Python<'_>) -> PyResult<String> {
        Ok(breezy::hooks::hookpoint_docs(
            &self.name,
            format_hook_version(py, &self.introduced)?.as_deref(),
            format_hook_version(py, &self.deprecated)?.as_deref(),
            &self.doc,
        ))
    }

    /// Register `callback` to fire when this hook point triggers. The label
    /// (shown in the UI) may be `None`.
    fn hook(&self, callback: Py<PyAny>, callback_label: Option<String>) {
        self.callbacks
            .push(breezy::hooks::Callback::Object(callback), callback_label);
    }

    /// Lazily register a callback, imported on first use when the hook fires.
    fn hook_lazy(
        &self,
        callback_module: String,
        callback_member: String,
        callback_label: Option<String>,
    ) {
        self.callbacks.push(
            breezy::hooks::Callback::Lazy {
                module: callback_module,
                member: callback_member,
            },
            callback_label,
        );
    }

    /// Remove the callbacks registered under `label`.
    fn uninstall(&self, label: Option<String>) -> PyResult<()> {
        self.callbacks
            .uninstall(label.as_deref())
            .map_err(|e| pyo3::exceptions::PyKeyError::new_err(e.to_string()))
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let objs = breezy::pyhooks::callables(py, &self.callbacks)?
            .into_iter()
            .map(|(obj, _)| obj)
            .collect::<Vec<_>>();
        Ok(objs.into_pyobject(py)?.call_method0("__iter__")?.unbind())
    }

    fn __len__(&self) -> usize {
        self.callbacks.len()
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        let callables = breezy::pyhooks::callables(py, &self.callbacks)?;
        let mut strings: Vec<String> = vec![
            "<HookPoint(".to_string(),
            self.name.clone(),
            "), callbacks=[".to_string(),
        ];
        for (obj, label) in &callables {
            strings.push(obj.bind(py).repr()?.extract()?);
            strings.push("(".to_string());
            strings.push(label.clone().unwrap_or_else(|| "None".to_string()));
            strings.push("),".to_string());
        }
        if callables.len() == 1 {
            let last = strings.len() - 1;
            strings[last] = ")".to_string();
        }
        strings.push("]>".to_string());
        Ok(strings.concat())
    }

    fn __richcmp__(
        &self,
        py: Python<'_>,
        other: &Bound<'_, PyAny>,
        op: CompareOp,
    ) -> PyResult<bool> {
        let other: PyRef<'_, PyHookPoint> = match other.extract() {
            Ok(o) => o,
            Err(_) => return Ok(matches!(op, CompareOp::Ne)),
        };
        // Callbacks are only equal when they are the same list, or both empty.
        let same_callbacks = self.callbacks.same_list(&other.callbacks)
            || (self.callbacks.is_empty() && other.callbacks.is_empty());
        let eq = self.name == other.name
            && self.doc == other.doc
            && version_eq(py, &self.introduced, &other.introduced)?
            && version_eq(py, &self.deprecated, &other.deprecated)?
            && same_callbacks;
        match op {
            CompareOp::Eq => Ok(eq),
            CompareOp::Ne => Ok(!eq),
            _ => Ok(false),
        }
    }
}

/// Install `a_callable` into hook `hook_name` of the hooks object `hookpoints_name`
/// in `hookpoints_module`, labelled `name`, without importing that module.
#[pyfunction]
fn install_lazy_named_hook(
    hookpoints_module: String,
    hookpoints_name: String,
    hook_name: String,
    a_callable: Py<PyAny>,
    name: Option<String>,
) {
    breezy::pyhooks::lazy_hook_list(&(hookpoints_module, hookpoints_name, hook_name))
        .push(breezy::hooks::Callback::Object(a_callable), name);
}

/// The ``(module, member, hook name)`` keys of the lazily installed hooks.
#[pyfunction]
fn lazy_hook_keys() -> Vec<breezy::hooks::LazyHookKey> {
    breezy::pyhooks::lazy_hook_keys()
}

/// A set of lazily installed hooks, put aside by [`swap_lazy_hooks`].
#[pyclass(name = "LazyHooks", module = "breezy._cmd_rs.hooks")]
struct PyLazyHooks(Option<breezy::hooks::LazyHooks<Py<PyAny>>>);

#[pymethods]
impl PyLazyHooks {
    /// The ``(module, member, hook name)`` keys of these hooks.
    fn keys(&self) -> PyResult<Vec<breezy::hooks::LazyHookKey>> {
        self.0
            .as_ref()
            .map(|hooks| hooks.keys().cloned().collect())
            .ok_or_else(|| {
                pyo3::exceptions::PyValueError::new_err("these lazy hooks were already restored")
            })
    }
}

/// Replace the lazily installed hooks with `hooks` (none if not given),
/// returning the ones replaced. The test framework uses this to isolate tests.
#[pyfunction]
#[pyo3(signature = (hooks=None))]
fn swap_lazy_hooks(hooks: Option<&Bound<'_, PyLazyHooks>>) -> PyResult<PyLazyHooks> {
    let replacement = match hooks {
        Some(hooks) => hooks.borrow_mut().0.take().ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err("these lazy hooks were already restored")
        })?,
        None => breezy::hooks::LazyHooks::new(),
    };
    Ok(PyLazyHooks(Some(breezy::pyhooks::replace_lazy_hooks(
        replacement,
    ))))
}

fn version_eq(py: Python<'_>, a: &Option<Py<PyAny>>, b: &Option<Py<PyAny>>) -> PyResult<bool> {
    match (a, b) {
        (None, None) => Ok(true),
        (Some(a), Some(b)) => a.bind(py).eq(b.bind(py)),
        _ => Ok(false),
    }
}

import_exception!(breezy.errors, DuplicateKey);
import_exception!(breezy.errors, UnsupportedOperation);
import_exception!(breezy.hooks, UnknownHook);

/// A dictionary mapping hook name to a list of callables (or HookPoints).
///
/// It is a mapping, backed by a ``dict``, that the per-subsystem hook classes
/// subclass and that plugins index. Values are stored as given: both plain
/// lists (old-style hooks) and HookPoints (new-style).
#[pyclass(
    name = "Hooks",
    module = "breezy._cmd_rs.hooks",
    mapping,
    subclass,
    dict
)]
struct Hooks {
    inner: Py<pyo3::types::PyDict>,
    callable_names: Py<pyo3::types::PyDict>,
    lazy_callable_names: Py<pyo3::types::PyDict>,
    module: Option<String>,
    member_name: Option<String>,
}

impl Hooks {
    fn class_name(slf: &Bound<'_, Self>) -> PyResult<String> {
        slf.get_type().getattr("__name__")?.extract()
    }

    /// Look up a hook (raising the framework's ``UnknownHook`` if absent).
    fn hook_named<'py>(slf: &Bound<'py, Self>, hook_name: &str) -> PyResult<Bound<'py, PyAny>> {
        let me = slf.borrow();
        match me.inner.bind(slf.py()).get_item(hook_name)? {
            Some(h) => Ok(h),
            None => Err(UnknownHook::new_err((
                Self::class_name(slf)?,
                hook_name.to_string(),
            ))),
        }
    }
}

#[pymethods]
impl Hooks {
    #[new]
    #[pyo3(signature = (module=None, member_name=None))]
    fn new(py: Python<'_>, module: Option<String>, member_name: Option<String>) -> Self {
        Hooks {
            inner: pyo3::types::PyDict::new(py).unbind(),
            callable_names: pyo3::types::PyDict::new(py).unbind(),
            lazy_callable_names: pyo3::types::PyDict::new(py).unbind(),
            module,
            member_name,
        }
    }

    // Subclasses call ``super().__init__(module, member_name)``; that reaches
    // here (a pyclass otherwise has no __init__, so the args would hit
    // object.__init__ and error). Record the module/member for lazy hooks.
    #[pyo3(signature = (module=None, member_name=None))]
    fn __init__(&mut self, module: Option<String>, member_name: Option<String>) {
        self.module = module;
        self.member_name = member_name;
    }

    #[getter]
    fn _module(&self) -> Option<String> {
        self.module.clone()
    }
    #[getter]
    fn _member_name(&self) -> Option<String> {
        self.member_name.clone()
    }
    #[getter]
    fn _callable_names(&self, py: Python<'_>) -> Py<pyo3::types::PyDict> {
        self.callable_names.clone_ref(py)
    }
    #[getter]
    fn _lazy_callable_names(&self, py: Python<'_>) -> Py<pyo3::types::PyDict> {
        self.lazy_callable_names.clone_ref(py)
    }

    // Mapping protocol delegated to the backing dict for exact semantics.
    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        match self.inner.bind(py).get_item(key)? {
            Some(v) => Ok(v.unbind()),
            None => Err(pyo3::exceptions::PyKeyError::new_err(key.clone().unbind())),
        }
    }
    fn __setitem__(
        &self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        self.inner.bind(py).set_item(key, value)
    }
    fn __delitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner.bind(py).del_item(key)
    }
    fn __contains__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.inner.bind(py).contains(key)
    }
    fn __len__(&self, py: Python<'_>) -> usize {
        self.inner.bind(py).len()
    }
    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(self.inner.bind(py).call_method0("__iter__")?.unbind())
    }
    fn __eq__(&self, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.inner.bind(py).as_any().eq(other)
    }
    #[pyo3(signature = (*args))]
    fn keys(&self, py: Python<'_>, args: &Bound<'_, PyTuple>) -> PyResult<Py<PyAny>> {
        Ok(self
            .inner
            .bind(py)
            .call_method("keys", args, None)?
            .unbind())
    }
    #[pyo3(signature = (*args))]
    fn values(&self, py: Python<'_>, args: &Bound<'_, PyTuple>) -> PyResult<Py<PyAny>> {
        Ok(self
            .inner
            .bind(py)
            .call_method("values", args, None)?
            .unbind())
    }
    #[pyo3(signature = (*args))]
    fn items(&self, py: Python<'_>, args: &Bound<'_, PyTuple>) -> PyResult<Py<PyAny>> {
        Ok(self
            .inner
            .bind(py)
            .call_method("items", args, None)?
            .unbind())
    }
    #[pyo3(signature = (*args))]
    fn get(&self, py: Python<'_>, args: &Bound<'_, PyTuple>) -> PyResult<Py<PyAny>> {
        Ok(self.inner.bind(py).call_method("get", args, None)?.unbind())
    }

    /// Add a hook point to this dictionary.
    #[pyo3(signature = (name, doc, introduced, deprecated=None))]
    fn add_hook(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        name: String,
        doc: Py<PyAny>,
        introduced: Py<PyAny>,
        deprecated: Option<Py<PyAny>>,
    ) -> PyResult<()> {
        let me = slf.borrow();
        if me.inner.bind(py).contains(&name)? {
            return Err(DuplicateKey::new_err(name));
        }
        // A hook point of hooks at a known location takes over the callbacks
        // installed lazily for it.
        let lazy_key = match (&me.module, &me.member_name) {
            (Some(module), Some(member)) => Some((module.clone(), member.clone(), name.clone())),
            _ => None,
        };
        let hookpoint = py.import("breezy.hooks")?.getattr("HookPoint")?.call1((
            name.clone(),
            doc,
            introduced,
            deprecated,
            lazy_key,
        ))?;
        me.inner.bind(py).set_item(name, hookpoint)?;
        Ok(())
    }

    /// The documentation of this hooks object: its class name and the
    /// documentation of each hook point, in name order.
    fn docs(slf: &Bound<'_, Self>) -> PyResult<String> {
        let py = slf.py();
        let inner = slf.borrow().inner.clone_ref(py);
        let names = py
            .import("builtins")?
            .call_method1("sorted", (inner.bind(py).keys(),))?;
        let docs = names
            .try_iter()?
            .map(|name| {
                let name = name?;
                inner
                    .bind(py)
                    .as_any()
                    .get_item(&name)?
                    .call_method0("docs")?
                    .extract()
            })
            .collect::<PyResult<Vec<String>>>()?;
        Ok(breezy::hooks::hooks_docs(&Self::class_name(slf)?, docs))
    }

    /// Display name for a registered callable.
    fn get_hook_name(&self, py: Python<'_>, a_callable: &Bound<'_, PyAny>) -> PyResult<String> {
        if let Some(name) = self.callable_names.bind(py).get_item(a_callable)? {
            if !name.is_none() {
                return name.extract();
            }
        }
        if !a_callable.is_none() {
            let key = (
                a_callable.getattr("__module__")?,
                a_callable.getattr("__name__")?,
            );
            if let Some(name) = self.lazy_callable_names.bind(py).get_item(key)? {
                if !name.is_none() {
                    return name.extract();
                }
            }
        }
        Ok("No hook name".to_string())
    }

    /// Install `a_callable` into hook `hook_name`, labelled `name`.
    #[pyo3(signature = (hook_name, a_callable, name))]
    fn install_named_hook(
        slf: &Bound<'_, Self>,
        hook_name: &str,
        a_callable: Py<PyAny>,
        name: Py<PyAny>,
    ) -> PyResult<()> {
        let py = slf.py();
        let hook = Self::hook_named(slf, hook_name)?;
        // List hooks (old-style) just append; HookPoints use .hook().
        match hook.call_method1("append", (a_callable.clone_ref(py),)) {
            Ok(_) => {}
            Err(e) if e.is_instance_of::<pyo3::exceptions::PyAttributeError>(py) => {
                hook.call_method1("hook", (a_callable.clone_ref(py), name.clone_ref(py)))?;
            }
            Err(e) => return Err(e),
        }
        if !name.bind(py).is_none() {
            slf.borrow()
                .name_hook(py, a_callable.bind(py), name.bind(py))?;
        }
        Ok(())
    }

    /// Install a lazily-imported callable into a hook.
    #[pyo3(signature = (hook_name, callable_module, callable_member, name))]
    fn install_named_hook_lazy(
        slf: &Bound<'_, Self>,
        hook_name: &str,
        callable_module: String,
        callable_member: String,
        name: Py<PyAny>,
    ) -> PyResult<()> {
        let py = slf.py();
        let hook = Self::hook_named(slf, hook_name)?;
        let hook_lazy = match hook.getattr("hook_lazy") {
            Ok(hook_lazy) => hook_lazy,
            Err(e) if e.is_instance_of::<pyo3::exceptions::PyAttributeError>(py) => {
                return Err(UnsupportedOperation::new_err((
                    slf.getattr("install_named_hook_lazy")?.unbind(),
                    slf.clone().unbind(),
                )));
            }
            Err(e) => return Err(e),
        };
        hook_lazy.call1((
            callable_module.clone(),
            callable_member.clone(),
            name.clone_ref(py),
        ))?;
        if !name.bind(py).is_none() {
            slf.borrow().name_hook_lazy(
                py,
                callable_module,
                callable_member,
                name.bind(py).str()?.extract()?,
            )?;
        }
        Ok(())
    }

    /// Uninstall callables labelled `label` from `hook_name`.
    fn uninstall_named_hook(
        slf: &Bound<'_, Self>,
        hook_name: &str,
        label: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let hook = Self::hook_named(slf, hook_name)?;
        let uninstall = match hook.getattr("uninstall") {
            Ok(uninstall) => uninstall,
            Err(e) if e.is_instance_of::<pyo3::exceptions::PyAttributeError>(slf.py()) => {
                return Err(UnsupportedOperation::new_err((
                    slf.getattr("uninstall_named_hook")?.unbind(),
                    slf.clone().unbind(),
                )));
            }
            Err(e) => return Err(e),
        };
        uninstall.call1((label,))?;
        Ok(())
    }

    /// Associate `name` with `a_callable`.
    fn name_hook(
        &self,
        py: Python<'_>,
        a_callable: &Bound<'_, PyAny>,
        name: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        self.callable_names.bind(py).set_item(a_callable, name)
    }

    /// Associate a name with a lazily-loaded callable.
    fn name_hook_lazy(
        &self,
        py: Python<'_>,
        callable_module: String,
        callable_member: String,
        callable_name: String,
    ) -> PyResult<()> {
        self.lazy_callable_names
            .bind(py)
            .set_item((callable_module, callable_member), callable_name)
    }
}

/// A [`Registry`] specialised for formats.
///
/// Registrations may be mirrored into a second registry, so one call can
/// populate both. ``get`` calls a registered factory, returning the format
/// itself rather than the callable.
#[pyclass(name = "FormatRegistry", module = "breezy._cmd_rs.registry", extends = Registry, subclass)]
struct FormatRegistry {
    other_registry: Option<Py<PyAny>>,
}

impl FormatRegistry {
    /// Mirror a call into the other registry, if there is one.
    fn mirror(
        slf: &Bound<'_, Self>,
        method: &str,
        args: &Bound<'_, PyTuple>,
        kwargs: &Bound<'_, pyo3::types::PyDict>,
    ) -> PyResult<()> {
        let py = slf.py();
        let other = slf
            .borrow()
            .other_registry
            .as_ref()
            .map(|o| o.clone_ref(py));
        if let Some(other) = other {
            other.bind(py).call_method(method, args, Some(kwargs))?;
        }
        Ok(())
    }
}

#[pymethods]
impl FormatRegistry {
    #[new]
    #[pyo3(signature = (other_registry=None))]
    fn new(py: Python<'_>, other_registry: Option<Py<PyAny>>) -> PyClassInitializer<Self> {
        PyClassInitializer::from(Registry::new(py, &PyTuple::empty(py), None)).add_subclass(
            FormatRegistry {
                other_registry: other_registry.filter(|o| !o.is_none(py)),
            },
        )
    }

    #[pyo3(signature = (other_registry=None))]
    fn __init__(slf: &Bound<'_, Self>, other_registry: Option<Py<PyAny>>) -> PyResult<()> {
        let py = slf.py();
        registry_super(slf.as_any(), "__init__", &PyTuple::empty(py), None)?;
        slf.borrow_mut().other_registry = other_registry.filter(|o| !o.is_none(py));
        Ok(())
    }

    /// Register a format, mirroring the registration if a second registry was
    /// given.
    #[pyo3(signature = (key, obj, help=None, info=None, override_existing=false))]
    fn register(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        key: Py<PyAny>,
        obj: Py<PyAny>,
        help: Option<Py<PyAny>>,
        info: Option<Py<PyAny>>,
        override_existing: bool,
    ) -> PyResult<()> {
        let kwargs = pyo3::types::PyDict::new(py);
        kwargs.set_item("help", &help)?;
        kwargs.set_item("info", &info)?;
        kwargs.set_item("override_existing", override_existing)?;
        let args = PyTuple::new(py, [&key, &obj])?;
        registry_super(slf.as_any(), "register", &args, Some(&kwargs))?;
        Self::mirror(slf, "register", &args, &kwargs)
    }

    /// Register a format to be imported on first access, mirroring it too.
    #[pyo3(signature = (key, module_name, member_name, help=None, info=None, override_existing=false))]
    #[allow(clippy::too_many_arguments)]
    fn register_lazy(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        key: Py<PyAny>,
        module_name: Py<PyAny>,
        member_name: Py<PyAny>,
        help: Option<Py<PyAny>>,
        info: Option<Py<PyAny>>,
        override_existing: bool,
    ) -> PyResult<()> {
        let kwargs = pyo3::types::PyDict::new(py);
        kwargs.set_item("help", &help)?;
        kwargs.set_item("info", &info)?;
        kwargs.set_item("override_existing", override_existing)?;
        let args = PyTuple::new(py, [&key, &module_name, &member_name])?;
        registry_super(slf.as_any(), "register_lazy", &args, Some(&kwargs))?;
        Self::mirror(slf, "register_lazy", &args, &kwargs)
    }

    /// Remove a format, removing it from the other registry too.
    fn remove(slf: &Bound<'_, Self>, py: Python<'_>, key: Py<PyAny>) -> PyResult<()> {
        let args = PyTuple::new(py, [&key])?;
        registry_super(slf.as_any(), "remove", &args, None)?;
        Self::mirror(slf, "remove", &args, &pyo3::types::PyDict::new(py))
    }

    /// Get a format, calling it if the registered object is a factory.
    fn get(slf: &Bound<'_, Self>, format_string: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let py = slf.py();
        let args = PyTuple::new(py, [format_string])?;
        let r = registry_super(slf.as_any(), "get", &args, None)?;
        if r.is_callable() {
            return Ok(r.call0()?.unbind());
        }
        Ok(r.unbind())
    }
}

/// Register the builtin hook points into `registry`.
#[pyfunction]
fn register_known_hooks(registry: &Bound<'_, PyAny>) -> PyResult<()> {
    for def in breezy::hooks::builtin_known_hooks() {
        registry.call_method1("register_lazy_hook", (def.module, def.member, def.factory))?;
    }
    Ok(())
}

/// Registry of all known hook points in breezy.
///
/// Keys are ``(module_name, member_name)`` tuples naming a hook point; each
/// maps lazily to the factory that builds that point's empty ``Hooks``.
#[pyclass(name = "KnownHooksRegistry", module = "breezy._cmd_rs.hooks", extends = Registry, subclass)]
struct KnownHooksRegistry;

#[pymethods]
impl KnownHooksRegistry {
    #[new]
    fn new(py: Python<'_>) -> PyClassInitializer<Self> {
        PyClassInitializer::from(Registry::new(py, &PyTuple::empty(py), None))
            .add_subclass(KnownHooksRegistry)
    }

    /// Register a hook point lazily, to avoid circular imports.
    fn register_lazy_hook(
        slf: &Bound<'_, Self>,
        hook_module_name: String,
        hook_member_name: String,
        hook_factory_member_name: String,
    ) -> PyResult<()> {
        let key = (hook_module_name.clone(), hook_member_name);
        slf.as_any().call_method1(
            "register_lazy",
            (key, hook_module_name, hook_factory_member_name),
        )?;
        Ok(())
    }

    /// Yield ``(hook_key, (parent_object, attr))`` for every registered hook.
    ///
    /// Used to reset and restore every hook to a known state, as the test
    /// harness does in ``TestCase._clear_hooks``.
    fn iter_parent_objects(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let out = pyo3::types::PyList::empty(py);
        for key in slf.as_any().call_method0("keys")?.try_iter()? {
            let key = key?;
            let pair = Self::key_to_parent_and_attribute(slf, &key)?;
            out.append((key, pair))?;
        }
        Ok(out.into_any().unbind())
    }

    /// Resolve a known-hooks key to the ``(parent_object, attr)`` pair holding
    /// that hook.
    fn key_to_parent_and_attribute(
        slf: &Bound<'_, Self>,
        key: &Bound<'_, PyAny>,
    ) -> PyResult<(Py<PyAny>, String)> {
        let py = slf.py();
        let (module, member): (String, Option<String>) = key.extract()?;
        let (parent_mod, parent_member, attr) = calc_parent_name(&module, member.as_deref())?;
        let parent = get_named_object(py, &parent_mod, parent_member.as_deref())?;
        Ok((parent, attr))
    }
}

#[pymodule]
fn _cmd_rs(py: Python, m: &Bound<PyModule>) -> PyResult<()> {
    // Route Rust `log` records to Python's `logging` module so that fixtures
    // like the test suite's `breezy.trace.push_log_file` see them. Without
    // this, Rust code that hits `log::warn!` etc. (or that fell back to
    // `eprintln!` for things like "failed to open trace file") would bypass
    // every Python-side handler and leak to the real stderr.
    //
    // `try_init` is used so re-imports of this extension module don't panic.
    let _ = pyo3_log::try_init();

    let i18n = PyModule::new(py, "i18n")?;
    i18n.add_function(wrap_pyfunction!(i18n_install, &i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_install_plugin, &i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_gettext, &i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_ngettext, &i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_disable_i18n, &i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_dgettext, &i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_gettext_per_paragraph, &i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_install_zzz, &i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_install_zzz_for_doc, &i18n)?)?;
    i18n.add_function(wrap_pyfunction!(i18n_zzz, &i18n)?)?;
    m.add_submodule(&i18n)?;
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
    m.add_function(wrap_pyfunction!(set_debug_flag, m)?)?;
    m.add_function(wrap_pyfunction!(unset_debug_flag, m)?)?;
    m.add_function(wrap_pyfunction!(clear_debug_flags, m)?)?;
    m.add_function(wrap_pyfunction!(get_debug_flags, m)?)?;
    m.add_function(wrap_pyfunction!(debug_flag_enabled, m)?)?;
    m.add_function(wrap_pyfunction!(str_tdelta, m)?)?;
    m.add_function(wrap_pyfunction!(debug_memory_proc, m)?)?;
    m.add_function(wrap_pyfunction!(rcp_location_to_url, m)?)?;
    m.add_function(wrap_pyfunction!(parse_cvs_location, m)?)?;
    m.add_function(wrap_pyfunction!(cvs_to_url, m)?)?;
    m.add_function(wrap_pyfunction!(parse_rcp_location, m)?)?;
    m.add_function(wrap_pyfunction!(help_as_plain_text, m)?)?;
    m.add_function(wrap_pyfunction!(format_see_also, m)?)?;
    m.add_function(wrap_pyfunction!(bugtracker_check_integer_bug_id, m)?)?;
    m.add_function(wrap_pyfunction!(
        bugtracker_check_project_integer_bug_id,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(bugtracker_unique_integer_bug_url, m)?)?;
    m.add_function(wrap_pyfunction!(bugtracker_project_integer_bug_url, m)?)?;
    m.add_function(wrap_pyfunction!(
        bugtracker_url_parametrized_integer_bug_url,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(bugtracker_url_parametrized_bug_url, m)?)?;
    m.add_function(wrap_pyfunction!(bugtracker_generic_bug_url, m)?)?;
    m.add_function(wrap_pyfunction!(bugtracker_encode_fixes_bug_urls, m)?)?;
    m.add_function(wrap_pyfunction!(bugtracker_decode_bug_urls, m)?)?;
    m.add_class::<LockHeldInfo>()?;

    let helpm = PyModule::new(py, "help")?;
    help::help_topics(&helpm)?;
    m.add_submodule(&helpm)?;

    let uncommitm = PyModule::new(py, "uncommit")?;
    uncommitm.add_function(wrap_pyfunction!(remove_tags, &uncommitm)?)?;
    m.add_submodule(&uncommitm)?;

    let cmdlinem = PyModule::new(py, "cmdline")?;
    cmdlinem.add_class::<Splitter>()?;
    cmdlinem.add_function(wrap_pyfunction!(split, &cmdlinem)?)?;
    m.add_submodule(&cmdlinem)?;

    m.add_class::<TreeBuilder>()?;

    let optparsem = PyModule::new(py, "optparse")?;
    optparsem.add_function(wrap_pyfunction!(verbosity_level, &optparsem)?)?;
    optparsem.add_function(wrap_pyfunction!(set_verbosity_level, &optparsem)?)?;
    optparsem.add_function(wrap_pyfunction!(apply_verbosity, &optparsem)?)?;
    optparsem.add_function(wrap_pyfunction!(split_revision_range, &optparsem)?)?;
    optparsem.add_class::<optparse::Parser>()?;
    optparsem.add_class::<PyOption>()?;
    optparsem.add_class::<RegistryOption>()?;
    m.add_submodule(&optparsem)?;

    let hooksm = PyModule::new(py, "hooks")?;
    hooksm.add_class::<PyHookPoint>()?;
    hooksm.add_class::<Hooks>()?;
    hooksm.add_class::<KnownHooksRegistry>()?;
    hooksm.add_function(wrap_pyfunction!(register_known_hooks, &hooksm)?)?;
    hooksm.add_function(wrap_pyfunction!(install_lazy_named_hook, &hooksm)?)?;
    hooksm.add_function(wrap_pyfunction!(lazy_hook_keys, &hooksm)?)?;
    hooksm.add_function(wrap_pyfunction!(swap_lazy_hooks, &hooksm)?)?;
    hooksm.add_class::<PyLazyHooks>()?;
    m.add_submodule(&hooksm)?;

    let registrym = PyModule::new(py, "registry")?;
    registrym.add_class::<Registry>()?;
    registrym.add_class::<FormatRegistry>()?;
    registrym.add_class::<ObjectGetter>()?;
    registrym.add_class::<LazyObjectGetter>()?;
    m.add_submodule(&registrym)?;

    let pyutilsm = PyModule::new(py, "pyutils")?;
    pyutilsm.add_function(wrap_pyfunction!(get_named_object, &pyutilsm)?)?;
    pyutilsm.add_function(wrap_pyfunction!(calc_parent_name, &pyutilsm)?)?;
    m.add_submodule(&pyutilsm)?;

    let diffm = PyModule::new(py, "diff")?;
    diffm.add_function(wrap_pyfunction!(unified_diff_bytes, &diffm)?)?;
    diffm.add_function(wrap_pyfunction!(internal_diff, &diffm)?)?;
    m.add_submodule(&diffm)?;

    let utextwrapm = PyModule::new(py, "utextwrap")?;
    utextwrap::utextwrap(&utextwrapm)?;
    m.add_submodule(&utextwrapm)?;

    let email_messagem = PyModule::new(py, "email_message")?;
    email_message::email_message(&email_messagem)?;
    m.add_submodule(&email_messagem)?;

    // PyO3 submodule hack for proper import support
    let sys = py.import("sys")?;
    let modules = sys.getattr("modules")?;
    let module_name = m.name()?;

    // Register submodules in sys.modules for dotted import support
    modules.set_item(format!("{}.i18n", module_name), &i18n)?;
    modules.set_item(format!("{}.help", module_name), &helpm)?;
    modules.set_item(format!("{}.uncommit", module_name), &uncommitm)?;
    modules.set_item(format!("{}.cmdline", module_name), &cmdlinem)?;
    modules.set_item(format!("{}.diff", module_name), &diffm)?;
    modules.set_item(format!("{}.utextwrap", module_name), &utextwrapm)?;
    modules.set_item(format!("{}.email_message", module_name), &email_messagem)?;
    modules.set_item(format!("{}.optparse", module_name), &optparsem)?;
    modules.set_item(format!("{}.hooks", module_name), &hooksm)?;
    modules.set_item(format!("{}.registry", module_name), &registrym)?;
    modules.set_item(format!("{}.pyutils", module_name), &pyutilsm)?;

    Ok(())
}
