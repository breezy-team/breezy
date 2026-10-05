//! Python bindings for the command machinery.
//!
//! These expose the command base class and its lifecycle, the command and
//! provider registries, command lookup and enumeration, argument parsing and
//! help assembly, and the entry points the `brz` binary and `python3 -m breezy`
//! both run through. The logic they drive lives in the library
//! (`breezy::command`, `breezy::commands`, `breezy::pycommand`); these are the
//! bindings that let the Python command objects take part in it.

use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyTuple;

use crate::registry::{registry_super, Registry};
use breezy::pyregistry::SharedTable;

import_exception!(breezy.errors, CommandError);

/// The run-method wrapper installed by `Command._setup_run`.
///
/// `_setup_run` replaces `self.run` with an instance of this callable, capturing
/// the command and the unwrapped class `run`. Calling it fires the `pre_command`
/// hooks, runs the captured `run` inside a `contextlib.ExitStack` stored as
/// `self._exit_stack` (so `add_cleanup`/`enter_context` work), then fires the
/// `post_command` hooks in a `finally`.
#[pyclass(name = "_RunWrapper", module = "breezy._cmd_rs.commands")]
pub(crate) struct RunWrapper {
    // The command refers back to this wrapper, so the references are exposed
    // to the garbage collector; `None` once it has cleared them.
    command: Option<Py<PyAny>>,
    class_run: Option<Py<PyAny>>,
}

#[pymethods]
impl RunWrapper {
    fn __traverse__(&self, visit: pyo3::PyVisit<'_>) -> Result<(), pyo3::PyTraverseError> {
        if let Some(command) = &self.command {
            visit.call(command)?;
        }
        if let Some(class_run) = &self.class_run {
            visit.call(class_run)?;
        }
        Ok(())
    }

    fn __clear__(&mut self) {
        self.command = None;
        self.class_run = None;
    }

    #[pyo3(signature = (*args, **kwargs))]
    fn __call__(
        &self,
        py: Python<'_>,
        args: &Bound<'_, PyTuple>,
        kwargs: Option<&Bound<'_, pyo3::types::PyDict>>,
    ) -> PyResult<Py<PyAny>> {
        let (Some(command), Some(class_run)) = (&self.command, &self.class_run) else {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "the command of this run method has been garbage collected",
            ));
        };
        let command = command.bind(py);
        let class_run = class_run.bind(py);
        let hooks = command.getattr("hooks")?;

        for hook in hooks.get_item("pre_command")?.try_iter()? {
            hook?.call1((command,))?;
        }
        let result = run_within_exit_stack(command, class_run, args, kwargs);

        // post_command fires whether the run succeeded or raised.
        for hook in hooks.get_item("post_command")?.try_iter()? {
            hook?.call1((command,))?;
        }
        result.map(|v| v.unbind())
    }
}

/// Run `class_run` inside a fresh `contextlib.ExitStack` stored as
/// `command._exit_stack`, reproducing the `with`-statement protocol.
///
/// The stack is entered, the run is called, and the stack is exited with the
/// exception triple (or three `None`s). A truthy `__exit__` return suppresses
/// the exception, exactly as `with` does, so a cleanup registered through
/// `enter_context` can still swallow an error.
fn run_within_exit_stack<'py>(
    command: &Bound<'py, PyAny>,
    class_run: &Bound<'py, PyAny>,
    args: &Bound<'py, PyTuple>,
    kwargs: Option<&Bound<'py, pyo3::types::PyDict>>,
) -> PyResult<Bound<'py, PyAny>> {
    let py = command.py();
    let stack = py.import("contextlib")?.call_method0("ExitStack")?;
    let stack = stack.call_method0("__enter__")?;
    command.setattr("_exit_stack", &stack)?;

    match class_run.call(args, kwargs) {
        Ok(value) => {
            stack.call_method1("__exit__", (py.None(), py.None(), py.None()))?;
            Ok(value)
        }
        Err(e) => {
            let value = e.value(py);
            let suppressed = stack
                .call_method1("__exit__", (value.get_type(), value, e.traceback(py)))?
                .is_truthy()?;
            if suppressed {
                Ok(py.None().into_bound(py))
            } else {
                Err(e)
            }
        }
    }
}

/// The base class for brz commands.
///
/// It is ``subclass``-able and carries a per-instance ``dict`` because the
/// Python ``cmd_*`` subclasses override the class-attribute defaults
/// (``aliases``/``takes_args``/...), define ``run`` and a docstring, and rely
/// on ``isinstance``/``overrideAttr``/the ExitStack lifecycle.
///
/// Only methods and the constructor live here; the data class-attribute defaults
/// and the ``hooks`` attribute are set on the type from Python after the class is
/// bound into ``breezy.commands`` (so subclass class-attribute overrides resolve
/// through the normal MRO rather than being shadowed by instance fields).
#[pyclass(name = "Command", module = "breezy._cmd_rs.commands", subclass, dict)]
pub(crate) struct Command;

#[pymethods]
impl Command {
    // Accept and ignore constructor args: subclasses such as ExternalCommand
    // bypass Command.__init__ and call ``Cls(path)``, which routes the arg
    // through __new__ (a pyclass has only __new__, unlike a plain Python class).
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn new(_args: &Bound<'_, PyTuple>, _kwargs: Option<&Bound<'_, pyo3::types::PyDict>>) -> Self {
        Command
    }

    fn __init__(slf: &Bound<'_, Self>) -> PyResult<()> {
        slf.setattr(
            "supported_std_options",
            pyo3::types::PyList::empty(slf.py()),
        )?;
        Self::_setup_run(slf)
    }

    /// Wrap the command's ``run`` with the pre/post-command + ExitStack wrapper.
    fn _setup_run(slf: &Bound<'_, Self>) -> PyResult<()> {
        let py = slf.py();
        let class_run = slf.getattr("run")?;
        let wrapper = Bound::new(
            py,
            RunWrapper {
                command: Some(slf.clone().into_any().unbind()),
                class_run: Some(class_run.unbind()),
            },
        )?;
        slf.setattr("run", wrapper)?;
        Ok(())
    }

    /// Register a function to call after ``run`` returns or raises (LIFO order).
    #[pyo3(signature = (cleanup_func, *args, **kwargs))]
    fn add_cleanup(
        slf: &Bound<'_, Self>,
        cleanup_func: &Bound<'_, PyAny>,
        args: &Bound<'_, PyTuple>,
        kwargs: Option<&Bound<'_, pyo3::types::PyDict>>,
    ) -> PyResult<()> {
        let stack = slf.getattr("_exit_stack")?;
        let full = PyTuple::new(slf.py(), [cleanup_func])?
            .as_sequence()
            .concat(args.as_sequence())?;
        stack.call_method("callback", full.cast::<PyTuple>()?, kwargs)?;
        Ok(())
    }

    /// Execute and empty pending cleanups immediately.
    fn cleanup_now(slf: &Bound<'_, Self>) -> PyResult<()> {
        slf.getattr("_exit_stack")?.call_method0("close")?;
        Ok(())
    }

    /// Enter a context manager and ensure it gets cleaned up.
    fn enter_context<'py>(
        slf: &Bound<'py, Self>,
        cm: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        slf.getattr("_exit_stack")?
            .call_method1("enter_context", (cm,))
    }

    /// Single-line grammar for this command (arguments only, not options).
    fn _usage(slf: &Bound<'_, Self>) -> PyResult<String> {
        let name: String = slf.call_method0("name")?.extract()?;
        let takes_args: Vec<String> = slf.getattr("takes_args")?.extract()?;
        Ok(breezy::command::usage(&name, &takes_args))
    }

    #[pyo3(signature = (additional_see_also=None, plain=true, see_also_as_links=false, verbose=true))]
    fn get_help_text(
        slf: &Bound<'_, Self>,
        additional_see_also: Option<Vec<String>>,
        plain: bool,
        see_also_as_links: bool,
        verbose: bool,
    ) -> PyResult<String> {
        breezy::commands::get_help_text(
            slf.py(),
            slf.as_any(),
            additional_see_also,
            plain,
            see_also_as_links,
            verbose,
        )
    }

    #[staticmethod]
    fn _get_help_parts<'py>(
        py: Python<'py>,
        text: &str,
    ) -> PyResult<(
        String,
        Bound<'py, pyo3::types::PyDict>,
        Bound<'py, pyo3::types::PyList>,
    )> {
        get_help_parts(py, text)
    }

    /// The command's help topic - its name.
    fn get_help_topic(slf: &Bound<'_, Self>) -> PyResult<Py<PyAny>> {
        Ok(slf.call_method0("name")?.unbind())
    }

    #[pyo3(signature = (additional_terms=None))]
    fn get_see_also(
        slf: &Bound<'_, Self>,
        additional_terms: Option<Vec<String>>,
    ) -> PyResult<Vec<String>> {
        let see_also = breezy::pycommand::python_see_also(slf.as_any())?;
        Ok(breezy::command::CommandSpec {
            see_also,
            ..Default::default()
        }
        .get_see_also(additional_terms))
    }

    /// Dict of valid options for this command (long option name -> option).
    fn options<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, pyo3::types::PyDict>> {
        let py = slf.py();
        let option_mod = py.import("breezy.option")?;
        let option_cls = option_mod.getattr("Option")?;
        let std_options = option_cls.getattr("STD_OPTIONS")?;
        let r = std_options
            .call_method0("copy")?
            .cast_into::<pyo3::types::PyDict>()?;
        let std_names = pyo3::types::PySet::new(py, r.keys())?;
        let options_dict = option_cls.getattr("OPTIONS")?;
        for o in slf.getattr("takes_options")?.try_iter()? {
            let mut o = o?;
            if let Ok(name) = o.extract::<String>() {
                o = options_dict.get_item(name)?;
            }
            let oname = o.getattr("name")?;
            r.set_item(&oname, &o)?;
            // Only looked up here: a command that does not call
            // Command.__init__ has no supported_std_options.
            if std_names.contains(&oname)? {
                slf.getattr("supported_std_options")?
                    .call_method1("append", (&oname,))?;
            }
        }
        Ok(r)
    }

    /// A file linked to stdout with the command's encoding handling.
    fn _setup_outf(slf: &Bound<'_, Self>) -> PyResult<()> {
        let py = slf.py();
        let encoding_type = slf.getattr("encoding_type")?;
        let factory = py.import("breezy.ui")?.getattr("ui_factory")?;
        let kwargs = pyo3::types::PyDict::new(py);
        kwargs.set_item("encoding_type", encoding_type)?;
        let outf = factory.call_method("make_output_stream", (), Some(&kwargs))?;
        slf.setattr("outf", outf)?;
        Ok(())
    }

    #[pyo3(signature = (argv, alias_argv=None))]
    fn run_argv_aliases(
        slf: &Bound<'_, Self>,
        argv: Vec<String>,
        alias_argv: Option<Vec<String>>,
    ) -> PyResult<Py<PyAny>> {
        breezy::pycommand::run_argv_aliases(slf.as_any(), argv, alias_argv)
    }

    /// The default ``run`` - subclasses override it.
    #[pyo3(signature = (*_args, **_kwargs))]
    fn run(
        slf: &Bound<'_, Self>,
        _args: &Bound<'_, PyTuple>,
        _kwargs: Option<&Bound<'_, pyo3::types::PyDict>>,
    ) -> PyResult<()> {
        let name: String = slf.call_method0("name")?.extract()?;
        Err(pyo3::exceptions::PyNotImplementedError::new_err(format!(
            "no implementation of command {name:?}"
        )))
    }

    /// Help message for this class, or None if it has only the base docstring.
    fn help(slf: &Bound<'_, Self>) -> PyResult<Option<String>> {
        let py = slf.py();
        let own_doc = slf.getattr("__doc__")?;
        let base_doc = py.get_type::<Command>().getattr("__doc__")?;
        if own_doc.is(&base_doc) {
            return Ok(None);
        }
        let getdoc = py.import("inspect")?.getattr("getdoc")?;
        getdoc.call1((slf,))?.extract()
    }

    /// The gettext function used to translate this command's help.
    fn gettext(slf: &Bound<'_, Self>, message: &str) -> PyResult<Py<PyAny>> {
        Ok(slf
            .py()
            .import("breezy.i18n")?
            .call_method1("gettext_per_paragraph", (message,))?
            .unbind())
    }

    /// The canonical name for this command (from the class name).
    fn name(slf: &Bound<'_, Self>) -> PyResult<String> {
        let class_name: String = slf.get_type().getattr("__name__")?.extract()?;
        Ok(breezy::command::unsquish_command_name(&class_name))
    }

    /// The name of the plugin that provides this command, or None if builtin.
    fn plugin_name(slf: &Bound<'_, Self>) -> PyResult<Option<String>> {
        let module: String = slf.getattr("__module__")?.extract()?;
        slf.py()
            .import("breezy.plugin")?
            .call_method1("plugin_name", (module,))?
            .extract()
    }
}

/// Translate `template` via ``breezy.i18n.gettext`` and format it with `args`.
///
/// Formatting uses Python's ``str.format``, so ``{0!r}`` in the (translated)
/// templates produces Python reprs.
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
/// Returns a dict mapping parameter names to their bound values (a string, a
/// list, or `None` for an empty ``*`` match), preserving the declaration order
/// of `takes_args`.
#[pyfunction]
pub(crate) fn match_argform<'py>(
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

/// Parse a command line against a command's options.
#[pyfunction]
#[pyo3(signature = (command, argv, alias_argv=None))]
pub(crate) fn parse_args<'py>(
    command: &Bound<'py, PyAny>,
    argv: Vec<String>,
    alias_argv: Option<Vec<String>>,
) -> PyResult<(Bound<'py, PyAny>, Bound<'py, pyo3::types::PyDict>)> {
    breezy::options::parse_args(command, argv, alias_argv)
}

/// Split help text into ``(summary, sections, order)``.
///
/// `sections` is a dict keyed by section label (with `None` for the default
/// section) and `order` is the list of labels in first-appearance order,
/// as returned by ``Command._get_help_parts``.
pub(crate) fn get_help_parts<'py>(
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

/// Drive a single ``brz`` invocation.
///
/// `argv` is the raw argument vector (master options included), or `None` to
/// take it from `sys.argv`. `load_plugins` / `disable_plugins` are the
/// overridable plugin-management callables; everything else is reached through
/// the `breezy.*` modules directly. Returns the command's exit code.
#[pyfunction]
#[pyo3(signature = (argv, load_plugins, disable_plugins))]
pub(crate) fn run_bzr(
    py: Python<'_>,
    argv: &Bound<'_, PyAny>,
    load_plugins: &Bound<'_, PyAny>,
    disable_plugins: &Bound<'_, PyAny>,
) -> PyResult<i32> {
    let argv = breezy::commands::resolve_argv(argv)?;
    breezy::commands::run_bzr(py, argv, load_plugins, disable_plugins)
}

/// Resolve a command object by name.
///
/// Runs the hook-driven lookup plus the typo guard,
/// raising the user-facing "unknown command" `CommandError` (with a "Perhaps you
/// meant" suggestion) when nothing matches.
#[pyfunction]
#[pyo3(signature = (cmd_name, plugins_override=true))]
pub(crate) fn get_cmd_object(
    py: Python<'_>,
    cmd_name: &str,
    plugins_override: bool,
) -> PyResult<Py<PyAny>> {
    breezy::commands::get_cmd_object(py, cmd_name, plugins_override)
}

/// Guess what command a user typoed.
///
/// Unlike the pure `guess_command` scorer (which takes a candidate list), this
/// gathers the candidates itself - every command name plus its aliases - and
/// applies the mis-spelling overrides.
#[pyfunction]
pub(crate) fn guess_typoed_command(py: Python<'_>, cmd_name: &str) -> PyResult<Option<String>> {
    breezy::commands::guess_command(py, cmd_name)
}

/// Resolve a command object by name, without the typo guard.
///
/// Returns `None` when no command is found; the caller raises the user-facing
/// "unknown command" error (with a typo suggestion via `guess_command`).
#[pyfunction]
#[pyo3(signature = (cmd_name, plugins_override=true, check_missing=true))]
pub(crate) fn get_cmd_object_inner(
    py: Python<'_>,
    cmd_name: &str,
    plugins_override: bool,
    check_missing: bool,
) -> PyResult<Option<Py<PyAny>>> {
    breezy::commands::get_cmd_object_inner(py, cmd_name, plugins_override, check_missing)
}

/// Collect every command name.
#[pyfunction]
pub(crate) fn all_command_names(py: Python<'_>) -> PyResult<Py<PyAny>> {
    breezy::commands::all_command_names(py)
}

/// Run an external command and wait for it.
#[pyfunction]
pub(crate) fn spawn_external_command(
    py: Python<'_>,
    path: &str,
    argv: Vec<String>,
) -> PyResult<i32> {
    py.detach(|| breezy::commands::spawn_external_command(path, argv))
        .map_err(Into::into)
}

/// Capture an external command's `--help` output.
#[pyfunction]
pub(crate) fn external_command_help(py: Python<'_>, path: &str) -> PyResult<String> {
    py.detach(|| breezy::commands::external_command_help(path))
        .map_err(Into::into)
}

/// Add the `Command.hooks` hook points.
#[pyfunction]
pub(crate) fn add_command_hooks(hooks: &Bound<'_, PyAny>) -> PyResult<()> {
    breezy::commands::add_command_hooks(hooks)
}

/// Install the hooks supplying brz's own commands.
#[pyfunction]
pub(crate) fn install_bzr_command_hooks(py: Python<'_>) -> PyResult<()> {
    breezy::commands::install_bzr_command_hooks(py)
}

/// Find an external command on `BZRPATH`.
#[pyfunction]
pub(crate) fn find_external_command(
    py: Python<'_>,
    cls: &Bound<'_, PyAny>,
    cmd_name: &str,
) -> PyResult<Option<Py<PyAny>>> {
    breezy::commands::find_external_command(py, cls, cmd_name)
}

/// Look up a command that is a shell script.
#[pyfunction]
pub(crate) fn get_external_command(
    py: Python<'_>,
    cmd_or_none: &Bound<'_, PyAny>,
    cmd_name: &str,
) -> PyResult<Py<PyAny>> {
    breezy::commands::get_external_command(py, cmd_or_none, cmd_name)
}

/// Find a provider that can supply `cmd_name`.
#[pyfunction]
pub(crate) fn probe_for_provider(
    py: Python<'_>,
    cmd_name: &str,
) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
    breezy::commands::probe_for_provider(py, cmd_name)
}

/// The `get_missing_command` hook probing for an uninstalled plugin.
#[pyfunction]
pub(crate) fn try_plugin_provider(py: Python<'_>, cmd_name: &str) -> PyResult<()> {
    breezy::commands::try_plugin_provider(py, cmd_name)
}

/// The message naming the plugin that provides a command.
#[pyfunction]
pub(crate) fn command_available_in_plugin(cmd_name: &str, plugin_name: &str, url: &str) -> String {
    breezy::command::command_available_in_plugin(cmd_name, plugin_name, url)
}

/// Register the builtin commands, once.
#[pyfunction]
pub(crate) fn register_builtin_commands(py: Python<'_>) -> PyResult<()> {
    breezy::commands::register_builtin_commands(py)
}

/// The command classes defined in `module`.
#[pyfunction]
pub(crate) fn scan_module_for_commands<'py>(
    module: &Bound<'py, PyAny>,
) -> PyResult<Vec<Bound<'py, PyAny>>> {
    breezy::commands::scan_module_for_commands(module)
}

/// Register a plugin command.
#[pyfunction]
#[pyo3(signature = (cmd, decorate=false))]
pub(crate) fn register_command(
    cmd: &Bound<'_, PyAny>,
    decorate: bool,
) -> PyResult<Option<Py<PyAny>>> {
    breezy::commands::register_command(cmd, decorate)
}

/// The builtin command names.
#[pyfunction]
pub(crate) fn builtin_command_names(py: Python<'_>) -> PyResult<Vec<String>> {
    breezy::commands::builtin_command_names(py)
}

/// The names of commands registered by plugins.
#[pyfunction]
pub(crate) fn plugin_command_names() -> Vec<String> {
    breezy::commands::plugin_command_names()
}

/// Look up a command in bzr's core.
#[pyfunction]
pub(crate) fn get_bzr_command(
    py: Python<'_>,
    cmd_or_none: &Bound<'_, PyAny>,
    cmd_name: &str,
) -> PyResult<Py<PyAny>> {
    breezy::commands::get_bzr_command(py, cmd_or_none, cmd_name)
}

/// Look up a command among brz's plugins.
#[pyfunction]
pub(crate) fn get_plugin_command(
    py: Python<'_>,
    cmd_or_none: &Bound<'_, PyAny>,
    cmd_name: &str,
) -> PyResult<Py<PyAny>> {
    breezy::commands::get_plugin_command(py, cmd_or_none, cmd_name)
}

/// The `list_commands` hook supplying bzr's core.
#[pyfunction]
pub(crate) fn list_bzr_commands(py: Python<'_>, names: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    breezy::commands::list_bzr_commands(py, names)
}

/// The unwrapped `brz help commands` lines and their continuation indent.
#[pyfunction]
pub(crate) fn command_listing(py: Python<'_>, hidden: bool) -> PyResult<(Vec<String>, usize)> {
    breezy::pyhelp::command_listing(py, hidden)
}

/// Render the help for `topic` over the standard search path.
#[pyfunction]
#[pyo3(signature = (topic=None))]
pub(crate) fn help_text(py: Python<'_>, topic: Option<&str>) -> PyResult<String> {
    breezy::pyhelp::help_text(py, topic)
}

/// The aliases registered alongside a command.
#[pyclass(
    name = "CommandInfo",
    module = "breezy._cmd_rs.commands",
    subclass,
    dict
)]
pub(crate) struct CommandInfo {
    #[pyo3(get, set)]
    aliases: Py<PyAny>,
}

#[pymethods]
impl CommandInfo {
    #[new]
    #[pyo3(signature = (aliases))]
    fn new(aliases: Py<PyAny>) -> Self {
        CommandInfo { aliases }
    }

    /// Build a [`CommandInfo`] from a command class, taking its aliases.
    #[classmethod]
    fn from_command(
        cls: &Bound<'_, pyo3::types::PyType>,
        command: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        Ok(cls.call1((command.getattr("aliases")?,))?.unbind())
    }
}

/// A view of a command table: maps command names (and aliases) to command
/// classes.
///
/// ``breezy.commands.builtin_command_registry`` and ``plugin_cmds`` are views
/// of the global builtin and plugin tables; constructing one makes a new, empty
/// table.
#[pyclass(name = "CommandRegistry", module = "breezy._cmd_rs.commands", subclass)]
pub(crate) struct CommandRegistry {
    table: SharedTable,
    /// The registry whose command a registration here overrides.
    #[pyo3(get, set)]
    overridden_registry: Option<Py<CommandRegistry>>,
}

#[pymethods]
impl CommandRegistry {
    #[new]
    fn new() -> Self {
        CommandRegistry {
            table: SharedTable::new(),
            overridden_registry: None,
        }
    }

    /// The command class registered under `command_name` or as an alias of it.
    fn get(&self, py: Python<'_>, command_name: &str) -> PyResult<Py<PyAny>> {
        self.table
            .class(py, command_name)?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(command_name.to_string()))
    }

    /// The command name for a command class name (``cmd_foo_bar`` is
    /// ``foo-bar``).
    #[staticmethod]
    fn _get_name(command_name: &str) -> String {
        breezy::pyregistry::command_name(command_name)
    }

    /// Register a command class, warning (rather than failing) on a duplicate
    /// unless `decorate`. Returns the previously registered command, if any.
    #[pyo3(signature = (cmd, decorate=false))]
    fn register(
        &self,
        py: Python<'_>,
        cmd: &Bound<'_, PyAny>,
        decorate: bool,
    ) -> PyResult<Option<Py<PyAny>>> {
        let overridden = self
            .overridden_registry
            .as_ref()
            .map(|r| r.borrow(py).table.clone());
        self.table
            .register_class(cmd, decorate, overridden.as_ref())
    }

    /// Register a command without importing its module until it is used.
    fn register_lazy(
        &self,
        command_name: &str,
        aliases: Vec<String>,
        module_name: &str,
    ) -> PyResult<()> {
        self.table
            .register_lazy(command_name, aliases, module_name)
            .map_err(|e| pyo3::exceptions::PyKeyError::new_err(e.to_string()))
    }

    /// Remove the command registered under `key`.
    fn remove(&self, key: &str) -> PyResult<()> {
        self.table
            .lock()
            .remove(key)
            .map(|_| ())
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(key.to_string()))
    }

    /// The registered command names, sorted.
    fn keys(&self) -> Vec<String> {
        self.table.names()
    }

    /// The aliases recorded for the command registered under `key`, or
    /// ``None`` if there is no such command.
    fn get_info(&self, py: Python<'_>, key: &str) -> PyResult<Option<Py<CommandInfo>>> {
        self.table
            .aliases(key)
            .map(|aliases| {
                Py::new(
                    py,
                    CommandInfo {
                        aliases: aliases.into_pyobject(py)?.into_any().unbind(),
                    },
                )
            })
            .transpose()
    }

    fn __contains__(&self, key: &str) -> bool {
        self.table.lock().contains(key)
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(self
            .keys()
            .into_pyobject(py)?
            .call_method0("__iter__")?
            .unbind())
    }

    fn __len__(&self) -> usize {
        self.table.lock().len()
    }
}

/// The view of the builtin command table.
#[pyfunction]
pub(crate) fn builtin_command_registry() -> CommandRegistry {
    CommandRegistry {
        table: breezy::pyregistry::builtin_commands().clone(),
        overridden_registry: None,
    }
}

/// The view of the plugin command table, whose commands override the builtin
/// ones in `builtin`.
#[pyfunction]
pub(crate) fn plugin_command_registry(builtin: Py<CommandRegistry>) -> CommandRegistry {
    CommandRegistry {
        table: breezy::pyregistry::plugin_commands().clone(),
        overridden_registry: Some(builtin),
    }
}

/// Registry of plugin-command providers; iterating yields the providers
/// (values) rather than keys.
#[pyclass(name = "ProvidersRegistry", module = "breezy._cmd_rs.commands", extends = Registry, subclass)]
pub(crate) struct ProvidersRegistry;

#[pymethods]
impl ProvidersRegistry {
    #[new]
    fn new(py: Python<'_>) -> PyClassInitializer<Self> {
        PyClassInitializer::from(Registry::new(py, &PyTuple::empty(py), None))
            .add_subclass(ProvidersRegistry)
    }

    fn __iter__(slf: &Bound<'_, Self>) -> PyResult<Py<PyAny>> {
        let py = slf.py();
        let items = registry_super(slf.as_any(), "items", &PyTuple::empty(py), None)?;
        let providers = pyo3::types::PyList::empty(py);
        for item in items.try_iter()? {
            providers.append(item?.get_item(1)?)?;
        }
        Ok(providers.call_method0("__iter__")?.unbind())
    }
}

/// Top-level command-line orchestration, shared by the `brz` binary
/// (`src/main.rs`) and `python3 -m breezy` (`breezy/__main__.py`).
///
/// Install the debugger signal hook, run the command via `commands_main`
/// inside the `breezy.initialize` context (the command's own exceptions are
/// caught and reported there, so the context exits with no exception), then
/// perform the deliberate abrupt shutdown (atexit hooks, pending weakref
/// finalizers, `os._exit`). The command reads `sys.argv`; the caller is
/// responsible for having set it.
///
/// `profiling` selects whether to log the import profile after the command,
/// matching the `--profile-imports` handling the caller installed before
/// importing breezy.
///
/// This never returns normally: it ends in `os._exit`. The `Ok(())` arm is
/// unreachable; the `Err` only carries failures raised before that point.
#[pyfunction]
#[pyo3(signature = (profiling=false))]
pub(crate) fn run_main(py: Python, profiling: bool) -> PyResult<()> {
    breezy::commands::run_main(py, profiling)
}
