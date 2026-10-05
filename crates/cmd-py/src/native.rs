//! Native Rust commands, exposed to Python as subclasses of ``Command``.
//!
//! Each command in `breezy::registry::command_registry` gets a generated
//! ``cmd_<name>`` class deriving from [`NativeCommand`], carrying the class
//! attributes the command machinery reads (help, aliases, options, ...) taken
//! from the Rust command. Lookup, plugin overrides, aliases, hooks and option
//! parsing therefore work as for any Python command; only the body of ``run``
//! is native.

use std::io::Write;

use breezy::command::{CommandContext, CommandError, CommandSpec, MatchedArgs};
use breezy::option::{KwValue, OptionRef, ParsedOptions};
use pyo3::exceptions::{PyKeyError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyModule, PyString, PyTuple};

use crate::commands::Command;

/// The base class of the generated native command classes.
#[pyclass(name = "NativeCommand", module = "breezy._cmd_rs.commands", extends = Command, subclass)]
pub(crate) struct NativeCommand;

#[pymethods]
impl NativeCommand {
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn new(
        _args: &Bound<'_, PyTuple>,
        _kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyClassInitializer<Self> {
        PyClassInitializer::from(Command).add_subclass(NativeCommand)
    }

    /// Run the native command body with the parsed arguments and options.
    #[pyo3(signature = (**kwargs))]
    fn run(slf: &Bound<'_, Self>, kwargs: Option<&Bound<'_, PyDict>>) -> PyResult<i32> {
        let py = slf.py();
        let name: String = slf.getattr("_native_name")?.extract()?;
        let entry = breezy::registry::command_registry()
            .get(&name)
            .ok_or_else(|| PyKeyError::new_err(name.clone()))?;
        let (opts, args) = parse_kwargs(py, &entry.spec, kwargs)?;

        let invoked_as = match slf.getattr("invoked_as")?.extract::<Option<String>>()? {
            Some(invoked_as) => invoked_as,
            None => entry.spec.name.clone(),
        };
        let trace = py.import("breezy.trace")?;
        let verbosity = trace.call_method0("get_verbosity_level")?.extract()?;
        let mut ctx = PyCommandContext {
            out: OutfWriter {
                outf: slf.getattr("outf")?,
                pending: Vec::new(),
                error: None,
            },
            trace,
            invoked_as,
            verbosity,
        };
        let result = entry.command.run(&mut ctx, &opts, &args);
        let flushed = ctx.out.flush();
        // An exception raised by outf.write is the root cause; raise it as itself
        // rather than as the io::Error it was passed through.
        if let Some(err) = ctx.out.error.take() {
            return Err(err);
        }
        let code = result?;
        flushed.map_err(breezy::command::CommandError::from)?;
        Ok(code)
    }
}

/// The [`CommandContext`] of a native command run from its Python class.
struct PyCommandContext<'py> {
    out: OutfWriter<'py>,
    trace: Bound<'py, PyModule>,
    invoked_as: String,
    verbosity: i32,
}

impl CommandContext for PyCommandContext<'_> {
    fn out(&mut self) -> &mut dyn Write {
        &mut self.out
    }

    fn note(&mut self, message: &str) -> Result<(), CommandError> {
        // trace.note takes a %-format; pass the message as its argument so a
        // literal % in it is not interpreted.
        self.trace.call_method1("note", ("%s", message))?;
        Ok(())
    }

    fn warning(&mut self, message: &str) -> Result<(), CommandError> {
        self.trace.call_method1("warning", ("%s", message))?;
        Ok(())
    }

    fn invoked_as(&self) -> &str {
        &self.invoked_as
    }

    fn verbosity(&self) -> i32 {
        self.verbosity
    }
}

/// Sort the keyword arguments ``run`` was called with into the native command's
/// options and positional parameters.
fn parse_kwargs(
    py: Python<'_>,
    spec: &CommandSpec,
    kwargs: Option<&Bound<'_, PyDict>>,
) -> PyResult<(ParsedOptions, MatchedArgs)> {
    let mut values = Vec::new();
    if let Some(kwargs) = kwargs {
        let revision_spec = py.import("breezy.revisionspec")?.getattr("RevisionSpec")?;
        for (key, value) in kwargs.iter() {
            values.push((key.extract()?, kw_value(&value, &revision_spec)?));
        }
    }
    let options = spec
        .options
        .iter()
        .map(OptionRef::resolve)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| pyo3::exceptions::PyKeyError::new_err(e.to_string()))?;
    breezy::option::parse_kwargs(&spec.name, &options, &spec.takes_args, values)
        .map_err(|e| PyTypeError::new_err(e.to_string()))
}

/// Describe the Python `value` passed to a native command's ``run``.
fn kw_value(value: &Bound<'_, PyAny>, revision_spec: &Bound<'_, PyAny>) -> PyResult<KwValue> {
    if value.is_none() {
        return Ok(KwValue::None);
    }
    // bool is a subclass of int, so it has to be checked first.
    if value.is_instance_of::<PyBool>() {
        return Ok(KwValue::Bool(value.extract()?));
    }
    if value.is_instance_of::<PyInt>() {
        return Ok(KwValue::Int(value.extract()?));
    }
    if value.is_instance_of::<PyFloat>() {
        return Ok(KwValue::Float(value.extract()?));
    }
    if value.is_instance_of::<PyString>() {
        return Ok(KwValue::Str(value.extract()?));
    }
    if value.is_instance(revision_spec)? {
        return Ok(KwValue::RevisionSpec(
            value.getattr("user_spec")?.extract()?,
        ));
    }
    if value.is_instance_of::<PyList>() || value.is_instance_of::<PyTuple>() {
        let items = value
            .try_iter()?
            .map(|item| kw_value(&item?, revision_spec))
            .collect::<PyResult<Vec<_>>>()?;
        return Ok(KwValue::Seq(items));
    }
    Err(PyTypeError::new_err(format!(
        "unsupported value for a native command: {}",
        value.repr()?
    )))
}

/// A [`Write`] sink over the command's Python ``outf``, which takes text.
///
/// Bytes are decoded as UTF-8; a multi-byte sequence split across writes is held
/// back until it is complete.
struct OutfWriter<'py> {
    outf: Bound<'py, PyAny>,
    pending: Vec<u8>,
    /// The Python exception raised by ``outf``, if a write failed.
    error: Option<PyErr>,
}

impl Write for OutfWriter<'_> {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.pending.extend_from_slice(buf);
        let valid = match std::str::from_utf8(&self.pending) {
            Ok(text) => text.len(),
            Err(e) if e.error_len().is_none() => e.valid_up_to(),
            Err(e) => return Err(std::io::Error::new(std::io::ErrorKind::InvalidData, e)),
        };
        if valid > 0 {
            let text = std::str::from_utf8(&self.pending[..valid]).expect("validated above");
            if let Err(err) = self.outf.call_method1("write", (text,)) {
                let io_err = std::io::Error::other(err.to_string());
                self.error = Some(err);
                return Err(io_err);
            }
            self.pending.drain(..valid);
        }
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        if self.pending.is_empty() {
            Ok(())
        } else {
            Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "output ends in an incomplete UTF-8 sequence",
            ))
        }
    }
}

/// The ``takes_options`` entry for option `option` of a native command.
///
/// A shared option is named, so that the command uses the live definition in
/// ``Option.OPTIONS``, except a registry option: the native command takes the
/// chosen key, where ``Option.OPTIONS`` converts it to the registered object.
fn takes_option<'py>(py: Python<'py>, option: &OptionRef) -> PyResult<Bound<'py, PyAny>> {
    let def = option
        .resolve()
        .map_err(|e| pyo3::exceptions::PyKeyError::new_err(e.to_string()))?;
    match option {
        OptionRef::Shared(name)
            if !matches!(def.kind, breezy::option::OptionKind::Registry { .. }) =>
        {
            Ok(name.into_pyobject(py)?.into_any())
        }
        _ => crate::optparse::python_option(py, &def, true),
    }
}

/// The class attributes for the generated class of the native command `spec`.
fn class_attrs<'py>(
    py: Python<'py>,
    spec: &CommandSpec,
    module: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let attrs = PyDict::new(py);
    attrs.set_item("__module__", module)?;
    attrs.set_item("_native_name", &spec.name)?;
    if let Some(help) = &spec.help {
        attrs.set_item("__doc__", help)?;
    }
    attrs.set_item("aliases", &spec.aliases)?;
    attrs.set_item("takes_args", &spec.takes_args)?;
    attrs.set_item("hidden", spec.hidden)?;
    attrs.set_item("encoding_type", spec.encoding_type.as_str())?;
    attrs.set_item("_see_also", &spec.see_also)?;
    let options = spec
        .options
        .iter()
        .map(|o| takes_option(py, o))
        .collect::<PyResult<Vec<_>>>()?;
    attrs.set_item("takes_options", options)?;
    if spec.display {
        let run = py.get_type::<NativeCommand>().getattr("run")?;
        let wrapped = py
            .import("breezy.commands")?
            .call_method1("display_command", (run,))?;
        attrs.set_item("run", wrapped)?;
    }
    Ok(attrs)
}

/// The generated ``cmd_*`` classes of the native commands, with their
/// ``__module__`` set to `module`.
#[pyfunction]
pub(crate) fn native_command_classes<'py>(
    py: Python<'py>,
    module: &str,
) -> PyResult<Vec<Bound<'py, PyAny>>> {
    let type_ = py.import("builtins")?.getattr("type")?;
    let base = py.get_type::<NativeCommand>();
    let mut classes = Vec::new();
    for entry in breezy::registry::command_registry().entries() {
        let attrs = class_attrs(py, &entry.spec, module)?;
        let class_name = breezy::command::squish_command_name(&entry.spec.name);
        classes.push(type_.call1((class_name, (base.clone(),), attrs))?);
    }
    Ok(classes)
}
