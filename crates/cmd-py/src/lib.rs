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

mod help;

use breezy::command::Command as _;
use breezy::pycommand::PyCommand;

/// A Rust view onto a Python `Command` object.
///
/// This wraps a Python command in the Rust [`PyCommand`] and exposes the
/// [`breezy::command::Command`] trait methods back to Python. It exists so the
/// Rust command trait can be exercised against the real Python command classes
/// while the infrastructure is migrated; it is not yet used by the command
/// dispatch path.
#[pyclass(name = "PyCommand")]
struct PyCommandWrapper(PyCommand);

#[pymethods]
impl PyCommandWrapper {
    #[new]
    fn new(command: Py<PyAny>) -> Self {
        PyCommandWrapper(PyCommand::new(command))
    }

    fn name(&self) -> String {
        self.0.name()
    }

    fn aliases(&self) -> Vec<String> {
        self.0.aliases()
    }

    fn takes_args(&self) -> Vec<String> {
        self.0.takes_args()
    }

    fn hidden(&self) -> bool {
        self.0.hidden()
    }

    fn encoding_type(&self) -> String {
        self.0.encoding_type()
    }

    fn invoked_as(&self) -> Option<String> {
        self.0.invoked_as()
    }

    fn plugin_name(&self) -> Option<String> {
        self.0.plugin_name()
    }

    fn help(&self) -> Option<String> {
        self.0.help()
    }
}

import_exception!(breezy.errors, CommandError);

/// Translate `template` via ``breezy.i18n.gettext`` and format it with `args`.
///
/// This mirrors the Python ``i18n.gettext(template).format(...)`` calls so the
/// ``{0!r}`` repr-conversions and the active translation are byte-identical to
/// the original implementation.
fn gettext_format(py: Python<'_>, template: &str, args: (String, String)) -> PyResult<String> {
    let i18n = py.import("breezy.i18n")?;
    let translated = i18n.call_method1("gettext", (template,))?;
    translated.call_method1("format", args)?.extract::<String>()
}

fn arg_match_error_to_py(py: Python<'_>, err: breezy::command::ArgMatchError) -> PyErr {
    use breezy::command::ArgMatchError;
    let msg = match err {
        ArgMatchError::NeedsOneOrMore { cmd, argname } => {
            gettext_format(py, "command {0!r} needs one or more {1}", (cmd, argname))
        }
        ArgMatchError::RequiresArgument { cmd, argname } => {
            gettext_format(py, "command {0!r} requires argument {1}", (cmd, argname))
        }
        ArgMatchError::ExtraArgument { cmd, extra } => {
            gettext_format(py, "extra argument to command {0}: {1}", (cmd, extra))
        }
    };
    match msg {
        Ok(msg) => CommandError::new_err(msg),
        Err(e) => e,
    }
}

/// Match positional arguments against a command's ``takes_args`` specification.
///
/// A port of the Python ``breezy.commands._match_argform``. Returns a dict
/// mapping parameter names to their bound values (a string, a list, or `None`
/// for an empty ``*`` match), preserving the declaration order of `takes_args`.
#[pyfunction]
fn match_argform<'py>(
    py: Python<'py>,
    cmd: &str,
    takes_args: Vec<String>,
    args: Vec<String>,
) -> PyResult<Bound<'py, pyo3::types::PyDict>> {
    use breezy::command::ArgValue;
    let matched = breezy::command::match_argform(cmd, &takes_args, args)
        .map_err(|e| arg_match_error_to_py(py, e))?;
    let dict = pyo3::types::PyDict::new(py);
    for (key, value) in matched {
        match value {
            ArgValue::Scalar(s) => dict.set_item(key, s)?,
            ArgValue::List(None) => dict.set_item(key, py.None())?,
            ArgValue::List(Some(items)) => dict.set_item(key, items)?,
        }
    }
    Ok(dict)
}

/// Convert a squished class name (``cmd_foo_bar``) to a command name (``foo-bar``).
#[pyfunction]
fn unsquish_command_name(name: &str) -> String {
    breezy::command::unsquish_command_name(name)
}

/// Convert a command name (``foo-bar``) to a squished class name (``cmd_foo_bar``).
#[pyfunction]
fn squish_command_name(name: &str) -> String {
    breezy::command::squish_command_name(name)
}

/// Build a command's single-line usage grammar from its name and ``takes_args``.
#[pyfunction]
fn usage(name: &str, takes_args: Vec<String>) -> String {
    breezy::command::usage(name, &takes_args)
}

/// Split help text into ``(summary, sections, order)``.
///
/// `sections` is a dict keyed by section label (with `None` for the default
/// section) and `order` is the list of labels in first-appearance order,
/// matching the Python ``Command._get_help_parts`` return value.
#[pyfunction]
fn get_help_parts<'py>(
    py: Python<'py>,
    text: &str,
) -> PyResult<(
    String,
    Bound<'py, pyo3::types::PyDict>,
    Bound<'py, pyo3::types::PyList>,
)> {
    let (summary, ordered) = breezy::command::split_help_parts(text);
    let sections = pyo3::types::PyDict::new(py);
    let order = pyo3::types::PyList::empty(py);
    for (label, body) in ordered {
        let key = match label {
            Some(ref s) => s.into_pyobject(py)?.into_any(),
            None => py.None().into_bound(py),
        };
        sections.set_item(&key, body)?;
        order.append(&key)?;
    }
    Ok((summary, sections, order))
}

/// Guess which command was meant, scoring `candidates` against `cmd_name`.
///
/// `candidates` is the set of known command names and aliases; `overrides` are
/// the hard-coded ``(name, cost)`` pairs for `cmd_name`. Returns the closest
/// candidate, or `None` if nothing scores within the cutoff.
#[pyfunction]
#[pyo3(signature = (cmd_name, candidates, overrides))]
fn guess_command(
    cmd_name: &str,
    candidates: Vec<String>,
    overrides: Vec<(String, f64)>,
) -> Option<String> {
    breezy::command::guess_command(cmd_name, &candidates, &overrides)
}

/// The master options parsed from the front of a ``brz`` command line.
///
/// Exposes the parsed flags to Python as read-only attributes; the caller
/// applies the side effects (debug flags, ``BRZ_CONCURRENCY``, config overrides).
#[pyclass(name = "MasterOptions", frozen)]
struct PyMasterOptions(breezy::command::MasterOptions);

#[pymethods]
impl PyMasterOptions {
    #[getter]
    fn lsprof(&self) -> bool {
        self.0.lsprof
    }
    #[getter]
    fn profile(&self) -> bool {
        self.0.profile
    }
    #[getter]
    fn no_plugins(&self) -> bool {
        self.0.no_plugins
    }
    #[getter]
    fn no_aliases(&self) -> bool {
        self.0.no_aliases
    }
    #[getter]
    fn no_l10n(&self) -> bool {
        self.0.no_l10n
    }
    #[getter]
    fn builtin(&self) -> bool {
        self.0.builtin
    }
    #[getter]
    fn coverage(&self) -> bool {
        self.0.coverage
    }
    #[getter]
    fn lsprof_file(&self) -> Option<String> {
        self.0.lsprof_file.clone()
    }
    #[getter]
    fn concurrency(&self) -> Option<String> {
        self.0.concurrency.clone()
    }
    #[getter]
    fn debug_flags(&self) -> Vec<String> {
        self.0.debug_flags.clone()
    }
    #[getter]
    fn config_overrides(&self) -> Vec<String> {
        self.0.config_overrides.clone()
    }
}

/// Scan and strip the master options from the front of `argv`.
///
/// Returns ``(MasterOptions, remaining_argv)``. Raises ``IndexError`` if
/// ``--lsprof-file`` or ``--concurrency`` is given without a following
/// argument, matching the Python behaviour.
#[pyfunction]
fn scan_master_options(argv: Vec<String>) -> PyResult<(PyMasterOptions, Vec<String>)> {
    let (opts, remaining) = breezy::command::scan_master_options(argv).map_err(|e| {
        pyo3::exceptions::PyIndexError::new_err(format!("missing argument for {}", e.option))
    })?;
    Ok((PyMasterOptions(opts), remaining))
}

/// Drive a single ``brz`` invocation.
///
/// `argv` is the raw argument vector (master options included); `ctx` is a
/// Python object providing the side-effecting operations as methods. Returns
/// the command's exit code.
#[pyfunction]
fn run_bzr(argv: Vec<String>, ctx: &Bound<'_, PyAny>) -> PyResult<i32> {
    breezy::pycommand::run_bzr(argv, ctx)
}

/// Run the native Rust ``rocks`` command, writing its message to `outf`.
///
/// The message is translated through ``breezy.i18n.gettext`` (matching the
/// original Python command) and written to the supplied output stream.
#[pyfunction]
fn run_rocks(py: Python<'_>, outf: &Bound<'_, PyAny>) -> PyResult<()> {
    let message = breezy::command::CmdRocks::message();
    let translated = py
        .import("breezy.i18n")?
        .call_method1("gettext", (message,))?;
    outf.call_method1("write", (translated,))?;
    Ok(())
}

/// A single parsed option or argument token returned by ``tokenize_options``.
///
/// ``is_option`` distinguishes the two cases. For an option, ``key``,
/// ``opt_str`` and ``flag_value`` are set and ``value`` holds the argument (or
/// ``None`` for a flag). For an argument, only ``value`` is set (the positional
/// text) and ``is_option`` is ``False``.
#[pyclass(name = "OptionToken", frozen, get_all)]
struct PyOptionToken {
    is_option: bool,
    key: Option<String>,
    opt_str: Option<String>,
    value: Option<String>,
    flag_value: bool,
}

/// Tokenize `argv` against the option `specs`.
///
/// Each spec is a tuple ``(key, long, short, negation, takes_value)`` where
/// `short` and `negation` may be ``None``. Returns a list of ``OptionToken``.
/// Raises ``breezy.errors.CommandError`` with optparse-compatible wording on an
/// unknown option, a missing argument or an ambiguous abbreviation.
#[pyfunction]
fn tokenize_options(
    specs: Vec<(String, String, Option<char>, Option<String>, bool)>,
    argv: Vec<String>,
) -> PyResult<Vec<PyOptionToken>> {
    use breezy::optparse::{OptionKind, OptionSpec, Spec, Token};
    let options = specs
        .into_iter()
        .map(|(key, long, short, negation, takes_value)| OptionSpec {
            key,
            long,
            short,
            negation,
            kind: if takes_value {
                OptionKind::Value
            } else {
                OptionKind::Flag
            },
        })
        .collect();
    let spec = Spec::from_options(options);
    let tokens = breezy::optparse::tokenize(&spec, argv)
        .map_err(|e| CommandError::new_err(e.to_string()))?;
    Ok(tokens
        .into_iter()
        .map(|token| match token {
            Token::Option {
                key,
                opt_str,
                value,
                flag_value,
            } => PyOptionToken {
                is_option: true,
                key: Some(key),
                opt_str: Some(opt_str),
                value,
                flag_value,
            },
            Token::Argument(arg) => PyOptionToken {
                is_option: false,
                key: None,
                opt_str: None,
                value: Some(arg),
                flag_value: false,
            },
        })
        .collect())
}

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
    m.add_class::<LockHeldInfo>()?;

    let helpm = PyModule::new(py, "help")?;
    help::help_topics(&helpm)?;
    m.add_submodule(&helpm)?;

    let uncommitm = PyModule::new(py, "uncommit")?;
    uncommitm.add_function(wrap_pyfunction!(remove_tags, &uncommitm)?)?;
    m.add_submodule(&uncommitm)?;

    let commandsm = PyModule::new(py, "commands")?;
    commandsm.add_class::<PyCommandWrapper>()?;
    commandsm.add_function(wrap_pyfunction!(match_argform, &commandsm)?)?;
    commandsm.add_function(wrap_pyfunction!(unsquish_command_name, &commandsm)?)?;
    commandsm.add_function(wrap_pyfunction!(squish_command_name, &commandsm)?)?;
    commandsm.add_function(wrap_pyfunction!(usage, &commandsm)?)?;
    commandsm.add_function(wrap_pyfunction!(get_help_parts, &commandsm)?)?;
    commandsm.add_function(wrap_pyfunction!(guess_command, &commandsm)?)?;
    commandsm.add_function(wrap_pyfunction!(scan_master_options, &commandsm)?)?;
    commandsm.add_function(wrap_pyfunction!(run_bzr, &commandsm)?)?;
    commandsm.add_function(wrap_pyfunction!(run_rocks, &commandsm)?)?;
    commandsm.add_class::<PyMasterOptions>()?;
    m.add_submodule(&commandsm)?;

    let optparsem = PyModule::new(py, "optparse")?;
    optparsem.add_function(wrap_pyfunction!(tokenize_options, &optparsem)?)?;
    optparsem.add_class::<PyOptionToken>()?;
    m.add_submodule(&optparsem)?;

    m.add_class::<TreeBuilder>()?;

    // PyO3 submodule hack for proper import support
    let sys = py.import("sys")?;
    let modules = sys.getattr("modules")?;
    let module_name = m.name()?;

    // Register submodules in sys.modules for dotted import support
    modules.set_item(format!("{}.i18n", module_name), &i18n)?;
    modules.set_item(format!("{}.help", module_name), &helpm)?;
    modules.set_item(format!("{}.uncommit", module_name), &uncommitm)?;
    modules.set_item(format!("{}.commands", module_name), &commandsm)?;
    modules.set_item(format!("{}.optparse", module_name), &optparsem)?;

    Ok(())
}
