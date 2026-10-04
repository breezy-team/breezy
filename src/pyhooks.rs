//! Hooks for Python: hook points whose callbacks are Python callables.

use pyo3::prelude::*;

/// Hook callbacks for Python, where a callback is a Python callable.
pub type PyCallbackList = crate::hooks::CallbackList<Py<PyAny>>;

/// The callbacks installed on hook points by name, before the hooks objects
/// defining them exist.
fn lazy_hooks() -> &'static std::sync::Mutex<crate::hooks::LazyHooks<Py<PyAny>>> {
    static LAZY: std::sync::OnceLock<std::sync::Mutex<crate::hooks::LazyHooks<Py<PyAny>>>> =
        std::sync::OnceLock::new();
    LAZY.get_or_init(Default::default)
}

fn lock_lazy_hooks() -> std::sync::MutexGuard<'static, crate::hooks::LazyHooks<Py<PyAny>>> {
    // Each mutation is a single map operation, so a panic while locked leaves
    // nothing half done.
    lazy_hooks().lock().unwrap_or_else(|e| e.into_inner())
}

/// The callbacks installed lazily for hook `key`, shared with the hook point
/// that takes them over.
pub fn lazy_hook_list(key: &crate::hooks::LazyHookKey) -> PyCallbackList {
    lock_lazy_hooks().list(key)
}

/// The keys of the lazily installed hooks.
pub fn lazy_hook_keys() -> Vec<crate::hooks::LazyHookKey> {
    lock_lazy_hooks().keys().cloned().collect()
}

/// Replace the lazily installed hooks with `hooks`, returning the previous
/// ones.
pub fn replace_lazy_hooks(
    hooks: crate::hooks::LazyHooks<Py<PyAny>>,
) -> crate::hooks::LazyHooks<Py<PyAny>> {
    std::mem::replace(&mut *lock_lazy_hooks(), hooks)
}

/// The callable of `callback`, and the callback to remember in its place if it
/// had to be imported.
pub fn resolve_callback(
    py: Python<'_>,
    callback: &crate::hooks::Callback<Py<PyAny>>,
) -> PyResult<(Py<PyAny>, Option<crate::hooks::Callback<Py<PyAny>>>)> {
    match callback {
        crate::hooks::Callback::Object(obj) => Ok((obj.clone_ref(py), None)),
        crate::hooks::Callback::Lazy { module, member } => {
            let mut obj = py.import(module.as_str())?.into_any();
            for attr in member.split('.') {
                obj = obj.getattr(attr)?;
            }
            let obj = obj.unbind();
            Ok((obj.clone_ref(py), Some(crate::hooks::Callback::Object(obj))))
        }
    }
}

/// The callables of `callbacks` paired with their labels, importing lazy ones.
pub fn callables(
    py: Python<'_>,
    callbacks: &PyCallbackList,
) -> PyResult<Vec<(Py<PyAny>, Option<String>)>> {
    let mut out = Vec::new();
    callbacks.for_each(
        |obj| obj.clone_ref(py),
        |installed| {
            let (obj, replacement) = resolve_callback(py, &installed.callback)?;
            out.push((obj, installed.label.clone()));
            Ok::<_, PyErr>(replacement)
        },
    )?;
    Ok(out)
}
