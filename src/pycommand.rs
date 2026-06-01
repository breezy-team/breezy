//! Python bindings for [`Command`].
//!
//! [`PyCommand`] wraps a Python `Command` instance and implements the Rust
//! [`Command`] trait by delegating each method to the underlying Python object.
//! This is how the existing Python command base class and its subclasses are
//! grandfathered into the Rust command infrastructure.

use crate::command::Command;
use pyo3::prelude::*;

/// A wrapper around a Python command object.
///
/// This struct provides a Rust interface to Python `Command` instances,
/// implementing the [`Command`] trait. It allows Rust code to drive command
/// objects that are still implemented in Python.
pub struct PyCommand(Py<PyAny>);

impl PyCommand {
    /// Creates a new `PyCommand` wrapper around a Python command object.
    ///
    /// # Arguments
    ///
    /// * `o` - The Python command object to wrap.
    pub fn new(o: Py<PyAny>) -> Self {
        PyCommand(o)
    }
}

impl Command for PyCommand {
    fn name(&self) -> String {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("name")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn aliases(&self) -> Vec<String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("aliases")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn takes_args(&self) -> Vec<String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("takes_args")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn hidden(&self) -> bool {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("hidden")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn encoding_type(&self) -> String {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("encoding_type")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn invoked_as(&self) -> Option<String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .getattr("invoked_as")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn plugin_name(&self) -> Option<String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("plugin_name")
                .unwrap()
                .extract()
                .unwrap()
        })
    }

    fn help(&self) -> Option<String> {
        Python::attach(|py| {
            self.0
                .bind(py)
                .call_method0("help")
                .unwrap()
                .extract()
                .unwrap()
        })
    }
}

use crate::command::{MasterOptions, Profiler};

/// Restores `breezy.option._verbosity_level` and resets the command-line config
/// overrides when dropped, mirroring the ``finally`` block of the Python
/// ``run_bzr``. Using a guard makes the restore happen on every exit path,
/// including when a command raises.
struct RunBzrCleanup<'py> {
    ctx: &'py Bound<'py, PyAny>,
    saved_verbosity: Py<PyAny>,
}

impl Drop for RunBzrCleanup<'_> {
    fn drop(&mut self) {
        let py = self.ctx.py();
        if self
            .ctx
            .call_method0("memory_debug_enabled")
            .and_then(|v| v.extract::<bool>())
            .unwrap_or(false)
        {
            let _ = self.ctx.call_method0("debug_memory");
        }
        let _ = self
            .ctx
            .call_method1("set_verbosity_level", (self.saved_verbosity.bind(py),));
        let _ = self.ctx.call_method0("reset_cmdline_overrides");
    }
}

/// Drive a single ``brz`` invocation, mirroring the body of the Python
/// ``run_bzr``.
///
/// `full_argv` is the raw argument vector (with master options still present);
/// the master options are scanned and their side effects applied through `ctx`.
/// `ctx` is a Python object providing the side-effecting operations as methods
/// (plugin loading, command lookup, alias resolution, running the command under
/// a profiler, verbosity access and so on). Returns the command's exit code.
pub fn run_bzr(full_argv: Vec<String>, ctx: &Bound<'_, PyAny>) -> PyResult<i32> {
    let (opts, argv) = crate::command::scan_master_options(full_argv).map_err(|e| {
        pyo3::exceptions::PyIndexError::new_err(format!("missing argument for {}", e.option))
    })?;

    // Apply the master-option side effects that the Python loop used to do
    // inline: debug flags, the concurrency environment variable and the
    // command-line config overrides.
    for flag in &opts.debug_flags {
        ctx.call_method1("set_debug_flag", (flag.as_str(),))?;
    }
    if let Some(concurrency) = &opts.concurrency {
        ctx.call_method1("set_concurrency", (concurrency.as_str(),))?;
    }
    ctx.call_method1("apply_cmdline_overrides", (opts.config_overrides.clone(),))?;
    ctx.call_method0("set_debug_flags_from_config")?;

    run_bzr_dispatch(&opts, argv, ctx)
}

/// The command-dispatch portion of [`run_bzr`], after master options have been
/// scanned and their side effects applied.
fn run_bzr_dispatch(
    opts: &MasterOptions,
    mut argv: Vec<String>,
    ctx: &Bound<'_, PyAny>,
) -> PyResult<i32> {
    // Load or disable plugins.
    if opts.no_plugins {
        ctx.call_method0("disable_plugins")?;
    } else {
        let warn = ctx
            .call_method0("warn_plugin_load_problems")?
            .extract::<bool>()?;
        ctx.call_method1("load_plugins", (warn,))?;
    }

    // With no command, show help; with --version, show the version.
    if argv.is_empty() {
        ctx.call_method0("run_help")?;
        return Ok(0);
    }
    if argv[0] == "--version" {
        ctx.call_method0("run_version")?;
        return Ok(0);
    }

    // Expand a user alias for the command name. As in the Python original,
    // ``alias_argv`` is whatever ``get_alias`` returned (``None`` or a list);
    // only a non-empty expansion replaces ``argv[0]`` with its first element.
    let mut alias_argv: Option<Vec<String>> = None;
    if !opts.no_aliases {
        if let Some(mut expanded) = ctx
            .call_method1("get_alias", (argv[0].as_str(),))?
            .extract::<Option<Vec<String>>>()?
        {
            if !expanded.is_empty() {
                argv[0] = expanded.remove(0);
            }
            alias_argv = Some(expanded);
        }
    }

    let cmd_name = argv.remove(0);
    let cmd_obj = ctx.call_method1("get_cmd_object", (cmd_name, !opts.builtin))?;
    if opts.no_l10n {
        ctx.call_method1("set_no_l10n", (&cmd_obj,))?;
    }

    // Save and zero the verbosity level for the duration of the command; the
    // cleanup guard restores it (and resets overrides) on every exit path.
    let saved_verbosity = ctx.call_method0("get_verbosity_level")?.unbind();
    ctx.call_method1("set_verbosity_level", (0,))?;
    let _cleanup = RunBzrCleanup {
        ctx,
        saved_verbosity,
    };

    let (profiler, warnings) = crate::command::select_profiler(opts);
    for warning in warnings {
        ctx.call_method1("warning", (warning,))?;
    }
    let profiler_name = match profiler {
        Profiler::None => "none",
        Profiler::Lsprof => "lsprof",
        Profiler::Profile => "profile",
        Profiler::Coverage => "coverage",
    };
    let ret = ctx.call_method1(
        "run_command",
        (
            &cmd_obj,
            argv,
            alias_argv,
            profiler_name,
            opts.lsprof_file.clone(),
        ),
    )?;
    // ``ret or 0`` in Python: None or 0 both become 0.
    let code = ret.extract::<Option<i32>>()?.unwrap_or(0);
    Ok(code)
}
