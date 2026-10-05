//! Command orchestration driven through PyO3.
//!
//! These functions implement the command machinery that the `breezy.commands`
//! Python module exposes: the entry path (`run_main`, `commands_main`,
//! `run_bzr`), command lookup and enumeration, argument parsing and help
//! assembly. They are not bindings for the [`crate::command::Command`] trait
//! (those live in [`crate::pycommand`]); they orchestrate Python command
//! objects, the registry hooks and the trace/plugin machinery, all of which
//! remain Python. The genuinely PyO3-free computation they rely on (master-
//! option scanning, profiler selection, argv handling) lives in
//! [`crate::command`].

use crate::command::{CommandError, CommandSource, MasterOptions};
use pyo3::prelude::*;

/// The PyO3 implementation of [`CommandSource`]: drives the real
/// ``breezy.commands.Command.hooks`` and Python command objects directly.
///
/// The hook iteration and override logic is the pure
/// [`CommandSource::resolve_command`] default; this only supplies the primitive
/// Python operations.
pub struct PyCommandSource<'py> {
    py: Python<'py>,
    /// The ``Command.hooks`` mapping.
    hooks: Bound<'py, PyAny>,
}

impl<'py> PyCommandSource<'py> {
    /// Build a source from the live ``breezy.commands.Command.hooks``.
    pub fn new(py: Python<'py>) -> PyResult<Self> {
        let hooks = py
            .import("breezy.commands")?
            .getattr("Command")?
            .getattr("hooks")?;
        Ok(PyCommandSource { py, hooks })
    }

    fn hook_list(&self, key: &str) -> PyResult<Vec<Py<PyAny>>> {
        let mut hooks = Vec::new();
        for hook in self.hooks.get_item(key)?.try_iter()? {
            hooks.push(hook?.unbind());
        }
        Ok(hooks)
    }

    /// Resolve a command object by name.
    ///
    /// Runs the hook-driven [`CommandSource::resolve_command`]; when nothing is
    /// found, raises the user-facing ``CommandError`` (suggesting a near match via
    /// [`Self::guess_command`] when there is one), instead of a bare `KeyError`.
    pub fn get_cmd_object(&self, cmd_name: &str, plugins_override: bool) -> PyResult<Py<PyAny>> {
        if let Some(cmd) = self.resolve_command(cmd_name, plugins_override, true)? {
            return Ok(cmd);
        }
        let msg = match self.guess_command(cmd_name)? {
            Some(candidate) => {
                crate::i18n::gettext("unknown command \"%s\". Perhaps you meant \"%s\"")
                    .replacen("%s", cmd_name, 1)
                    .replacen("%s", &candidate, 1)
            }
            None => crate::i18n::gettext("unknown command \"%s\"").replacen("%s", cmd_name, 1),
        };
        Err(command_error(self.py, &msg)?)
    }

    /// Guess what command a user typoed.
    ///
    /// Builds the candidate set (every command name plus its aliases) and scores
    /// them with the pure [`crate::command::guess_command`], applying the
    /// hard-coded mis-spelling overrides.
    fn guess_command(&self, cmd_name: &str) -> PyResult<Option<String>> {
        let names = self.enumerate_names()?;
        let mut candidates: Vec<String> = Vec::new();
        for name in names {
            let cmd = self.get_cmd_object(&name, true)?;
            let aliases: Vec<String> = cmd.bind(self.py).getattr("aliases")?.extract()?;
            candidates.push(name);
            candidates.extend(aliases);
        }
        let overrides = guess_overrides(cmd_name);
        Ok(crate::command::guess_command(
            cmd_name,
            &candidates,
            &overrides,
        ))
    }
}

/// Resolve a command object by name.
///
/// The full resolution - the hook-driven lookup plus the typo guard - runs in
/// Rust; this is the entry point the cmd-py binding and the dispatcher share.
pub fn get_cmd_object(
    py: Python<'_>,
    cmd_name: &str,
    plugins_override: bool,
) -> PyResult<Py<PyAny>> {
    PyCommandSource::new(py)?.get_cmd_object(cmd_name, plugins_override)
}

/// Guess what command a user typoed.
pub fn guess_command(py: Python<'_>, cmd_name: &str) -> PyResult<Option<String>> {
    PyCommandSource::new(py)?.guess_command(cmd_name)
}

/// The hard-coded mis-spelling overrides: a small table of ``(candidate, cost)``
/// corrections the distance heuristic gets wrong.
fn guess_overrides(cmd_name: &str) -> Vec<(String, f64)> {
    match cmd_name {
        // The heuristic otherwise finds "nick" for "ic"; force "ci".
        "ic" => vec![("ci".to_string(), 0.0)],
        _ => Vec::new(),
    }
}

/// Build the `breezy.errors.CommandError` for `message`.
fn command_error(py: Python<'_>, message: &str) -> PyResult<PyErr> {
    let err = py
        .import("breezy.errors")?
        .getattr("CommandError")?
        .call1((message,))?;
    Ok(PyErr::from_value(err))
}

impl CommandSource for PyCommandSource<'_> {
    type Cmd = Py<PyAny>;
    type Hook = Py<PyAny>;

    fn list_commands_hooks(&self) -> Result<Vec<Py<PyAny>>, CommandError> {
        Ok(self.hook_list("list_commands")?)
    }

    fn call_list_hook(
        &self,
        hook: &Py<PyAny>,
        names: std::collections::BTreeSet<String>,
    ) -> Result<Option<std::collections::BTreeSet<String>>, CommandError> {
        let names = pyo3::types::PySet::new(self.py, names)?;
        let result = hook.bind(self.py).call1((names,))?;
        if result.is_none() {
            return Ok(None);
        }
        Ok(Some(result.extract()?))
    }

    fn hook_label(&self, hook: &Py<PyAny>) -> Result<String, CommandError> {
        Ok(self
            .hooks
            .call_method1("get_hook_name", (hook.bind(self.py),))?
            .extract()?)
    }

    fn get_command_hooks(&self) -> Result<Vec<Py<PyAny>>, CommandError> {
        Ok(self.hook_list("get_command")?)
    }
    fn get_missing_command_hooks(&self) -> Result<Vec<Py<PyAny>>, CommandError> {
        Ok(self.hook_list("get_missing_command")?)
    }
    fn extend_command_hooks(&self) -> Result<Vec<Py<PyAny>>, CommandError> {
        Ok(self.hook_list("extend_command")?)
    }

    fn call_get_command(
        &self,
        hook: &Py<PyAny>,
        current: Option<&Py<PyAny>>,
        cmd_name: &str,
    ) -> Result<Option<Py<PyAny>>, CommandError> {
        let cur = match current {
            Some(c) => c.bind(self.py).clone(),
            None => self.py.None().into_bound(self.py),
        };
        let result = hook.bind(self.py).call1((cur, cmd_name))?;
        Ok((!result.is_none()).then(|| result.unbind()))
    }

    fn call_get_missing(
        &self,
        hook: &Py<PyAny>,
        cmd_name: &str,
    ) -> Result<Option<Py<PyAny>>, CommandError> {
        let result = hook.bind(self.py).call1((cmd_name,))?;
        Ok((!result.is_none()).then(|| result.unbind()))
    }

    fn call_extend(&self, hook: &Py<PyAny>, cmd: &Py<PyAny>) -> Result<(), CommandError> {
        hook.bind(self.py).call1((cmd.bind(self.py),))?;
        Ok(())
    }

    fn is_plugin_command(&self, cmd: &Py<PyAny>) -> Result<bool, CommandError> {
        Ok(cmd.bind(self.py).call_method0("plugin_name")?.is_truthy()?)
    }

    fn has_invoked_as(&self, cmd: &Py<PyAny>) -> Result<bool, CommandError> {
        Ok(cmd
            .bind(self.py)
            .getattr_opt("invoked_as")?
            .is_some_and(|v| !v.is_none()))
    }

    fn set_invoked_as(&self, cmd: &Py<PyAny>, cmd_name: &str) -> Result<(), CommandError> {
        Ok(cmd.bind(self.py).setattr("invoked_as", cmd_name)?)
    }
}

/// The cleanup after a command run by ``run_bzr``: report memory use if the
/// ``memory`` debug flag is set, restore the verbosity level and reset the
/// command-line config overrides, so that a later command in the same process
/// starts afresh. Every step runs; the first failure is returned.
fn run_bzr_cleanup(
    py: Python<'_>,
    saved_verbosity: i32,
    cmdline_overrides: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let memory = (|| -> PyResult<()> {
        if py
            .import("breezy.debug")?
            .call_method1("debug_flag_enabled", ("memory",))?
            .is_truthy()?
        {
            let kwargs = pyo3::types::PyDict::new(py);
            kwargs.set_item("short", false)?;
            py.import("breezy.trace")?.call_method(
                "debug_memory",
                ("Process status after command:",),
                Some(&kwargs),
            )?;
        }
        Ok(())
    })();
    crate::options::set_verbosity_level(saved_verbosity);
    let reset = cmdline_overrides.call_method0("_reset").map(|_| ());
    memory.and(reset)
}

/// Build the help text for the Python command `cmd`.
///
/// The assembly is [`crate::command::CommandSpec::help_text`]; this reads the
/// command into a spec, renders its options block, and installs the i18n
/// catalogue when the command's `l10n` attribute asks for translation.
pub fn get_help_text(
    py: Python<'_>,
    cmd: &Bound<'_, PyAny>,
    additional_see_also: Option<Vec<String>>,
    plain: bool,
    see_also_as_links: bool,
    verbose: bool,
) -> PyResult<String> {
    let localise = cmd.getattr("l10n")?.is_truthy()?;
    if localise {
        py.import("breezy.i18n")?.call_method0("install")?;
    }
    let spec = crate::pycommand::spec_from_python(cmd)?;
    let option_help = crate::pycommand::python_option_help(cmd)?;
    Ok(spec.help_text(
        &option_help,
        additional_see_also,
        plain,
        see_also_as_links,
        verbose,
        localise,
    ))
}

/// Resolve a command object by name, without the typo guard.
///
/// The hook iteration, override rule and ``invoked_as`` defaulting are the pure
/// [`CommandSource::resolve_command`] default; this builds a [`PyCommandSource`]
/// over the live ``Command.hooks`` and runs it. Returns `Ok(None)` when no
/// command is found (the caller raises the user-facing error).
pub fn get_cmd_object_inner(
    py: Python<'_>,
    cmd_name: &str,
    plugins_override: bool,
    check_missing: bool,
) -> PyResult<Option<Py<PyAny>>> {
    Ok(PyCommandSource::new(py)?.resolve_command(cmd_name, plugins_override, check_missing)?)
}

/// Collect every command name.
///
/// The hook iteration and None-guard are the pure
/// [`CommandSource::enumerate_names`] default; this builds a [`PyCommandSource`]
/// over the live ``Command.hooks`` and runs it.
pub fn all_command_names(py: Python<'_>) -> PyResult<Py<PyAny>> {
    let names = PyCommandSource::new(py)?.enumerate_names()?;
    Ok(pyo3::types::PySet::new(py, names)?.into_any().unbind())
}

/// Yield the command classes defined in `module`: every attribute whose name
/// starts with ``cmd_``.
pub fn scan_module_for_commands<'py>(
    module: &Bound<'py, PyAny>,
) -> PyResult<Vec<Bound<'py, PyAny>>> {
    let module_dict = module.getattr("__dict__")?;
    let mut found = Vec::new();
    for name in module_dict.try_iter()? {
        let name = name?;
        if name.extract::<String>()?.starts_with("cmd_") {
            found.push(module_dict.get_item(&name)?);
        }
    }
    Ok(found)
}

/// Register the builtin commands, once.
///
/// The Python command classes of ``breezy.builtins`` and the native commands go
/// into the builtin table, followed by the lazily registered builtins. The
/// classes generated for the native commands are not registered as classes.
pub fn register_builtin_commands(py: Python<'_>) -> PyResult<()> {
    let table = crate::pyregistry::builtin_commands();
    if !table.lock().is_empty() {
        return Ok(());
    }
    let builtins = py.import("breezy.builtins")?;
    for cmd_class in scan_module_for_commands(builtins.as_any())? {
        if cmd_class.getattr("__dict__")?.contains("_native_name")? {
            continue;
        }
        table.register_class(&cmd_class, false, None)?;
    }
    for entry in crate::registry::command_registry().entries() {
        table
            .lock()
            .insert(crate::registry::Registration::native(entry), false)
            .map_err(|e| pyo3::exceptions::PyKeyError::new_err(e.to_string()))?;
    }
    builtins.call_method0("_register_lazy_builtins")?;
    Ok(())
}

/// Register a plugin command.
///
/// Returns the command it overrode, if any.
pub fn register_command(cmd: &Bound<'_, PyAny>, decorate: bool) -> PyResult<Option<Py<PyAny>>> {
    crate::pyregistry::plugin_commands().register_class(
        cmd,
        decorate,
        Some(crate::pyregistry::builtin_commands()),
    )
}

/// Return the builtin command names.
pub fn builtin_command_names(py: Python<'_>) -> PyResult<Vec<String>> {
    register_builtin_commands(py)?;
    Ok(crate::pyregistry::builtin_commands().names())
}

/// Return the names of commands registered by plugins.
pub fn plugin_command_names() -> Vec<String> {
    crate::pyregistry::plugin_commands().names()
}

/// Run the external command at `path` with `argv` and wait for it.
///
/// Behaves like ``os.spawnv(os.P_WAIT, ...)``: the child is passed `path` as its
/// own ``argv[0]``, and the result is the exit status, or the negated signal
/// number when the child was killed by a signal.
pub fn spawn_external_command(path: &str, argv: Vec<String>) -> std::io::Result<i32> {
    let status = std::process::Command::new(path).args(argv).status()?;
    if let Some(code) = status.code() {
        return Ok(code);
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::ExitStatusExt;
        // Killed by a signal: os.spawnv reports -signum.
        if let Some(signal) = status.signal() {
            return Ok(-signal);
        }
    }
    Err(std::io::Error::other(format!(
        "{path} exited without a status"
    )))
}

/// Capture ``<path> --help`` for an external command's help text.
///
/// A non-zero exit is not an error: whatever the command wrote is the help.
/// Output is decoded lossily, since an external command's encoding is unknown.
pub fn external_command_help(path: &str) -> std::io::Result<String> {
    let out = std::process::Command::new(path).arg("--help").output()?;
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

/// Add the ``Command.hooks`` hook points to `hooks`.
///
/// The definitions themselves are [`crate::command::command_hook_defs`]; this
/// only calls ``add_hook`` for each, in order.
pub fn add_command_hooks(hooks: &Bound<'_, PyAny>) -> PyResult<()> {
    for def in crate::command::command_hook_defs() {
        hooks.call_method1("add_hook", (def.name, def.doc, def.introduced))?;
    }
    Ok(())
}

/// Install the hooks supplying brz's own commands.
///
/// Every hook registered here is a Rust function. The install is idempotent:
/// it returns immediately if the core ``list_commands`` hook is already present.
pub fn install_bzr_command_hooks(py: Python<'_>) -> PyResult<()> {
    let commands = py.import("breezy.commands")?;
    let hooks = commands.getattr("Command")?.getattr("hooks")?;
    let rs = py.import("breezy._cmd_rs")?.getattr("commands")?;

    let list_bzr_commands = rs.getattr("list_bzr_commands")?;
    if hooks
        .get_item("list_commands")?
        .contains(&list_bzr_commands)?
    {
        return Ok(());
    }
    for (point, name, label) in [
        ("list_commands", "list_bzr_commands", "bzr commands"),
        ("get_command", "get_bzr_command", "bzr commands"),
        ("get_command", "get_plugin_command", "bzr plugin commands"),
        (
            "get_command",
            "get_external_command",
            "bzr external command lookup",
        ),
        (
            "get_missing_command",
            "try_plugin_provider",
            "bzr plugin-provider-db check",
        ),
    ] {
        hooks.call_method1("install_named_hook", (point, rs.getattr(name)?, label))?;
    }
    Ok(())
}

/// Find an external command named `cmd_name` on ``BZRPATH``.
///
/// The path search itself is [`crate::command::find_on_bzrpath`]; the file test
/// and the resulting ``ExternalCommand`` come from Python, so the lookup keeps
/// using ``os.path.isfile`` and yields a real command object.
pub fn find_external_command(
    py: Python<'_>,
    cls: &Bound<'_, PyAny>,
    cmd_name: &str,
) -> PyResult<Option<Py<PyAny>>> {
    let os = py.import("os")?;
    let bzrpath: String = os
        .getattr("environ")?
        .call_method1("get", ("BZRPATH", ""))?
        .extract()?;
    let separator: char = os.getattr("pathsep")?.extract()?;
    let isfile = os.getattr("path")?.getattr("isfile")?;
    let found = crate::command::find_on_bzrpath(&bzrpath, separator, cmd_name, |path| {
        isfile.call1((path,))?.is_truthy()
    })?;
    found
        .map(|path| Ok(cls.call1((path,))?.unbind()))
        .transpose()
}

/// The ``get_command`` hook looking up a command that is a shell script.
///
/// Only looks when nothing has been found so far.
pub fn get_external_command<'py>(
    py: Python<'py>,
    cmd_or_none: &Bound<'py, PyAny>,
    cmd_name: &str,
) -> PyResult<Py<PyAny>> {
    if !cmd_or_none.is_none() {
        return Ok(cmd_or_none.clone().unbind());
    }
    let cmd_obj = py
        .import("breezy.externalcommand")?
        .getattr("ExternalCommand")?
        .call_method1("find_command", (cmd_name,))?;
    // A falsy result means "not found".
    if cmd_obj.is_truthy()? {
        Ok(cmd_obj.unbind())
    } else {
        Ok(py.None())
    }
}

/// Find a provider that can supply `cmd_name`.
///
/// Returns the provider's plugin metadata together with the provider itself.
/// Providers that cannot supply the command raise
/// ``breezy.commands.NoPluginAvailable`` and are skipped; if none can, that
/// same error is raised for `cmd_name`.
pub fn probe_for_provider(py: Python<'_>, cmd_name: &str) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
    let commands = py.import("breezy.commands")?;
    let no_plugin = commands.getattr("NoPluginAvailable")?;
    // Look for providers that provide this command but aren't installed.
    for provider in commands.getattr("command_providers_registry")?.try_iter()? {
        let provider = provider?;
        match provider.call_method1("plugin_for_command", (cmd_name,)) {
            Ok(metadata) => return Ok((metadata.unbind(), provider.unbind())),
            Err(e) if e.is_instance(py, &no_plugin) => {}
            Err(e) => return Err(e),
        }
    }
    Err(PyErr::from_value(no_plugin.call1((cmd_name,))?))
}

/// The ``get_missing_command`` hook probing for an uninstalled plugin.
///
/// Raises ``breezy.commands.CommandAvailableInPlugin`` when a provider knows of
/// `cmd_name`; when none does, the command is simply not found and the hook
/// returns without a command.
pub fn try_plugin_provider(py: Python<'_>, cmd_name: &str) -> PyResult<()> {
    let commands = py.import("breezy.commands")?;
    match probe_for_provider(py, cmd_name) {
        Ok((plugin_metadata, provider)) => Err(PyErr::from_value(
            commands.getattr("CommandAvailableInPlugin")?.call1((
                cmd_name,
                plugin_metadata,
                provider,
            ))?,
        )),
        Err(e) if e.is_instance(py, &commands.getattr("NoPluginAvailable")?) => Ok(()),
        Err(e) => Err(e),
    }
}

/// Look up a command in bzr's core.
///
/// Registers the builtins (once) and instantiates the registered class, falling
/// back to `cmd_or_none`.
pub fn get_bzr_command<'py>(
    py: Python<'py>,
    cmd_or_none: &Bound<'py, PyAny>,
    cmd_name: &str,
) -> PyResult<Py<PyAny>> {
    register_builtin_commands(py)?;
    instantiate(
        py,
        crate::pyregistry::builtin_commands(),
        cmd_or_none,
        cmd_name,
    )
}

/// Look up a command among brz's plugins, falling back to `cmd_or_none`.
pub fn get_plugin_command<'py>(
    py: Python<'py>,
    cmd_or_none: &Bound<'py, PyAny>,
    cmd_name: &str,
) -> PyResult<Py<PyAny>> {
    instantiate(
        py,
        crate::pyregistry::plugin_commands(),
        cmd_or_none,
        cmd_name,
    )
}

/// An instance of the command `cmd_name` registered in `table`, or
/// `cmd_or_none` if there is none.
fn instantiate<'py>(
    py: Python<'py>,
    table: &crate::pyregistry::SharedTable,
    cmd_or_none: &Bound<'py, PyAny>,
    cmd_name: &str,
) -> PyResult<Py<PyAny>> {
    match table.class(py, cmd_name)? {
        Some(class) => Ok(class.bind(py).call0()?.unbind()),
        None => Ok(cmd_or_none.clone().unbind()),
    }
}

/// The ``list_commands`` hook supplying bzr's core: add the builtin and plugin
/// command names to `names`.
pub fn list_bzr_commands<'py>(py: Python<'py>, names: &Bound<'py, PyAny>) -> PyResult<Py<PyAny>> {
    register_builtin_commands(py)?;
    names.call_method1("update", (crate::pyregistry::builtin_commands().names(),))?;
    names.call_method1("update", (crate::pyregistry::plugin_commands().names(),))?;
    Ok(names.clone().unbind())
}

/// Resolve and validate an argv.
///
/// `None` (Python `None`) falls back to `sys.argv[1:]`; otherwise every element
/// must be a `str`, and a non-str raises `breezy.errors.BzrError`.
pub fn resolve_argv(argv: &Bound<'_, PyAny>) -> PyResult<Vec<String>> {
    let py = argv.py();
    if argv.is_none() {
        let full: Vec<String> = py.import("sys")?.getattr("argv")?.extract()?;
        return Ok(full.into_iter().skip(1).collect());
    }
    let mut new_argv = Vec::new();
    for item in argv.try_iter()? {
        let item = item?;
        match item.cast::<pyo3::types::PyString>() {
            Ok(s) => new_argv.push(s.extract::<String>()?),
            Err(_) => return Err(bzr_error(py, "argv should be list of unicode strings.")?),
        }
    }
    Ok(new_argv)
}

/// Build the `breezy.errors.BzrError` for `message`.
fn bzr_error(py: Python<'_>, message: &str) -> PyResult<PyErr> {
    let err = py
        .import("breezy.errors")?
        .getattr("BzrError")?
        .call1((message,))?;
    Ok(PyErr::from_value(err))
}

/// Drive a single ``brz`` invocation.
///
/// `full_argv` is the raw argument vector (with master options still present).
/// `load_plugins` / `disable_plugins` are the (overridable) plugin-management
/// callables ``breezy.commands.run_bzr`` takes; everything else is reached
/// directly through the ``breezy.*`` modules. Returns the command's exit code.
pub fn run_bzr(
    py: Python<'_>,
    full_argv: Vec<String>,
    load_plugins: &Bound<'_, PyAny>,
    disable_plugins: &Bound<'_, PyAny>,
) -> PyResult<i32> {
    // Target the "brz" logger so the records reach the brz.log trace stream
    // (its BreezyTraceHandler), where mutter() writes.
    log::debug!(target: "brz", "breezy version: {}", crate::version::version_string());
    log::debug!(target: "brz", "brz arguments: {full_argv:?}");

    let (opts, argv) = crate::command::scan_master_options(full_argv).map_err(|e| {
        pyo3::exceptions::PyIndexError::new_err(format!("missing argument for {}", e.option))
    })?;

    let debug = py.import("breezy.debug")?;
    for flag in &opts.debug_flags {
        debug.call_method1("set_debug_flag", (flag.as_str(),))?;
    }
    if let Some(concurrency) = &opts.concurrency {
        py.import("os")?
            .getattr("environ")?
            .set_item("BRZ_CONCURRENCY", concurrency.as_str())?;
    }
    let cmdline_overrides = py
        .import("breezy")?
        .call_method0("get_global_state")?
        .getattr("cmdline_overrides")?;
    cmdline_overrides.call_method1("_from_cmdline", (opts.config_overrides.clone(),))?;
    debug.call_method0("set_debug_flags_from_config")?;

    run_bzr_dispatch(
        py,
        &opts,
        argv,
        load_plugins,
        disable_plugins,
        &cmdline_overrides,
    )
}

/// The command-dispatch portion of [`run_bzr`], after master options have been
/// scanned and their side effects applied.
fn run_bzr_dispatch(
    py: Python<'_>,
    opts: &MasterOptions,
    mut argv: Vec<String>,
    load_plugins: &Bound<'_, PyAny>,
    disable_plugins: &Bound<'_, PyAny>,
    cmdline_overrides: &Bound<'_, PyAny>,
) -> PyResult<i32> {
    let commands = py.import("breezy.commands")?;

    if opts.no_plugins {
        disable_plugins.call0()?;
    } else {
        let config = py.import("breezy.config")?.call_method0("GlobalConfig")?;
        let warn = !config
            .call_method1("suppress_warning", ("plugin_load_failure",))?
            .is_truthy()?;
        let kwargs = pyo3::types::PyDict::new(py);
        kwargs.set_item("warn_load_problems", warn)?;
        load_plugins.call((), Some(&kwargs))?;
    }

    let source = PyCommandSource::new(py)?;

    // With no command, show help; with --version, show the version.
    match crate::command::classify_dispatch(&argv) {
        crate::command::Dispatch::ShowHelp => {
            run_named_command(&source, "help")?;
            return Ok(0);
        }
        crate::command::Dispatch::ShowVersion => {
            run_named_command(&source, "version")?;
            return Ok(0);
        }
        crate::command::Dispatch::RunCommand => {}
    }

    // Expand a user alias for the command name.
    let mut alias_argv: Option<Vec<String>> = None;
    if !opts.no_aliases {
        let expansion = commands
            .call_method1("get_alias", (argv[0].as_str(),))?
            .extract::<Option<Vec<String>>>()?;
        alias_argv = crate::command::apply_alias(&mut argv, expansion);
    }

    let cmd_name = argv.remove(0);
    let cmd_obj = source
        .get_cmd_object(&cmd_name, !opts.builtin)?
        .into_bound(py);
    if opts.no_l10n {
        cmd_obj.setattr("l10n", false)?;
    }

    // Save and zero the verbosity level for the duration of the command; the
    // cleanup guard restores it (and resets overrides) on every exit path.
    let saved_verbosity = crate::options::verbosity_level();
    crate::options::set_verbosity_level(0);

    let result = (|| -> PyResult<i32> {
        let (profiler, warnings) = crate::command::select_profiler(opts);
        if !warnings.is_empty() {
            let trace = py.import("breezy.trace")?;
            for warning in warnings {
                trace.call_method1("warning", (warning,))?;
            }
        }
        let ret = run_command(
            &commands,
            &cmd_obj,
            argv,
            alias_argv,
            profiler.name(),
            opts.lsprof_file.clone(),
        )?;
        // A command returning None exits with 0.
        Ok(ret.extract::<Option<i32>>()?.unwrap_or(0))
    })();
    let cleanup = run_bzr_cleanup(py, saved_verbosity, cmdline_overrides);
    match result {
        Ok(code) => cleanup.map(|()| code),
        // The command's own error is the one to report.
        Err(err) => {
            if let Err(cleanup_err) = cleanup {
                log::debug!(target: "brz", "error during command cleanup: {cleanup_err}");
            }
            Err(err)
        }
    }
}

/// Run a builtin command by name with an empty argv (used for ``help`` and
/// ``version`` when ``brz`` is invoked with no command / ``--version``).
///
/// Resolves the command through the Rust [`PyCommandSource`] and invokes its
/// Python ``run_argv_aliases``.
fn run_named_command(source: &PyCommandSource<'_>, name: &str) -> PyResult<()> {
    let cmd = source.get_cmd_object(name, true)?;
    cmd.bind(source.py)
        .call_method1("run_argv_aliases", (Vec::<String>::new(),))?;
    Ok(())
}

/// Run `cmd_obj` under the selected profiler.
fn run_command<'py>(
    commands: &Bound<'py, PyAny>,
    cmd_obj: &Bound<'py, PyAny>,
    argv: Vec<String>,
    alias_argv: Option<Vec<String>>,
    profiler: &str,
    lsprof_file: Option<String>,
) -> PyResult<Bound<'py, PyAny>> {
    let run = cmd_obj.getattr("run_argv_aliases")?;
    match profiler {
        "lsprof" => {
            commands.call_method1("apply_lsprofiled", (lsprof_file, &run, argv, alias_argv))
        }
        "profile" => commands.call_method1("apply_profiled", (&run, argv, alias_argv)),
        "coverage" => commands.call_method1("apply_coveraged", (&run, argv, alias_argv)),
        _ => run.call1((argv, alias_argv)),
    }
}

/// Register the builtins, install the command hooks, run the command, and map
/// a command exception to an exit code.
///
/// Any `KeyboardInterrupt`/`Exception` becomes the exit code from
/// `trace.report_exception`, honouring the `BRZ_PDB` post-mortem hook. With
/// `argv` `None`, `run_bzr` reads `sys.argv`; an explicit list has its program
/// name dropped before dispatch.
pub fn commands_main(py: Python<'_>, argv: Option<Vec<String>>) -> PyResult<i32> {
    let commands = py.import("breezy.commands")?;
    register_builtin_commands(py)?;
    install_bzr_command_hooks(py)?;

    let trace = py.import("breezy.trace")?;
    let sys = py.import("sys")?;
    let run_argv: Py<PyAny> = match crate::command::drop_program_name(argv) {
        Some(a) => a.into_pyobject(py)?.into(),
        None => py.None(),
    };
    match commands.call_method1("run_bzr", (run_argv,)) {
        Ok(v) => {
            let ret = v.extract::<i32>()?;
            trace.call_method1("mutter", ("return code %d", ret))?;
            Ok(ret)
        }
        Err(e) => {
            let tb = e.traceback(py);
            let exc_info = (e.get_type(py), e.value(py), tb.clone());
            let exitcode: i32 = trace
                .call_method1("report_exception", (exc_info, sys.getattr("stderr")?))?
                .extract()?;
            let os = py.import("os")?;
            if os
                .getattr("environ")?
                .call_method1("get", ("BRZ_PDB",))?
                .is_truthy()?
            {
                // User-facing notice before dropping into pdb, so an interactive
                // BRZ_PDB session still sees it.
                println!("**** entering debugger");
                py.import("pdb")?.call_method1("post_mortem", (tb,))?;
            }
            trace.call_method1("mutter", ("return code %d", exitcode))?;
            Ok(exitcode)
        }
    }
}

/// The top-level CLI entry point.
///
/// Hooks the debugger signal, enters `breezy.initialize()`, dispatches via
/// [`commands_main`], optionally dumps import-profiling, then shuts down
/// abruptly (atexit + weakref finalizers + `os._exit`). Never returns
/// normally; `os._exit` ends the process.
pub fn run_main(py: Python<'_>, profiling: bool) -> PyResult<()> {
    let breakin = py.import("breezy.breakin")?;
    breakin.getattr("hook_debugger_to_signal")?.call0()?;

    let breezy = py.import("breezy")?;

    // initialize() returns an already-started BzrLibraryState; entering it as a
    // context manager is a no-op, so we just call it and pair it with __exit__.
    let state = breezy.getattr("initialize")?.call0()?;
    let none = py.None();
    let exit_val: i32 = match commands_main(py, None) {
        Ok(code) => {
            if profiling {
                let profile_imports = py.import("profile_imports")?;
                let sys = py.import("sys")?;
                profile_imports
                    .getattr("log_stack_info")?
                    .call1((sys.getattr("stderr")?,))?;
            }
            state.call_method1("__exit__", (&none, &none, &none))?;
            code
        }
        Err(e) => {
            // commands_main never lets a command exception through (it maps them
            // to an exit code); this only fires for failures in the setup before
            // the command. BzrLibraryState.__exit__ never suppresses, so
            // propagate after cleanup.
            let etype = e.get_type(py);
            let suppress = state.call_method1("__exit__", (etype, e.value(py), e.traceback(py)))?;
            if suppress.is_truthy()? {
                0
            } else {
                return Err(e);
            }
        }
    };

    // Shut down abruptly: run the two cleanup phases a normal interpreter exit
    // would (atexit hooks and pending weakref finalizers, which the test suite
    // relies on to remove TEST_ROOT and leaked limbo dirs), then exit without
    // flushing or gc.
    py.import("atexit")?.getattr("_run_exitfuncs")?.call0()?;
    py.import("weakref")?
        .getattr("finalize")?
        .getattr("_exitfunc")?
        .call0()?;
    py.import("os")?.getattr("_exit")?.call1((exit_val,))?;
    Ok(())
}
