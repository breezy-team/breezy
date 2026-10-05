//! Python bindings for command-line option handling.
//!
//! These expose the Rust option model and parser to Python: the `Option` base
//! class (and the registry-backed subclass), the parser driving the Python
//! options' conversions and callbacks, the shared option definitions, and the
//! parse-time verbosity counter.

use pyo3::import_exception;
use pyo3::prelude::*;
use pyo3::types::PyTuple;

import_exception!(breezy.errors, CommandError);

/// Split a revision string on the ``..`` range separator (not before ``/``/``\``).
#[pyfunction]
pub(crate) fn split_revision_range(revstr: &str) -> Vec<String> {
    breezy::options::split_revision_range(revstr)
}

/// Read the parse-time verbosity level (the counter ``-v`` / ``-q`` set).
#[pyfunction]
pub(crate) fn verbosity_level() -> i32 {
    breezy::options::verbosity_level()
}

/// Set the parse-time verbosity level.
#[pyfunction]
pub(crate) fn set_verbosity_level(level: i32) {
    breezy::options::set_verbosity_level(level)
}

/// Apply a ``-v`` / ``-q`` switch to the verbosity level, returning the new
/// level. `verbose` selects the direction; `value` is the switch's truthiness
/// (false for ``--no-verbose`` / ``--no-quiet``, which reset to 0).
#[pyfunction]
pub(crate) fn apply_verbosity(verbose: bool, value: bool) -> i32 {
    breezy::options::apply_verbosity(verbose, value)
}

/// A command-line option definition.
///
/// It is ``subclass``-able and carries a per-instance ``dict`` because
/// ``ListOption``, ``RegistryOption`` and the option definitions across the
/// codebase hold Python values (the ``type`` conversion callable, the
/// ``custom_callback``, registries) and rely on ``isinstance``. The pure string
/// logic (negation name, param-name derivation, argname rules) is in
/// [`breezy::options`].
#[pyclass(name = "Option", module = "breezy._cmd_rs.optparse", subclass, dict)]
pub(crate) struct PyOption {
    #[pyo3(get, set)]
    name: String,
    #[pyo3(get, set)]
    help: Py<PyAny>,
    #[pyo3(get, set)]
    r#type: Py<PyAny>,
    #[pyo3(get, set)]
    argname: Option<String>,
    _short_name: Option<String>,
    #[pyo3(get, set)]
    _param_name: String,
    #[pyo3(get, set)]
    custom_callback: Py<PyAny>,
    #[pyo3(get, set)]
    hidden: bool,
}

#[pymethods]
impl PyOption {
    // Accept and ignore constructor args: subclasses (ListOption/RegistryOption
    // and plugin options) have their own __init__ signatures, which route their
    // args through __new__ (a pyclass has only __new__). The fields are filled
    // by __init__ (called for the common `Option(name, ...)` case, and via
    // `Option.__init__(self, ...)` from subclasses).
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn new(
        py: Python<'_>,
        _args: &Bound<'_, PyTuple>,
        _kwargs: Option<&Bound<'_, pyo3::types::PyDict>>,
    ) -> Self {
        PyOption {
            name: String::new(),
            help: py.None(),
            r#type: py.None(),
            argname: None,
            _short_name: None,
            _param_name: String::new(),
            custom_callback: py.None(),
            hidden: false,
        }
    }

    #[pyo3(signature = (
        name, help=None, r#type=None, argname=None, short_name=None,
        param_name=None, custom_callback=None, hidden=false
    ))]
    #[allow(clippy::too_many_arguments)]
    fn __init__(
        &mut self,
        py: Python<'_>,
        name: String,
        help: Option<Py<PyAny>>,
        r#type: Option<Py<PyAny>>,
        argname: Option<String>,
        short_name: Option<String>,
        param_name: Option<String>,
        custom_callback: Option<Py<PyAny>>,
        hidden: bool,
    ) -> PyResult<()> {
        let has_type = r#type.as_ref().is_some_and(|t| !t.is_none(py));
        self.argname = breezy::options::resolve_argname(has_type, argname.as_deref())
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        self._param_name = breezy::options::param_name(&name, param_name.as_deref());
        self.name = name;
        self.help = match help {
            Some(h) => h,
            None => "".into_pyobject(py)?.into_any().unbind(),
        };
        self.r#type = r#type.unwrap_or_else(|| py.None());
        self._short_name = short_name;
        self.custom_callback = custom_callback.unwrap_or_else(|| py.None());
        self.hidden = hidden;
        Ok(())
    }

    /// The short option letter, or ``None``.
    fn short_name(&self) -> Option<String> {
        self._short_name.clone().filter(|s| !s.is_empty())
    }

    /// Set the short option letter.
    fn set_short_name(&mut self, short_name: String) {
        self._short_name = Some(short_name);
    }

    /// The negated form of the option name (``no-`` prefix toggled).
    fn get_negation_name(&self) -> String {
        breezy::options::negation_name(&self.name)
    }

    /// Iterate the switches this option provides: ``(name, short, argname, help)``.
    fn iter_switches(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        let argname = self.argname.as_ref().map(|a| a.to_uppercase());
        let tuple = (
            self.name.clone(),
            self.short_name(),
            argname,
            self.help.bind(py),
        )
            .into_pyobject(py)?;
        Ok(vec![tuple.into_any().unbind()])
    }

    /// Whether this option is hidden from help (the `name` arg is unused here).
    #[pyo3(signature = (_name=None))]
    fn is_hidden(&self, _name: Option<&str>) -> bool {
        self.hidden
    }

    /// Shallow-copy this option, preserving the concrete subclass.
    ///
    /// ``copy.copy`` is used by ``custom_help`` to clone a standard option and
    /// override its help. A pyclass is not copyable by default, so reproduce the
    /// plain-object behaviour: a new same-typed instance with the pyclass fields
    /// and the instance ``__dict__`` carried over (a shallow copy).
    fn __copy__(slf: &Bound<'_, Self>) -> PyResult<Py<PyAny>> {
        let py = slf.py();
        let me = slf.borrow();
        let clone = PyOption {
            name: me.name.clone(),
            help: me.help.clone_ref(py),
            r#type: me.r#type.clone_ref(py),
            argname: me.argname.clone(),
            _short_name: me._short_name.clone(),
            _param_name: me._param_name.clone(),
            custom_callback: me.custom_callback.clone_ref(py),
            hidden: me.hidden,
        };
        // Build an instance of the concrete type (Option or a subclass) without
        // running __init__, then install the pyclass state and copy __dict__.
        let cls = slf.get_type();
        let obj = cls.call_method1("__new__", (&cls,))?;
        obj.cast::<Self>()?.borrow_mut().clone_from_fields(clone);
        if let Ok(src_dict) = slf.getattr("__dict__") {
            obj.getattr("__dict__")?
                .call_method1("update", (src_dict,))?;
        }
        Ok(obj.unbind())
    }
}

/// An option whose values come from a [`Registry`].
///
/// The registry may be supplied directly or lazily as a ``(module, attribute)``
/// pair resolved on first use. ``value_switches`` gives each registry key its own
/// ``--key`` switch; ``enum_switch`` additionally provides ``--name=KEY``.
#[pyclass(name = "RegistryOption", module = "breezy._cmd_rs.optparse", extends = PyOption, subclass, dict)]
pub(crate) struct RegistryOption {
    /// The registry, once known; `None` until a lazy registry is resolved.
    registry: Option<Py<PyAny>>,
    /// The lazy getter, when built from `lazy_registry`.
    lazy_registry: Option<Py<PyAny>>,
    #[pyo3(get, set)]
    converter: Py<PyAny>,
    #[pyo3(get, set)]
    value_switches: bool,
    #[pyo3(get, set)]
    enum_switch: bool,
    #[pyo3(get, set)]
    short_value_switches: Py<PyAny>,
    #[pyo3(get, set)]
    title: Py<PyAny>,
}

#[pymethods]
impl RegistryOption {
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    fn new(
        py: Python<'_>,
        _args: &Bound<'_, PyTuple>,
        _kwargs: Option<&Bound<'_, pyo3::types::PyDict>>,
    ) -> PyClassInitializer<Self> {
        PyClassInitializer::from(PyOption::new(py, _args, _kwargs)).add_subclass(RegistryOption {
            registry: None,
            lazy_registry: None,
            converter: py.None(),
            value_switches: false,
            enum_switch: true,
            short_value_switches: py.None(),
            title: py.None(),
        })
    }

    #[pyo3(signature = (
        name, help, registry=None, converter=None, value_switches=false,
        title=None, enum_switch=true, lazy_registry=None, short_name=None,
        short_value_switches=None
    ))]
    #[allow(clippy::too_many_arguments)]
    fn __init__(
        slf: &Bound<'_, Self>,
        py: Python<'_>,
        name: String,
        help: Py<PyAny>,
        registry: Option<Py<PyAny>>,
        converter: Option<Py<PyAny>>,
        value_switches: bool,
        title: Option<Py<PyAny>>,
        enum_switch: bool,
        lazy_registry: Option<(String, String)>,
        short_name: Option<String>,
        short_value_switches: Option<Py<PyAny>>,
    ) -> PyResult<()> {
        // Option.__init__(self, name, help, type=self.convert, short_name=...)
        // - the type is the bound convert method, so parsing runs it.
        let convert = slf.getattr("convert")?;
        slf.as_super().borrow_mut().__init__(
            py,
            name.clone(),
            Some(help),
            Some(convert.unbind()),
            None,
            short_name,
            None,
            None,
            false,
        )?;

        let registry_given = registry.as_ref().is_some_and(|r| !r.is_none(py));
        let lazy = if registry_given {
            if lazy_registry.is_some() {
                return Err(pyo3::exceptions::PyAssertionError::new_err(
                    "registry and lazy_registry are mutually exclusive",
                ));
            }
            None
        } else {
            let Some((module, member)) = lazy_registry else {
                return Err(pyo3::exceptions::PyAssertionError::new_err(
                    "One of registry or lazy_registry must be given.",
                ));
            };
            Some(
                py.import("breezy.registry")?
                    .getattr("_LazyObjectGetter")?
                    .call1((module, member))?
                    .unbind(),
            )
        };

        let mut me = slf.borrow_mut();
        me.registry = registry.filter(|_| registry_given);
        me.lazy_registry = lazy;
        me.converter = converter.unwrap_or_else(|| py.None());
        me.value_switches = value_switches;
        me.enum_switch = enum_switch;
        me.short_value_switches = short_value_switches.unwrap_or_else(|| py.None());
        // The title defaults to the option name.
        me.title = match title.filter(|t| !t.is_none(py)) {
            Some(t) => t,
            None => name.into_pyobject(py)?.into_any().unbind(),
        };
        Ok(())
    }

    /// The registry, resolving a lazy one on first use.
    #[getter]
    fn registry(slf: &Bound<'_, Self>) -> PyResult<Py<PyAny>> {
        let py = slf.py();
        if let Some(reg) = &slf.borrow().registry {
            return Ok(reg.clone_ref(py));
        }
        let lazy = slf
            .borrow()
            .lazy_registry
            .as_ref()
            .ok_or_else(|| {
                pyo3::exceptions::PyAssertionError::new_err(
                    "One of registry or lazy_registry must be given.",
                )
            })?
            .clone_ref(py);
        let reg = lazy.bind(py).call_method0("get_obj")?.unbind();
        slf.borrow_mut().registry = Some(reg.clone_ref(py));
        Ok(reg)
    }

    /// Raise ``BadOptionValue`` unless `value` names a registry entry.
    fn validate_value(slf: &Bound<'_, Self>, value: &Bound<'_, PyAny>) -> PyResult<()> {
        let py = slf.py();
        if Self::registry(slf)?.bind(py).contains(value)? {
            return Ok(());
        }
        let name = slf.as_super().borrow().name.clone();
        Err(PyErr::from_value(
            py.import("breezy.option")?
                .getattr("BadOptionValue")?
                .call1((name, value))?,
        ))
    }

    /// Convert a value name into the registered object (the option's ``type``).
    fn convert(slf: &Bound<'_, Self>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let py = slf.py();
        Self::validate_value(slf, value)?;
        let converter = slf.borrow().converter.clone_ref(py);
        if converter.is_none(py) {
            Ok(Self::registry(slf)?
                .bind(py)
                .call_method1("get", (value,))?
                .unbind())
        } else {
            Ok(converter.bind(py).call1((value,))?.unbind())
        }
    }

    /// Build a registry option whose values are plain strings, from keyword
    /// arguments naming each value and its help.
    #[staticmethod]
    #[pyo3(signature = (name_, help=None, title=None, value_switches=false, enum_switch=true, **kwargs))]
    fn from_kwargs(
        py: Python<'_>,
        name_: String,
        help: Option<String>,
        title: Option<Py<PyAny>>,
        value_switches: bool,
        enum_switch: bool,
        kwargs: Option<&Bound<'_, pyo3::types::PyDict>>,
    ) -> PyResult<Py<PyAny>> {
        let reg = py.import("breezy.registry")?.getattr("Registry")?.call0()?;
        let mut help = help;
        if let Some(kwargs) = kwargs {
            let mut items: Vec<(String, String)> = Vec::new();
            for (k, v) in kwargs.iter() {
                items.push((k.extract()?, v.extract()?));
            }
            items.sort();
            for (name, switch_help) in items {
                let name = name.replace('_', "-");
                let kw = pyo3::types::PyDict::new(py);
                kw.set_item("help", &switch_help)?;
                reg.call_method("register", (&name, &name), Some(&kw))?;
                if !value_switches {
                    // Fold each value's help into the option help instead.
                    let mut h = help.unwrap_or_default();
                    h.push_str(&format!("  \"{name}\": {switch_help}"));
                    if !h.ends_with('.') {
                        h.push('.');
                    }
                    help = Some(h);
                }
            }
        }
        let kw = pyo3::types::PyDict::new(py);
        kw.set_item("title", title)?;
        kw.set_item("value_switches", value_switches)?;
        kw.set_item("enum_switch", enum_switch)?;
        Ok(py
            .import("breezy.option")?
            .getattr("RegistryOption")?
            .call((name_, help, reg), Some(&kw))?
            .unbind())
    }

    /// Iterate the switches this option provides, including its value switches.
    fn iter_switches(slf: &Bound<'_, Self>, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        let mut out = slf.as_super().borrow().iter_switches(py)?;
        if slf.borrow().value_switches {
            let registry = Self::registry(slf)?;
            let registry = registry.bind(py);
            let mut keys: Vec<String> = registry.call_method0("keys")?.extract()?;
            keys.sort();
            for key in keys {
                let help = registry.call_method1("get_help", (&key,))?;
                out.push(
                    (key, py.None(), py.None(), help)
                        .into_pyobject(py)?
                        .into_any()
                        .unbind(),
                );
            }
        }
        Ok(out)
    }

    /// Whether `name` is an alias of a registry key (rather than the option).
    fn is_alias(slf: &Bound<'_, Self>, name: &str) -> PyResult<bool> {
        let py = slf.py();
        if name == slf.as_super().borrow().name {
            return Ok(false);
        }
        Self::registry(slf)?
            .bind(py)
            .call_method0("aliases")?
            .contains(name)
    }

    /// Whether the named option or registry key should be hidden from help.
    #[pyo3(signature = (name=None))]
    fn is_hidden(slf: &Bound<'_, Self>, name: Option<&str>) -> PyResult<bool> {
        let py = slf.py();
        let own = slf.as_super().borrow().name.clone();
        if name.is_some_and(|n| n == own) {
            return Ok(slf.as_super().borrow().is_hidden(name));
        }
        let info = Self::registry(slf)?
            .bind(py)
            .call_method1("get_info", (name,))?;
        match info.getattr_opt("hidden")? {
            Some(hidden) => hidden.is_truthy(),
            None => Ok(false),
        }
    }
}

impl PyOption {
    /// Overwrite the pyclass fields from `other` (used by ``__copy__``).
    fn clone_from_fields(&mut self, other: PyOption) {
        self.name = other.name;
        self.help = other.help;
        self.r#type = other.r#type;
        self.argname = other.argname;
        self._short_name = other._short_name;
        self._param_name = other._param_name;
        self.custom_callback = other.custom_callback;
        self.hidden = other.hidden;
    }
}

/// The ``breezy.option`` type callable converting the argument of a value
/// option of `kind`.
fn value_type<'py>(
    py: Python<'py>,
    kind: breezy::option::ValueKind,
) -> PyResult<Bound<'py, PyAny>> {
    use breezy::option::ValueKind;
    match kind {
        ValueKind::Str => py.import("builtins")?.getattr("str"),
        ValueKind::Int => py.import("builtins")?.getattr("int"),
        ValueKind::Float => py.import("builtins")?.getattr("float"),
        ValueKind::RevisionRange => py.import("breezy.option")?.getattr("_parse_revision_str"),
        ValueKind::Change => py.import("breezy.option")?.getattr("_parse_change_str"),
    }
}

/// Build the ``breezy.option`` option object for `def`.
///
/// With `keys`, a registry option's value is the chosen key rather than the
/// registered object; native commands take keys.
pub(crate) fn python_option<'py>(
    py: Python<'py>,
    def: &breezy::option::OptionDef,
    keys: bool,
) -> PyResult<Bound<'py, PyAny>> {
    use breezy::option::{Choices, OptionKind};

    let module = py.import("breezy.option")?;
    let kwargs = pyo3::types::PyDict::new(py);
    if let Some(short) = def.short {
        kwargs.set_item("short_name", short.to_string())?;
    }
    let class = match &def.kind {
        OptionKind::Flag => "Option",
        OptionKind::Value(kind) => {
            kwargs.set_item("type", value_type(py, *kind)?)?;
            "Option"
        }
        OptionKind::List(kind) => {
            kwargs.set_item("type", value_type(py, *kind)?)?;
            "ListOption"
        }
        OptionKind::Registry {
            choices,
            value_switches,
            enum_switch,
            title,
            short_value_switches,
        } => {
            match choices {
                Choices::Fixed(choices) => {
                    let registry = py.import("breezy.registry")?.getattr("Registry")?.call0()?;
                    for choice in choices {
                        let choice_kwargs = pyo3::types::PyDict::new(py);
                        choice_kwargs.set_item("help", &choice.help)?;
                        registry.call_method(
                            "register",
                            (&choice.key, &choice.key),
                            Some(&choice_kwargs),
                        )?;
                    }
                    kwargs.set_item("registry", registry)?;
                }
                Choices::Registry(r) => {
                    kwargs.set_item("lazy_registry", (&r.module, &r.attribute))?;
                }
            }
            if keys {
                kwargs.set_item("converter", py.import("builtins")?.getattr("str")?)?;
            }
            kwargs.set_item("value_switches", value_switches)?;
            kwargs.set_item("enum_switch", enum_switch)?;
            kwargs.set_item("title", title)?;
            if !short_value_switches.is_empty() {
                let shorts = pyo3::types::PyDict::new(py);
                for (key, short) in short_value_switches {
                    shorts.set_item(key, short.to_string())?;
                }
                kwargs.set_item("short_value_switches", shorts)?;
            }
            if def.param_name.is_some() || def.argname.is_some() || def.hidden {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "registry option {} can not have a parameter name, argument name or be hidden",
                    def.name
                )));
            }
            return module
                .getattr("RegistryOption")?
                .call((&def.name, &def.help), Some(&kwargs));
        }
    };
    kwargs.set_item("help", &def.help)?;
    kwargs.set_item("param_name", &def.param_name)?;
    kwargs.set_item("argname", &def.argname)?;
    kwargs.set_item("hidden", def.hidden)?;
    module.getattr(class)?.call((&def.name,), Some(&kwargs))
}

/// The options shared between commands, as ``breezy.option`` objects, for
/// ``Option.OPTIONS``.
#[pyfunction]
pub(crate) fn shared_options(py: Python<'_>) -> PyResult<Vec<Bound<'_, PyAny>>> {
    breezy::option::shared_options()
        .iter()
        .map(|def| python_option(py, def, false))
        .collect()
}

/// The short switch of registry `option`'s value `key`, if it has one.
fn short_value_switch(option: &Bound<'_, PyAny>, key: &Bound<'_, PyAny>) -> PyResult<Option<char>> {
    let shorts = option.getattr("short_value_switches")?;
    if shorts.is_truthy()? && shorts.contains(key)? {
        Ok(Some(shorts.get_item(key)?.extract()?))
    } else {
        Ok(None)
    }
}

/// How a Python option is parsed, and its default before parsing.
fn parser_option<'py>(
    py: Python<'py>,
    option: &Bound<'py, PyAny>,
) -> PyResult<(breezy::optparse::ParserOption, Option<Bound<'py, PyAny>>)> {
    use breezy::optparse::{ParserOption, Shape};

    let module = py.import("breezy.option")?;
    let name: String = option.getattr("name")?.extract()?;
    let short: Option<char> = option.call_method0("short_name")?.extract()?;
    let param: String = option.getattr("_param_name")?.extract()?;
    let (shape, default) = if option.is_instance(&module.getattr("ListOption")?)? {
        (Shape::List, None)
    } else if option.is_instance(&module.getattr("RegistryOption")?)? {
        let mut value_switches = Vec::new();
        if option.getattr("value_switches")?.is_truthy()? {
            let registry = option.getattr("registry")?;
            let aliases = registry.call_method0("aliases")?;
            for key in registry.call_method0("keys")?.try_iter()? {
                let key = key?;
                if aliases.contains(&key)? {
                    continue;
                }
                let short = short_value_switch(option, &key)?;
                value_switches.push((key.extract()?, short));
            }
        }
        let enum_switch = option.getattr("enum_switch")?.is_truthy()?;
        // Only --name=KEY is an option taking an argument.
        let default = if enum_switch {
            Some(module.getattr("OptionParser")?.getattr("DEFAULT_VALUE")?)
        } else {
            None
        };
        (
            Shape::Registry {
                enum_switch,
                value_switches,
            },
            default,
        )
    } else if option.getattr("type")?.is_none() {
        (Shape::Flag, None)
    } else {
        let default = module.getattr("OptionParser")?.getattr("DEFAULT_VALUE")?;
        (Shape::Value, Some(default))
    };
    Ok((
        ParserOption {
            name,
            short,
            param,
            shape,
        },
        default,
    ))
}

/// The option parser for a command's options.
///
/// Each parse fills a new ``values`` (a ``breezy.option.OptionValues``), in
/// which each list option defaults to an empty list and each option taking an
/// argument to ``OptionParser.DEFAULT_VALUE``.
#[pyclass(name = "Parser", module = "breezy._cmd_rs.optparse")]
pub(crate) struct Parser {
    options: Vec<Py<PyAny>>,
    parser_options: Vec<breezy::optparse::ParserOption>,
    /// The parameters with a default, and the default; `None` for an empty list.
    defaults: Vec<(String, Option<Py<PyAny>>)>,
    /// The values of the last parse.
    #[pyo3(get)]
    values: Py<PyAny>,
}

impl Parser {
    /// A new ``OptionValues`` holding the defaults.
    fn fresh_values<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let values = py
            .import("breezy.option")?
            .getattr("OptionValues")?
            .call0()?;
        for (param, default) in &self.defaults {
            match default {
                Some(default) => values.setattr(param.as_str(), default)?,
                None => values.setattr(param.as_str(), pyo3::types::PyList::empty(py))?,
            }
        }
        Ok(values)
    }
}

#[pymethods]
impl Parser {
    #[new]
    fn new(py: Python<'_>, options: Vec<Bound<'_, PyAny>>) -> PyResult<Self> {
        let mut parser_options = Vec::new();
        let mut defaults = Vec::new();
        for option in &options {
            let (parser_option, default) = parser_option(py, option)?;
            match (&parser_option.shape, default) {
                (breezy::optparse::Shape::List, _) => {
                    defaults.push((parser_option.param.clone(), None))
                }
                (_, Some(default)) => {
                    defaults.push((parser_option.param.clone(), Some(default.unbind())))
                }
                (_, None) => {}
            }
            parser_options.push(parser_option);
        }
        let mut parser = Parser {
            options: options.into_iter().map(Bound::unbind).collect(),
            parser_options,
            defaults,
            values: py.None(),
        };
        parser.values = parser.fresh_values(py)?.unbind();
        Ok(parser)
    }

    /// Parse `args`, returning ``(values, remaining_args)``.
    fn parse_args<'py>(
        slf: &Bound<'py, Self>,
        args: Vec<String>,
    ) -> PyResult<(Py<PyAny>, Vec<String>)> {
        let py = slf.py();
        let values = slf.borrow().fresh_values(py)?;
        // Callbacks are given the parser, and may look at its values.
        slf.borrow_mut().values = values.clone().unbind();
        let parser_options = slf.borrow().parser_options.clone();
        let mut handler = PyHandler {
            parser: slf.clone(),
            values: values.clone(),
        };
        let parsed =
            breezy::optparse::parse(&parser_options, args, &mut handler).map_err(|e| match e {
                breezy::optparse::ParseError::Option(e) => CommandError::new_err(e.to_string()),
                breezy::optparse::ParseError::Handler(e) => e,
            })?;
        Ok((values.unbind(), parsed.args))
    }

    /// The options help: ``Options:`` and each option's switches and help,
    /// with a registry option's value switches grouped under its title.
    fn format_option_help(&self, py: Python<'_>) -> PyResult<String> {
        use breezy::options::{option_string, value_switch_string, HelpEntry};

        // The switches are those the optparse-based parser had, including the
        // hidden ones, which count towards the help column.
        let shown = |help: Bound<'_, PyAny>, hidden: bool| -> PyResult<Option<String>> {
            if hidden {
                Ok(None)
            } else if help.is_truthy()? {
                Ok(Some(breezy::i18n::gettext(&help.extract::<String>()?)))
            } else {
                Ok(Some(String::new()))
            }
        };
        let mut main = Vec::new();
        let mut groups = Vec::new();
        for (option, parser_option) in self.options.iter().zip(&self.parser_options) {
            let option = option.bind(py);
            let name = parser_option.name.as_str();
            let short = parser_option.short.map(|c| c.to_string());
            let argname: Option<String> = option.getattr("argname")?.extract()?;
            let hidden = option.getattr("hidden")?.is_truthy()?;
            let value_entry = |hidden: bool| -> PyResult<HelpEntry> {
                Ok(HelpEntry {
                    switches: option_string(name, short.as_deref(), argname.as_deref(), true),
                    help: shown(option.getattr("help")?, hidden)?,
                })
            };
            match &parser_option.shape {
                breezy::optparse::Shape::Flag => {
                    main.push(HelpEntry {
                        switches: option_string(name, short.as_deref(), None, false),
                        help: shown(option.getattr("help")?, hidden)?,
                    });
                    main.push(HelpEntry {
                        switches: format!("--{}", breezy::options::negation_name(name)),
                        help: None,
                    });
                }
                breezy::optparse::Shape::Value => main.push(value_entry(hidden)?),
                // A list option's help is shown even if it is hidden.
                breezy::optparse::Shape::List => main.push(value_entry(false)?),
                breezy::optparse::Shape::Registry { enum_switch, .. } => {
                    if !option.getattr("value_switches")?.is_truthy()? {
                        if *enum_switch {
                            main.push(value_entry(hidden)?);
                        }
                        continue;
                    }
                    let mut entries = Vec::new();
                    if *enum_switch {
                        entries.push(value_entry(hidden)?);
                    }
                    let registry = option.getattr("registry")?;
                    let aliases = registry.call_method0("aliases")?;
                    let alias_map = registry.call_method0("alias_map")?;
                    for key in registry.call_method0("keys")?.try_iter()? {
                        let key = key?;
                        if aliases.contains(&key)? {
                            continue;
                        }
                        let mut names: Vec<String> = vec![key.extract()?];
                        if let Some(key_aliases) = alias_map
                            .call_method1("get", (&key,))?
                            .extract::<Option<Vec<String>>>()?
                        {
                            for alias in key_aliases {
                                if !option.call_method1("is_hidden", (&alias,))?.is_truthy()? {
                                    names.push(alias);
                                }
                            }
                        }
                        let key_hidden = option.call_method1("is_hidden", (&key,))?.is_truthy()?;
                        entries.push(HelpEntry {
                            switches: value_switch_string(
                                &names,
                                short_value_switch(option, &key)?,
                            ),
                            help: shown(registry.call_method1("get_help", (&key,))?, key_hidden)?,
                        });
                    }
                    groups.push((option.getattr("title")?.extract::<String>()?, entries));
                }
            }
        }
        Ok(breezy::options::format_option_help(
            &main,
            &groups,
            breezy::options::help_width_from_env(),
        ))
    }
}

/// Converts option arguments with the Python options' ``type`` and runs their
/// ``custom_callback``s, recording each value in the parser's ``values``.
struct PyHandler<'py> {
    parser: Bound<'py, Parser>,
    values: Bound<'py, PyAny>,
}

impl<'py> PyHandler<'py> {
    fn option(&self, index: usize) -> Bound<'py, PyAny> {
        self.parser.borrow().options[index]
            .bind(self.parser.py())
            .clone()
    }
}

impl<'py> breezy::optparse::Handler for PyHandler<'py> {
    type Value = Py<PyAny>;
    type Error = PyErr;

    fn convert(
        &mut self,
        index: usize,
        raw: &str,
        via: breezy::optparse::Via,
    ) -> PyResult<Py<PyAny>> {
        let py = self.parser.py();
        let option = self.option(index);
        match option.getattr("type")?.call1((raw,)) {
            Ok(value) => Ok(value.unbind()),
            // Only an argument given to the option is reported as an invalid
            // value; a list item or value switch fails with its own error.
            Err(e)
                if via == breezy::optparse::Via::Argument
                    && e.is_instance_of::<pyo3::exceptions::PyValueError>(py) =>
            {
                let option_spec = &self.parser.borrow().parser_options[index];
                let mut names = Vec::new();
                if let Some(short) = option_spec.short {
                    names.push(format!("-{short}"));
                }
                names.push(format!("--{}", option_spec.name));
                let err = CommandError::new_err(format!(
                    "invalid value for option {}: {raw}",
                    names.join("/")
                ));
                err.set_cause(py, Some(e));
                Err(err)
            }
            Err(e) => Err(e),
        }
    }

    fn set(
        &mut self,
        index: usize,
        value: &breezy::optparse::Parsed<Py<PyAny>>,
        via: breezy::optparse::Via,
    ) -> PyResult<()> {
        use breezy::optparse::Parsed;
        let py = self.parser.py();
        let option = self.option(index);
        let param = self.parser.borrow().parser_options[index].param.clone();
        let value = match value {
            Parsed::Bool(b) => pyo3::types::PyBool::new(py, *b).to_owned().into_any(),
            Parsed::Value(v) => v.bind(py).clone(),
            Parsed::List(items) => {
                pyo3::types::PyList::new(py, items.iter().map(|i| i.bind(py)))?.into_any()
            }
        };
        self.values.setattr(param.as_str(), &value)?;
        let callback = option.getattr("custom_callback")?;
        if !callback.is_none() {
            // A value option's callback is given the option name; the others are
            // given the parameter name.
            let name = if via == breezy::optparse::Via::Argument {
                option.getattr("name")?
            } else {
                param.into_pyobject(py)?.into_any()
            };
            callback.call1((&option, name, value, &self.parser))?;
        }
        Ok(())
    }
}
