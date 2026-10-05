//! The Python side of the command machinery.
//!
//! Python commands are subclasses of the Python ``Command`` class rather than
//! implementations of the Rust [`Command`] trait; [`spec_from_python`] reads one
//! into a [`CommandSpec`] for the help system, and [`run_argv_aliases`] drives
//! one.

use crate::command::CommandSpec;
use pyo3::prelude::*;

/// Read the description of the Python command object `cmd`.
///
/// Options are left empty: a Python command's options are Python ``Option``
/// objects, rendered by [`python_option_help`].
pub fn spec_from_python(cmd: &Bound<'_, PyAny>) -> PyResult<CommandSpec> {
    let encoding_type: String = cmd.getattr("encoding_type")?.extract()?;
    Ok(CommandSpec {
        name: cmd.call_method0("name")?.extract()?,
        aliases: cmd.getattr("aliases")?.extract()?,
        takes_args: cmd.getattr("takes_args")?.extract()?,
        help: cmd.call_method0("help")?.extract()?,
        hidden: cmd.getattr("hidden")?.extract()?,
        encoding_type: encoding_type.parse()?,
        see_also: python_see_also(cmd)?,
        plugin_name: cmd.call_method0("plugin_name")?.extract()?,
        display: false,
        options: Vec::new(),
    })
}

/// The ``_see_also`` terms of the Python command `cmd`; a command without the
/// attribute has none.
pub fn python_see_also(cmd: &Bound<'_, PyAny>) -> PyResult<Vec<String>> {
    match cmd.getattr_opt("_see_also")? {
        Some(v) if !v.is_none() => v.extract(),
        _ => Ok(Vec::new()),
    }
}

/// The options block of the help for the Python command `cmd`, rendered by the
/// option parser built from its options.
pub fn python_option_help(cmd: &Bound<'_, PyAny>) -> PyResult<String> {
    let py = cmd.py();
    let items = cmd.call_method0("options")?.call_method0("items")?;
    let sorted = py.import("builtins")?.call_method1("sorted", (items,))?;
    let values = pyo3::types::PyList::empty(py);
    for pair in sorted.try_iter()? {
        values.append(pair?.get_item(1)?)?;
    }
    py.import("breezy.option")?
        .call_method1("get_optparser", (values,))?
        .call_method0("format_option_help")?
        .extract()
}

/// Parse the command line and run the Python command `cmd`.
///
/// Handles the standard ``--help``/``--usage`` early returns, links the
/// ``verbose`` / ``quiet`` standard options to the global verbosity, runs the
/// command body and resets verbosity afterwards.
pub fn run_argv_aliases(
    cmd: &Bound<'_, PyAny>,
    argv: Vec<String>,
    alias_argv: Option<Vec<String>>,
) -> PyResult<Py<PyAny>> {
    let py = cmd.py();

    // A parse error propagates without triggering the cleanup below.
    let (args, opts) = crate::options::parse_args(cmd, argv, alias_argv)?;
    cmd.call_method0("_setup_outf")?;

    if opts.contains("help")? {
        write_help(cmd, true)?;
        return Ok(ok_outcome(py));
    }
    if opts.contains("usage")? {
        write_help(cmd, false)?;
        return Ok(ok_outcome(py));
    }

    set_verbosity_level(py, crate::options::verbosity_level())?;
    let std: Vec<String> = cmd.getattr("supported_std_options")?.extract()?;
    for name in ["verbose", "quiet"] {
        let is_on = if name == "verbose" {
            is_verbose(py)?
        } else {
            is_quiet(py)?
        };
        if std.iter().any(|o| o == name) {
            opts.set_item(name, is_on)?;
        } else if opts.contains(name)? {
            opts.del_item(name)?;
        }
    }

    let outcome = run_parsed(cmd, &args, &opts);

    // Log the transport activity, then reset the verbosity so the next command
    // in this process does not inherit it. Both steps run whether the body
    // returned or raised, and neither may replace the outcome - a failure to
    // log must not lose the command's own error, and must not skip the
    // verbosity reset either.
    let logged = bytes_debug_enabled(py).and_then(|display| log_transport_activity(py, display));
    let reset = set_verbosity_level(py, 0);

    // A cleanup failure is only reported when the command itself succeeded;
    // otherwise the command's error is the one worth propagating.
    match outcome {
        Ok(value) => logged.and(reset).map(|()| value),
        Err(err) => {
            for cleanup_err in [logged, reset].into_iter().filter_map(Result::err) {
                log::debug!(target: "brz", "error during command cleanup: {cleanup_err}");
            }
            Err(err)
        }
    }
}

/// Write `cmd`'s help to its ``outf`` (the ``--help`` / ``--usage`` early return).
fn write_help(cmd: &Bound<'_, PyAny>, verbose: bool) -> PyResult<()> {
    let help = crate::commands::get_help_text(cmd.py(), cmd, None, true, false, verbose)?;
    cmd.getattr("outf")?.call_method1("write", (help,))?;
    Ok(())
}

/// Run the command body with the parsed args and options (``self.run(**kwargs)``).
fn run_parsed(
    cmd: &Bound<'_, PyAny>,
    args: &Bound<'_, PyAny>,
    opts: &Bound<'_, pyo3::types::PyDict>,
) -> PyResult<Py<PyAny>> {
    let py = cmd.py();
    let commands = py.import("breezy.commands")?;
    // _match_argform validates the required positional arguments; it runs
    // after the --help/--usage checks, so those work without them.
    let cmdargs = commands
        .call_method1(
            "_match_argform",
            (cmd.call_method0("name")?, cmd.getattr("takes_args")?, args),
        )?
        .extract::<Bound<'_, pyo3::types::PyDict>>()?;
    // Merge in the options, with hyphens in their names turned into underscores.
    let all = cmdargs.copy()?;
    for (k, v) in opts.iter() {
        let key: String = k.extract()?;
        all.set_item(key.replace('-', "_"), v)?;
    }
    cmd.call_method("run", (), Some(&all)).map(|v| v.unbind())
}

/// The exit-code outcome for a help/usage early return (0 as a Python object).
fn ok_outcome(py: Python<'_>) -> Py<PyAny> {
    0i32.into_pyobject(py).unwrap().into_any().unbind()
}

/// Set the global verbosity level (``trace.set_verbosity_level``).
fn set_verbosity_level(py: Python<'_>, level: i32) -> PyResult<()> {
    py.import("breezy.trace")?
        .call_method1("set_verbosity_level", (level,))?;
    Ok(())
}

/// Whether output is currently verbose (``trace.is_verbose``).
fn is_verbose(py: Python<'_>) -> PyResult<bool> {
    py.import("breezy.trace")?
        .call_method0("is_verbose")?
        .is_truthy()
}

/// Whether output is currently quiet (``trace.is_quiet``).
fn is_quiet(py: Python<'_>) -> PyResult<bool> {
    py.import("breezy.trace")?
        .call_method0("is_quiet")?
        .is_truthy()
}

/// Log transport activity after a command run, displaying byte counts when the
/// ``bytes`` debug flag is enabled.
fn log_transport_activity(py: Python<'_>, display: bool) -> PyResult<()> {
    let kwargs = pyo3::types::PyDict::new(py);
    kwargs.set_item("display", display)?;
    py.import("breezy.ui")?.getattr("ui_factory")?.call_method(
        "log_transport_activity",
        (),
        Some(&kwargs),
    )?;
    Ok(())
}

/// Whether the ``bytes`` debug flag is enabled.
fn bytes_debug_enabled(py: Python<'_>) -> PyResult<bool> {
    py.import("breezy.debug")?
        .call_method1("debug_flag_enabled", ("bytes",))?
        .is_truthy()
}
