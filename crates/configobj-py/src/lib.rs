//! Python bindings presenting the configobj crate as the `configobj` module.
//!
//! Kept in step with configobj-rs's own configobj-py/src/lib.rs. A pymodule
//! generates its init symbol in the crate that declares it, so the bindings
//! cannot simply be re-exported from there.
//!
//! The Python configobj presents a config file as nested dicts: a `ConfigObj`
//! is a mapping of names to values and to `Section`s, which are mappings in
//! turn. Callers index them, assign into them, `del` from them and call
//! `setdefault`, so that is the shape these bindings expose, rather than the
//! crate's own Rust-flavoured API.
//!
//! Values are text, and a list value is a list of strings.

use configobj::{Builder, ConfigObj as RsConfigObj, Section as RsSection, Value};
use pyo3::exceptions::{PyKeyError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyString};
use std::sync::{Arc, Mutex};

/// The parsed file, shared between the `ConfigObj` and every `Section` view of
/// it so that a write through one is seen by the others, as in Python.
type Shared = Arc<Mutex<RsConfigObj>>;

/// Turn a crate error into the Python exception the caller expects.
fn to_py_err(e: configobj::Error) -> PyErr {
    match &e {
        configobj::Error::Io(_) => PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()),
        // Callers distinguish a mis-encoded file from a malformed one, and
        // catch the same exception they would from decoding it themselves.
        // UnicodeDecodeError cannot be built from a message alone, so it is
        // raised by decoding the offending bytes.
        configobj::Error::Encoding(_) => {
            Python::attach(|py| match std::ffi::CString::new(e.to_string()) {
                Ok(message) => PyErr::from_value(
                    pyo3::exceptions::PyUnicodeDecodeError::new(
                        py,
                        c"utf-8",
                        &[0xff],
                        0..1,
                        &message,
                    )
                    .map(|err| err.into_any())
                    .unwrap_or_else(|err| err.value(py).clone().into_any()),
                ),
                Err(_) => ConfigObjError::new_err(e.to_string()),
            })
        }
        _ => ConfigObjError::new_err(e.to_string()),
    }
}

pyo3::create_exception!(
    _configobj_rs,
    ConfigObjError,
    pyo3::exceptions::PyException,
    "A config file could not be parsed or written."
);

pyo3::create_exception!(
    _configobj_rs,
    ParseError,
    ConfigObjError,
    "A line could not be parsed."
);

pyo3::create_exception!(
    _configobj_rs,
    DuplicateError,
    ConfigObjError,
    "A section or key was defined twice."
);

pyo3::create_exception!(
    _configobj_rs,
    NestingError,
    ConfigObjError,
    "A section header's nesting could not be made sense of."
);

/// Raise the most specific error class for a parse failure, carrying the line
/// number breezy reports to the user.
fn parse_err_to_py(py: Python<'_>, e: configobj::Error, filename: Option<&str>) -> PyErr {
    let errors = e.parse_errors();
    let Some(first) = errors.first() else {
        return to_py_err(e);
    };
    let err = match first.kind {
        configobj::ErrorKind::Duplicate => DuplicateError::new_err(e.to_string()),
        configobj::ErrorKind::Nesting => NestingError::new_err(e.to_string()),
        _ => ParseError::new_err(e.to_string()),
    };
    // Callers report where a config file went wrong, reading the line number
    // off the exception and walking .errors for the individual messages.
    let value = err.value(py);
    let _ = value.setattr("line_number", first.line_number);
    let _ = value.setattr("line", first.line.as_str());
    let _ = value.setattr("msg", e.to_string());

    let each = PyList::empty(py);
    for error in errors {
        let item = ParseError::new_err(error.to_string());
        let item = item.value(py);
        let _ = item.setattr("msg", error.to_string());
        let _ = item.setattr("line_number", error.line_number);
        let _ = item.setattr("line", error.line.as_str());
        let _ = each.append(item);
    }
    let _ = value.setattr("errors", each);

    // .config is the partly built config, which callers use only to name the
    // file the errors came from.
    let _ = value.setattr(
        "config",
        ErrorConfig {
            filename: filename.map(str::to_string),
        },
    );
    err
}

/// Stands in for the partly built config carried by a parse error.
///
/// Callers reach through it for the filename, which is all it needs to hold.
#[pyclass]
struct ErrorConfig {
    #[pyo3(get)]
    filename: Option<String>,
}

/// Convert a stored value into the Python object a caller expects.
fn value_to_py(py: Python<'_>, value: &Value) -> PyResult<Py<PyAny>> {
    match value {
        Value::String(s) => Ok(PyString::new(py, s).into_any().unbind()),
        Value::List(items) => Ok(PyList::new(py, items.iter().map(|i| i.as_str()))?
            .into_any()
            .unbind()),
    }
}

/// Convert a Python object into a value, accepting the types a config file can
/// hold: text, or a sequence of text.
fn py_to_value(obj: &Bound<'_, PyAny>) -> PyResult<Value> {
    if let Ok(s) = obj.cast::<PyString>() {
        return Ok(Value::String(s.extract::<String>()?));
    }
    if obj.is_instance_of::<PyBytes>() {
        return Err(PyTypeError::new_err(
            "config values are text; decode bytes before storing them",
        ));
    }
    if let Ok(items) = obj.try_iter() {
        let mut out = Vec::new();
        for item in items {
            out.push(stringify(&item?)?);
        }
        return Ok(Value::List(out));
    }
    Ok(Value::String(stringify(obj)?))
}

/// Render a value as the text a config file stores.
///
/// A file holds only text, so a number or a bool is stored the way Python
/// spells it, which is what the Python configobj writes for one.
fn stringify(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    if let Ok(s) = obj.cast::<PyString>() {
        return s.extract::<String>();
    }
    if obj.is_instance_of::<PyBytes>() {
        return Err(PyTypeError::new_err(
            "config values are text; decode bytes before storing them",
        ));
    }
    obj.str()?.extract::<String>()
}

/// The path from the root of the file to one section.
///
/// A `Section` keeps a path rather than a borrow, so it stays valid while the
/// config is mutated through another handle.
#[derive(Clone, Default)]
struct Path(Vec<String>);

impl Path {
    fn child(&self, name: &str) -> Path {
        let mut path = self.0.clone();
        path.push(name.to_string());
        Path(path)
    }
}

/// Resolve a path to a section, or raise if it has been removed.
fn resolve<'a>(root: &'a RsConfigObj, path: &Path) -> PyResult<&'a RsSection> {
    let names: Vec<&str> = path.0.iter().map(String::as_str).collect();
    root.section_path(&names)
        .ok_or_else(|| PyKeyError::new_err(format!("section {:?} no longer exists", path.0)))
}

/// Resolve a path to a section for mutation.
fn resolve_mut<'a>(root: &'a mut RsConfigObj, path: &Path) -> PyResult<&'a mut RsSection> {
    let mut current: &mut RsSection = root.root_mut();
    for name in &path.0 {
        current = current
            .section_mut(name)
            .ok_or_else(|| PyKeyError::new_err(format!("section {name:?} no longer exists")))?;
    }
    Ok(current)
}

/// A section of a config file, behaving as a mutable mapping.
#[pyclass(mapping, subclass)]
struct Section {
    shared: Shared,
    path: Path,
}

impl Section {
    fn with<R>(&self, f: impl FnOnce(&RsSection) -> PyResult<R>) -> PyResult<R> {
        let root = self.shared.lock().expect("config lock");
        f(resolve(&root, &self.path)?)
    }

    fn with_mut<R>(&self, f: impl FnOnce(&mut RsSection) -> PyResult<R>) -> PyResult<R> {
        let mut root = self.shared.lock().expect("config lock");
        f(resolve_mut(&mut root, &self.path)?)
    }

    /// Look up a name, which may be a value or a subsection.
    fn lookup(&self, py: Python<'_>, key: &str) -> PyResult<Py<PyAny>> {
        let is_section = self.with(|section| Ok(section.section(key).is_some()))?;
        if is_section {
            return Ok(Section {
                shared: Arc::clone(&self.shared),
                path: self.path.child(key),
            }
            .into_pyobject(py)?
            .into_any()
            .unbind());
        }
        let value = self.with(|section| Ok(section.get(key).cloned()))?;
        match value {
            Some(value) => value_to_py(py, &value),
            None => Err(PyKeyError::new_err(key.to_string())),
        }
    }

    /// Store a value or, for a mapping, a whole subsection.
    fn store(&self, key: &str, value: &Bound<'_, PyAny>) -> PyResult<()> {
        if let Ok(dict) = value.cast::<PyDict>() {
            self.with_mut(|section| {
                section.insert_section(key, RsSection::new());
                Ok(())
            })?;
            let child = Section {
                shared: Arc::clone(&self.shared),
                path: self.path.child(key),
            };
            for (k, v) in dict.iter() {
                let name = k.extract::<String>()?;
                child.store(&name, &v)?;
            }
            return Ok(());
        }
        let value = py_to_value(value)?;
        self.with_mut(|section| {
            section.insert(key, value);
            Ok(())
        })
    }
}

#[pymethods]
impl Section {
    fn __getitem__(&self, py: Python<'_>, key: &str) -> PyResult<Py<PyAny>> {
        self.lookup(py, key)
    }

    fn __setitem__(&self, key: &str, value: &Bound<'_, PyAny>) -> PyResult<()> {
        self.store(key, value)
    }

    fn __delitem__(&self, key: &str) -> PyResult<()> {
        self.with_mut(|section| {
            if section.remove(key) {
                Ok(())
            } else {
                Err(PyKeyError::new_err(key.to_string()))
            }
        })
    }

    fn __contains__(&self, key: &str) -> PyResult<bool> {
        self.with(|section| Ok(section.contains_key(key)))
    }

    fn __len__(&self) -> PyResult<usize> {
        self.with(|section| Ok(section.len()))
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let keys = self.keys()?;
        Ok(PyList::new(py, keys)?.into_any().try_iter()?.into())
    }

    /// Every name in this section, in file order.
    fn keys(&self) -> PyResult<Vec<String>> {
        self.with(|section| Ok(section.keys().map(str::to_string).collect()))
    }

    /// The names holding values rather than subsections, in file order.
    #[getter]
    fn scalars(&self) -> PyResult<Vec<String>> {
        self.with(|section| Ok(section.scalars().map(str::to_string).collect()))
    }

    /// The names holding subsections, in file order.
    #[getter]
    fn sections(&self) -> PyResult<Vec<String>> {
        self.with(|section| Ok(section.section_names().map(str::to_string).collect()))
    }

    fn values(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        self.keys()?
            .into_iter()
            .map(|key| self.lookup(py, &key))
            .collect()
    }

    fn items(&self, py: Python<'_>) -> PyResult<Vec<(String, Py<PyAny>)>> {
        self.keys()?
            .into_iter()
            .map(|key| Ok((key.clone(), self.lookup(py, &key)?)))
            .collect()
    }

    /// The name the Python configobj gives `items`, which callers still use.
    fn iteritems(&self, py: Python<'_>) -> PyResult<Vec<(String, Py<PyAny>)>> {
        self.items(py)
    }

    /// Compare equal to a mapping with the same contents.
    ///
    /// The Python configobj's `Section` is a `dict` subclass, so callers
    /// compare sections against plain dicts.
    fn __eq__(&self, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<bool> {
        // Another section compares by contents, as two dicts would.
        if let Ok(section) = other.cast::<Section>() {
            let theirs = section.borrow().dict(py)?;
            let ours = self.dict(py)?;
            return ours.bind(py).eq(theirs.bind(py));
        }
        let Ok(mapping) = other.cast::<PyDict>() else {
            return Ok(false);
        };
        if mapping.len() != self.with(|section| Ok(section.len()))? {
            return Ok(false);
        }
        for (key, value) in mapping.iter() {
            let key = key.extract::<String>()?;
            if !self.with(|section| Ok(section.contains_key(&key)))? {
                return Ok(false);
            }
            let ours = self.lookup(py, &key)?;
            if !ours.bind(py).eq(&value)? {
                return Ok(false);
            }
        }
        Ok(true)
    }

    /// Render as a dict, so a section can be compared or copied like one.
    fn dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let out = PyDict::new(py);
        for key in self.keys()? {
            let value = self.lookup(py, &key)?;
            let value = match value.bind(py).cast::<Section>() {
                Ok(section) => section.borrow().dict(py)?,
                Err(_) => value,
            };
            out.set_item(key, value)?;
        }
        Ok(out.into_any().unbind())
    }

    #[pyo3(signature = (key, default=None))]
    fn get(
        &self,
        py: Python<'_>,
        key: &str,
        default: Option<Py<PyAny>>,
    ) -> PyResult<Option<Py<PyAny>>> {
        match self.lookup(py, key) {
            Ok(value) => Ok(Some(value)),
            Err(e) if e.is_instance_of::<PyKeyError>(py) => Ok(default),
            Err(e) => Err(e),
        }
    }

    /// Return the value for `key`, storing and returning `default` if absent.
    #[pyo3(signature = (key, default=None))]
    fn setdefault(
        &self,
        py: Python<'_>,
        key: &str,
        default: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        if self.with(|section| Ok(section.contains_key(key)))? {
            return self.lookup(py, key);
        }
        match default {
            Some(value) => self.store(key, value)?,
            None => self.with_mut(|section| {
                section.insert(key, "");
                Ok(())
            })?,
        }
        self.lookup(py, key)
    }

    /// Merge a mapping into this section.
    fn update(&self, other: &Bound<'_, PyAny>) -> PyResult<()> {
        let items = if let Ok(dict) = other.cast::<PyDict>() {
            dict.items()
        } else {
            other.call_method0("items")?.cast_into::<PyList>()?
        };
        for pair in items.iter() {
            let (key, value): (String, Bound<'_, PyAny>) = pair.extract()?;
            self.store(&key, &value)?;
        }
        Ok(())
    }

    /// Interpret an option as a boolean, as `yes`/`no`, `on`/`off`,
    /// `true`/`false` or `1`/`0` in any case.
    fn as_bool(&self, key: &str) -> PyResult<bool> {
        let value = self
            .with(|section| Ok(section.get(key).cloned()))?
            .ok_or_else(|| PyKeyError::new_err(key.to_string()))?;
        value
            .as_bool()
            .map_err(|e| PyValueError::new_err(e.to_string()))
    }

    /// Interpret an option as an integer.
    fn as_int(&self, key: &str) -> PyResult<i64> {
        let value = self
            .with(|section| Ok(section.get(key).cloned()))?
            .ok_or_else(|| PyKeyError::new_err(key.to_string()))?;
        value
            .parse::<i64>()
            .map_err(|e| PyValueError::new_err(e.to_string()))
    }

    /// Interpret an option as a float.
    fn as_float(&self, key: &str) -> PyResult<f64> {
        let value = self
            .with(|section| Ok(section.get(key).cloned()))?
            .ok_or_else(|| PyKeyError::new_err(key.to_string()))?;
        value
            .parse::<f64>()
            .map_err(|e| PyValueError::new_err(e.to_string()))
    }

    /// Read an option as a list, treating a single value as a one-item list.
    fn as_list(&self, key: &str) -> PyResult<Vec<String>> {
        let value = self
            .with(|section| Ok(section.get(key).cloned()))?
            .ok_or_else(|| PyKeyError::new_err(key.to_string()))?;
        Ok(value.as_list().into_iter().map(str::to_string).collect())
    }

    /// Render as a dict would.
    ///
    /// The Python configobj's `Section` is a `dict` subclass, so callers
    /// display a section by formatting it and get dict syntax.
    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        self.dict(py)?.bind(py).repr()?.extract()
    }
}

/// A parsed config file.
#[pyclass(mapping, extends=Section, subclass)]
struct ConfigObj {}

#[pymethods]
impl ConfigObj {
    /// Parse a config.
    ///
    /// `infile` may be a filename, a file-like object, a list of lines, a
    /// mapping to start from, or `None` for an empty config.
    #[new]
    #[pyo3(signature = (infile=None, **kwargs))]
    fn new(
        py: Python<'_>,
        infile: Option<&Bound<'_, PyAny>>,
        kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<PyClassInitializer<Self>> {
        let list_values = match kwargs.and_then(|k| k.get_item("list_values").transpose()) {
            Some(value) => value?.extract::<bool>()?,
            None => true,
        };
        let file_error = match kwargs.and_then(|k| k.get_item("file_error").transpose()) {
            Some(value) => value?.extract::<bool>()?,
            None => false,
        };
        let builder = Builder::new().list_values(list_values);

        let (parsed, filename) = load(py, infile, &builder, file_error)?;
        let mut parsed = parsed;
        if let Some(name) = &filename {
            parsed.set_filename(name);
        }

        let shared: Shared = Arc::new(Mutex::new(parsed));
        // A mapping given as input is applied on top of the empty config.
        if let Some(obj) = infile {
            if let Ok(dict) = obj.cast::<PyDict>() {
                let root = Section {
                    shared: Arc::clone(&shared),
                    path: Path::default(),
                };
                for (k, v) in dict.iter() {
                    root.store(&k.extract::<String>()?, &v)?;
                }
            }
        }
        Ok(PyClassInitializer::from(Section {
            shared,
            path: Path::default(),
        })
        .add_subclass(ConfigObj {}))
    }

    /// Accept and ignore the constructor arguments.
    ///
    /// Construction happens in `__new__`, but a subclass written for the
    /// Python configobj calls `super().__init__(infile, ...)`, which would
    /// otherwise reach `object.__init__` and be rejected.
    #[pyo3(signature = (*_args, **_kwargs))]
    fn __init__(
        _slf: PyRef<'_, Self>,
        _args: &Bound<'_, pyo3::types::PyTuple>,
        _kwargs: Option<&Bound<'_, PyDict>>,
    ) {
    }

    /// Write the config, to `outfile` if given or else to its filename.
    ///
    /// With neither, the lines are returned, as the Python implementation does.
    #[pyo3(signature = (outfile=None))]
    fn write(
        slf: PyRef<'_, Self>,
        py: Python<'_>,
        outfile: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Option<Py<PyAny>>> {
        // Release the lock before calling back into Python: another thread
        // may take the GIL and then block on the lock, deadlocking us.
        let base = slf.as_super();
        let root = base.shared.lock().expect("config lock");
        match outfile {
            Some(out) => {
                let bytes = root.to_bytes().map_err(to_py_err)?;
                drop(root);
                out.call_method1("write", (PyBytes::new(py, &bytes),))?;
                Ok(None)
            }
            None if root.filename().is_some() => {
                root.save().map_err(to_py_err)?;
                Ok(None)
            }
            None => {
                let lines = root.to_lines().map_err(to_py_err)?;
                drop(root);
                Ok(Some(PyList::new(py, lines)?.into_any().unbind()))
            }
        }
    }

    /// Re-read the config from the file it was read from.
    fn reload(slf: PyRef<'_, Self>) -> PyResult<()> {
        let base = slf.as_super();
        let mut root = base.shared.lock().expect("config lock");
        // A file that has gone missing reloads as empty, matching how a
        // missing file reads when the config is first opened.
        let missing = root.filename().is_some_and(|path| !path.exists());
        if missing {
            let keys: Vec<String> = root.keys().map(str::to_string).collect();
            for key in keys {
                root.remove(&key);
            }
            return Ok(());
        }
        root.reload().map_err(to_py_err)
    }

    /// The file this config was read from, if any.
    #[getter]
    fn get_filename(slf: PyRef<'_, Self>) -> Option<String> {
        let base = slf.as_super();
        let root = base.shared.lock().expect("config lock");
        root.filename().map(|p| p.to_string_lossy().into_owned())
    }

    #[setter]
    fn set_filename(slf: PyRef<'_, Self>, filename: Option<String>) {
        let base = slf.as_super();
        let mut root = base.shared.lock().expect("config lock");
        if let Some(name) = filename {
            root.set_filename(name);
        }
    }

    /// Comment lines at the top of the file.
    #[getter]
    fn get_initial_comment(slf: PyRef<'_, Self>) -> Vec<String> {
        let base = slf.as_super();
        let root = base.shared.lock().expect("config lock");
        root.initial_comment().to_vec()
    }

    #[setter]
    fn set_initial_comment(slf: PyRef<'_, Self>, lines: Vec<String>) {
        let base = slf.as_super();
        let mut root = base.shared.lock().expect("config lock");
        root.set_initial_comment(lines);
    }

    /// Comment lines at the bottom of the file.
    #[getter]
    fn get_final_comment(slf: PyRef<'_, Self>) -> Vec<String> {
        let base = slf.as_super();
        let root = base.shared.lock().expect("config lock");
        root.final_comment().to_vec()
    }

    #[setter]
    fn set_final_comment(slf: PyRef<'_, Self>, lines: Vec<String>) {
        let base = slf.as_super();
        let mut root = base.shared.lock().expect("config lock");
        root.set_final_comment(lines);
    }
}

/// Read the input into a config, returning it with any filename it came from.
fn load(
    py: Python<'_>,
    infile: Option<&Bound<'_, PyAny>>,
    builder: &Builder,
    file_error: bool,
) -> PyResult<(RsConfigObj, Option<String>)> {
    let Some(obj) = infile else {
        return Ok((builder.from_str("").map_err(to_py_err)?, None));
    };

    // A mapping starts from an empty config and is filled in by the caller.
    if obj.cast::<PyDict>().is_ok() {
        return Ok((builder.from_str("").map_err(to_py_err)?, None));
    }

    // A filename.
    if let Ok(name) = obj.cast::<PyString>() {
        let name = name.extract::<String>()?;
        // A missing file reads as an empty config unless the caller asked
        // otherwise, which is how an optional config file is read.
        if !file_error && !std::path::Path::new(&name).exists() {
            return Ok((builder.from_str("").map_err(to_py_err)?, Some(name)));
        }
        let conf = builder.from_file(&name).map_err(|e| match &e {
            configobj::Error::Parse(_) => parse_err_to_py(py, e, Some(&name)),
            _ => to_py_err(e),
        })?;
        return Ok((conf, Some(name)));
    }

    // A file-like object.
    if obj.hasattr("read")? {
        let data = obj.call_method0("read")?;
        let bytes = as_bytes(&data)?;
        let conf = builder
            .from_bytes(&bytes)
            .map_err(|e| parse_err_to_py(py, e, None))?;
        return Ok((conf, None));
    }

    // A sequence of lines, which may be text or bytes.
    let mut lines = Vec::new();
    for item in obj.try_iter()? {
        let item = item?;
        if let Ok(text) = item.cast::<PyString>() {
            lines.push(text.extract::<String>()?);
        } else {
            let bytes = as_bytes(&item)?;
            lines.push(
                String::from_utf8(bytes)
                    .map_err(|e| PyValueError::new_err(format!("config is not UTF-8: {e}")))?,
            );
        }
    }
    let conf = builder
        .from_lines(lines)
        .map_err(|e| parse_err_to_py(py, e, None))?;
    Ok((conf, None))
}

/// Read an object as bytes, accepting text as UTF-8.
fn as_bytes(obj: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    if let Ok(bytes) = obj.cast::<PyBytes>() {
        return Ok(bytes.as_bytes().to_vec());
    }
    if let Ok(text) = obj.cast::<PyString>() {
        return Ok(text.extract::<String>()?.into_bytes());
    }
    Err(PyTypeError::new_err("expected text or bytes"))
}

/// Quote a value so that parsing it yields the value back.
///
/// Callers that keep values quoted themselves, as breezy's config stores do,
/// use this with `unquote` as a matched pair. Quoting always follows the
/// list-value rules, since those are what make a value safe to read back.
///
/// A list is quoted with list syntax, and anything that is not text is
/// rendered the way a config file would store it.
#[pyfunction]
fn quote(value: &Bound<'_, PyAny>) -> PyResult<String> {
    RsConfigObj::quote_value(&py_to_value(value)?).map_err(to_py_err)
}

/// Strip one layer of matching quotes, undoing [`quote`].
#[pyfunction]
fn unquote(value: &str) -> String {
    RsConfigObj::unquote(value).to_string()
}

/// Split a value the way a config file line would be read.
///
/// This gives callers configobj's list handling without having to build a
/// config and parse a synthetic line through it.
#[pyfunction]
fn parse_value(py: Python<'_>, value: &str) -> PyResult<Py<PyAny>> {
    let conf = RsConfigObj::from_str(&format!("value = {value}\n"))
        .map_err(|e| parse_err_to_py(py, e, None))?;
    match conf.get("value") {
        Some(value) => value_to_py(py, value),
        None => Err(ConfigObjError::new_err("value could not be read")),
    }
}

#[pymodule]
fn _configobj_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // A section is a mapping of its contents. The Python configobj says so by
    // subclassing dict, which a pyclass cannot do, so register with the ABC
    // instead: callers testing isinstance(value, Mapping) then see it.
    let py = m.py();
    let abc = py.import("collections.abc")?;
    for name in ["Mapping", "MutableMapping"] {
        abc.getattr(name)?
            .call_method1("register", (py.get_type::<Section>(),))?;
    }

    m.add_function(wrap_pyfunction!(quote, m)?)?;
    m.add_function(wrap_pyfunction!(unquote, m)?)?;
    m.add_function(wrap_pyfunction!(parse_value, m)?)?;
    m.add_class::<ConfigObj>()?;
    m.add_class::<Section>()?;
    m.add("ConfigObjError", m.py().get_type::<ConfigObjError>())?;
    m.add("ParseError", m.py().get_type::<ParseError>())?;
    m.add("DuplicateError", m.py().get_type::<DuplicateError>())?;
    m.add("NestingError", m.py().get_type::<NestingError>())?;
    Ok(())
}
