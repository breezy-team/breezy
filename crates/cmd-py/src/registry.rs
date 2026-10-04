//! Python bindings for the object registry.
//!
//! The registry maps keys to objects (or to lazily imported ones) and carries
//! the help and info recorded alongside each entry. It is the base that the
//! command, provider, format and known-hooks registries subclass.

use pyo3::prelude::*;
use pyo3::types::{PyTuple, PyType};

/// Import and return the object named by `module_name`/`member_name`.
///
/// Imports the module and, if a member name is given, walks its (possibly
/// dotted) attribute chain.
#[pyfunction]
#[pyo3(signature = (module_name, member_name=None))]
pub(crate) fn get_named_object(
    py: Python<'_>,
    module_name: &str,
    member_name: Option<&str>,
) -> PyResult<Py<PyAny>> {
    let builtins = py.import("builtins")?;
    match member_name.filter(|m| !m.is_empty()) {
        Some(member) => {
            let attr_chain: Vec<&str> = member.split('.').collect();
            let from_list = vec![attr_chain[0]];
            let mut obj = builtins.call_method1(
                "__import__",
                (
                    module_name,
                    pyo3::types::PyDict::new(py),
                    pyo3::types::PyDict::new(py),
                    from_list,
                ),
            )?;
            for attr in attr_chain {
                obj = obj.getattr(attr)?;
            }
            Ok(obj.unbind())
        }
        None => {
            builtins.call_method1(
                "__import__",
                (
                    module_name,
                    py.import("builtins")?.getattr("globals")?.call0()?,
                    py.import("builtins")?.getattr("locals")?.call0()?,
                    pyo3::types::PyList::empty(py),
                ),
            )?;
            Ok(py
                .import("sys")?
                .getattr("modules")?
                .get_item(module_name)?
                .unbind())
        }
    }
}

/// Determine the parent module/member and final attribute of a dotted name.
///
/// Returns ``(module_name, member_name, final_attr)`` such that
/// ``getattr(get_named_object(module, member), final_attr)`` equals
/// ``get_named_object(module_name, member_name)``.
#[pyfunction]
#[pyo3(signature = (module_name, member_name=None))]
pub(crate) fn calc_parent_name(
    module_name: &str,
    member_name: Option<&str>,
) -> PyResult<(String, Option<String>, String)> {
    match member_name {
        Some(member) => match member.rsplit_once('.') {
            Some((parent, attr)) => Ok((
                module_name.to_string(),
                Some(parent.to_string()),
                attr.to_string(),
            )),
            None => Ok((module_name.to_string(), None, member.to_string())),
        },
        None => match module_name.rsplit_once('.') {
            Some((parent, attr)) => Ok((parent.to_string(), None, attr.to_string())),
            None => Err(pyo3::exceptions::PyAssertionError::new_err(format!(
                "No parent object for top-level module {module_name:?}"
            ))),
        },
    }
}

/// Hold a reference to an object and return it on request.
///
/// This makes plain objects behave like lazily-imported ones for [`Registry`].
#[pyclass(name = "_ObjectGetter", module = "breezy._cmd_rs.registry", subclass)]
pub(crate) struct ObjectGetter {
    obj: Py<PyAny>,
}

#[pymethods]
impl ObjectGetter {
    #[new]
    pub(crate) fn new(obj: Py<PyAny>) -> Self {
        ObjectGetter { obj }
    }

    fn get_module(&self, py: Python<'_>) -> PyResult<String> {
        self.obj.bind(py).getattr("__module__")?.extract()
    }

    fn get_obj(&self, py: Python<'_>) -> Py<PyAny> {
        self.obj.clone_ref(py)
    }
}

/// Record a possible object and import it on first request.
#[pyclass(name = "_LazyObjectGetter", module = "breezy._cmd_rs.registry", extends = ObjectGetter)]
pub(crate) struct LazyObjectGetter {
    #[pyo3(get)]
    _module_name: String,
    #[pyo3(get)]
    _member_name: Option<String>,
    #[pyo3(get)]
    _imported: bool,
}

#[pymethods]
impl LazyObjectGetter {
    #[new]
    #[pyo3(signature = (module_name, member_name))]
    pub(crate) fn new(
        py: Python<'_>,
        module_name: String,
        member_name: Option<String>,
    ) -> PyClassInitializer<Self> {
        PyClassInitializer::from(ObjectGetter { obj: py.None() }).add_subclass(LazyObjectGetter {
            _module_name: module_name,
            _member_name: member_name,
            _imported: false,
        })
    }

    fn get_module(&self) -> String {
        self._module_name.clone()
    }

    fn get_obj(mut slf: PyRefMut<'_, Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if !slf._imported {
            let obj = get_named_object(py, &slf._module_name.clone(), slf._member_name.as_deref())?;
            slf._imported = true;
            slf.as_super().obj = obj;
        }
        Ok(slf.as_super().obj.clone_ref(py))
    }

    fn __repr__(slf: PyRef<'_, Self>) -> String {
        format!(
            "<breezy._cmd_rs.registry._LazyObjectGetter object at {:x}, module={:?} attribute={:?} imported={:?}>",
            slf.as_ptr() as usize,
            slf._module_name,
            slf._member_name,
            slf._imported,
        )
    }
}

/// A name-to-object registry with lazy-import support.
///
/// Objects are stored behind ``_ObjectGetter``/``_LazyObjectGetter`` wrappers
/// so plain and lazily-imported entries behave alike. Subclassed across breezy
/// (formats, commands, hooks, ...).
#[pyclass(name = "Registry", module = "breezy._cmd_rs.registry", subclass)]
pub(crate) struct Registry {
    default_key: Option<Py<PyAny>>,
    dict: Py<pyo3::types::PyDict>,
    aliases: Py<pyo3::types::PyDict>,
    help_dict: Py<pyo3::types::PyDict>,
    info_dict: Py<pyo3::types::PyDict>,
}

impl Registry {
    pub(crate) fn object_getter<'py>(
        py: Python<'py>,
        obj: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        Ok(Bound::new(
            py,
            ObjectGetter {
                obj: obj.clone().unbind(),
            },
        )?
        .into_any())
    }

    pub(crate) fn lazy_object_getter<'py>(
        py: Python<'py>,
        module_name: &str,
        member_name: Option<&str>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let initializer = LazyObjectGetter::new(
            py,
            module_name.to_string(),
            member_name.map(|s| s.to_string()),
        );
        Ok(Bound::new(py, initializer)?.into_any())
    }

    /// `key` if not None, else the default key (KeyError if neither).
    fn key_or_default<'py>(
        &self,
        py: Python<'py>,
        key: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        match key {
            Some(k) if !k.is_none() => Ok(k),
            _ => match &self.default_key {
                Some(d) if !d.is_none(py) => Ok(d.bind(py).clone()),
                _ => Err(pyo3::exceptions::PyKeyError::new_err(
                    "Key is None, and no default key is set",
                )),
            },
        }
    }
}

#[pymethods]
impl Registry {
    // Accept and ignore any args (subclasses pass their own __init__ args
    // through the constructor; like object.__new__ when __init__ is overridden).
    #[new]
    #[pyo3(signature = (*_args, **_kwargs))]
    pub(crate) fn new(
        py: Python<'_>,
        _args: &Bound<'_, PyTuple>,
        _kwargs: Option<&Bound<'_, pyo3::types::PyDict>>,
    ) -> Self {
        Registry {
            default_key: None,
            dict: pyo3::types::PyDict::new(py).unbind(),
            aliases: pyo3::types::PyDict::new(py).unbind(),
            help_dict: pyo3::types::PyDict::new(py).unbind(),
            info_dict: pyo3::types::PyDict::new(py).unbind(),
        }
    }

    // Subclasses call super().__init__(), which resets the state.
    fn __init__(&mut self, py: Python<'_>) {
        self.default_key = None;
        self.dict = pyo3::types::PyDict::new(py).unbind();
        self.aliases = pyo3::types::PyDict::new(py).unbind();
        self.help_dict = pyo3::types::PyDict::new(py).unbind();
        self.info_dict = pyo3::types::PyDict::new(py).unbind();
    }

    // Support `Registry[K, V, P]` as a (generic) base class; the parameters are
    // type annotations only, so return the class unchanged.
    #[classmethod]
    fn __class_getitem__(cls: &Bound<'_, PyType>, _item: &Bound<'_, PyAny>) -> Py<PyType> {
        cls.clone().unbind()
    }

    fn aliases(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(self.aliases.bind(py).call_method0("copy")?.unbind())
    }

    fn alias_map(&self, py: Python<'_>) -> PyResult<Py<pyo3::types::PyDict>> {
        let ret = pyo3::types::PyDict::new(py);
        for (alias, target) in self.aliases.bind(py).iter() {
            match ret.get_item(&target)? {
                Some(list) => list.call_method1("append", (alias,))?,
                None => {
                    let list = pyo3::types::PyList::new(py, [alias])?;
                    ret.set_item(target, list)?;
                    continue;
                }
            };
        }
        Ok(ret.unbind())
    }

    fn _add_help_and_info(
        &self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        help: Option<Py<PyAny>>,
        info: Option<Py<PyAny>>,
    ) -> PyResult<()> {
        self.help_dict
            .bind(py)
            .set_item(key, help.map(|h| h.into_bound(py)))?;
        self.info_dict
            .bind(py)
            .set_item(key, info.map(|i| i.into_bound(py)))?;
        Ok(())
    }

    #[pyo3(signature = (key, obj, help=None, info=None, override_existing=false))]
    fn register(
        slf: &Bound<'_, Self>,
        key: Bound<'_, PyAny>,
        obj: Bound<'_, PyAny>,
        help: Option<Py<PyAny>>,
        info: Option<Py<PyAny>>,
        override_existing: bool,
    ) -> PyResult<()> {
        let py = slf.py();
        let me = slf.borrow();
        if !override_existing && me.dict.bind(py).contains(&key)? {
            return Err(pyo3::exceptions::PyKeyError::new_err(format!(
                "Key {} already registered",
                key.repr()?
            )));
        }
        me.dict
            .bind(py)
            .set_item(&key, Self::object_getter(py, &obj)?)?;
        me._add_help_and_info(py, &key, help, info)
    }

    #[pyo3(signature = (key, module_name, member_name, help=None, info=None, override_existing=false))]
    fn register_lazy(
        slf: &Bound<'_, Self>,
        key: Bound<'_, PyAny>,
        module_name: String,
        member_name: Option<String>,
        help: Option<Py<PyAny>>,
        info: Option<Py<PyAny>>,
        override_existing: bool,
    ) -> PyResult<()> {
        let py = slf.py();
        let me = slf.borrow();
        if !override_existing && me.dict.bind(py).contains(&key)? {
            return Err(pyo3::exceptions::PyKeyError::new_err(format!(
                "Key {} already registered",
                key.repr()?
            )));
        }
        let getter = Self::lazy_object_getter(py, &module_name, member_name.as_deref())?;
        me.dict.bind(py).set_item(&key, getter)?;
        me._add_help_and_info(py, &key, help, info)
    }

    #[pyo3(signature = (key, target, info=None))]
    fn register_alias(
        slf: &Bound<'_, Self>,
        key: Bound<'_, PyAny>,
        target: Bound<'_, PyAny>,
        info: Option<Py<PyAny>>,
    ) -> PyResult<()> {
        let py = slf.py();
        let me = slf.borrow();
        let dict = me.dict.bind(py);
        if dict.contains(&key)? && !me.aliases.bind(py).contains(&key)? {
            return Err(pyo3::exceptions::PyKeyError::new_err(format!(
                "Key {} already registered and not an alias",
                key.repr()?
            )));
        }
        let target_getter = dict
            .get_item(&target)?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(target.clone().unbind()))?;
        dict.set_item(&key, target_getter)?;
        me.aliases.bind(py).set_item(&key, &target)?;
        let info = match info {
            Some(i) => i.into_bound(py),
            None => me
                .info_dict
                .bind(py)
                .get_item(&target)?
                .unwrap_or_else(|| py.None().into_bound(py)),
        };
        let target_help = me
            .help_dict
            .bind(py)
            .get_item(&target)?
            .unwrap_or_else(|| py.None().into_bound(py));
        me._add_help_and_info(py, &key, Some(target_help.unbind()), Some(info.unbind()))
    }

    #[pyo3(signature = (key=None))]
    fn get(&self, py: Python<'_>, key: Option<Bound<'_, PyAny>>) -> PyResult<Py<PyAny>> {
        let k = self.key_or_default(py, key)?;
        let getter = self
            .dict
            .bind(py)
            .get_item(&k)?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(k.unbind()))?;
        Ok(getter.call_method0("get_obj")?.unbind())
    }

    fn _get_module(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<String> {
        let getter = self
            .dict
            .bind(py)
            .get_item(key)?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(key.clone().unbind()))?;
        getter.call_method0("get_module")?.extract()
    }

    fn get_prefix(&self, py: Python<'_>, fullname: &str) -> PyResult<Option<(Py<PyAny>, String)>> {
        for key in self.keys(py)? {
            let key = key.bind(py);
            let key_str: String = key.str()?.extract()?;
            if let Some(rest) = fullname.strip_prefix(&key_str) {
                let obj = self.get(py, Some(key.clone()))?;
                return Ok(Some((obj, rest.to_string())));
            }
        }
        Ok(None)
    }

    #[pyo3(signature = (key=None))]
    fn get_help(slf: &Bound<'_, Self>, key: Option<Bound<'_, PyAny>>) -> PyResult<Py<PyAny>> {
        let py = slf.py();
        let me = slf.borrow();
        let k = me.key_or_default(py, key.clone())?;
        let the_help = me
            .help_dict
            .bind(py)
            .get_item(&k)?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(k.clone().unbind()))?;
        if the_help.is_callable() {
            // callable help is invoked as help(self_registry, key), with key
            // as passed in (possibly None).
            let key_arg = key.map_or_else(|| py.None(), |k| k.unbind());
            return Ok(the_help.call1((slf, key_arg))?.unbind());
        }
        Ok(the_help.unbind())
    }

    #[pyo3(signature = (key=None))]
    fn get_info(&self, py: Python<'_>, key: Option<Bound<'_, PyAny>>) -> PyResult<Py<PyAny>> {
        let k = self.key_or_default(py, key)?;
        Ok(self
            .info_dict
            .bind(py)
            .get_item(&k)?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(k.clone().unbind()))?
            .unbind())
    }

    fn remove(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<()> {
        self.dict.bind(py).del_item(key)
    }

    fn __contains__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.dict.bind(py).contains(key)
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(self.dict.bind(py).call_method0("__iter__")?.unbind())
    }

    fn keys(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        let keys = self.dict.bind(py).keys();
        let sorted = py.import("builtins")?.call_method1("sorted", (keys,))?;
        let mut out = Vec::new();
        for k in sorted.try_iter()? {
            out.push(k?.unbind());
        }
        Ok(out)
    }

    fn iteritems(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        // Resolving an entry may import a module that registers more entries,
        // so iterate over a copy.
        let entries: Vec<(Bound<'_, PyAny>, Bound<'_, PyAny>)> =
            self.dict.bind(py).iter().collect();
        let items = pyo3::types::PyList::empty(py);
        for (key, getter) in entries {
            items.append((key, getter.call_method0("get_obj")?))?;
        }
        Ok(items.call_method0("__iter__")?.unbind())
    }

    fn items(&self, py: Python<'_>) -> PyResult<Vec<(Py<PyAny>, Py<PyAny>)>> {
        // Uses keys() (sorted) rather than iterating the entries (bug #430510).
        let mut out = Vec::new();
        for key in self.keys(py)? {
            let key = key.bind(py);
            let getter = self
                .dict
                .bind(py)
                .get_item(key)?
                .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(key.clone().unbind()))?;
            out.push((
                key.clone().unbind(),
                getter.call_method0("get_obj")?.unbind(),
            ));
        }
        Ok(out)
    }

    #[pyo3(signature = (key=None))]
    fn _get_key_or_default(
        &self,
        py: Python<'_>,
        key: Option<Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        Ok(self.key_or_default(py, key)?.unbind())
    }

    #[pyo3(signature = (key))]
    fn _set_default_key(&mut self, py: Python<'_>, key: Option<Bound<'_, PyAny>>) -> PyResult<()> {
        match key {
            Some(k) if !k.is_none() => {
                if !self.dict.bind(py).contains(&k)? {
                    return Err(pyo3::exceptions::PyKeyError::new_err(format!(
                        "No object registered under key {k}."
                    )));
                }
                self.default_key = Some(k.unbind());
            }
            _ => self.default_key = None,
        }
        Ok(())
    }

    fn _get_default_key(&self, py: Python<'_>) -> Option<Py<PyAny>> {
        self.default_key.as_ref().map(|k| k.clone_ref(py))
    }

    #[getter]
    fn default_key(&self, py: Python<'_>) -> Option<Py<PyAny>> {
        self.default_key.as_ref().map(|k| k.clone_ref(py))
    }

    #[setter]
    fn set_default_key(&mut self, py: Python<'_>, key: Option<Bound<'_, PyAny>>) -> PyResult<()> {
        self._set_default_key(py, key)
    }
}

/// Call a base [`Registry`] method on `slf` (the `Registry.method(self, ...)`
/// pattern, so subclass overrides don't recurse).
pub(crate) fn registry_super<'py>(
    slf: &Bound<'py, PyAny>,
    method: &str,
    args: &Bound<'py, PyTuple>,
    kwargs: Option<&Bound<'py, pyo3::types::PyDict>>,
) -> PyResult<Bound<'py, PyAny>> {
    let py = slf.py();
    let base = py.get_type::<Registry>().getattr(method)?;
    // Prepend slf: (slf,) + args.
    let full = PyTuple::new(py, [slf])?
        .as_sequence()
        .concat(args.as_sequence())?;
    base.call(full.cast::<PyTuple>()?, kwargs)
}
