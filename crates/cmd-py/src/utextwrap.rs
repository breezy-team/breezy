//! Python bindings for `breezy::utextwrap`, exposed as `breezy._cmd_rs.utextwrap`.
//!
//! Only the `wrap`/`fill` convenience functions used by breezy are exposed. The
//! East Asian width category of each character is obtained from CPython's own
//! `unicodedata.east_asian_width`, so wrapping tracks the exact Unicode version
//! the interpreter was built against.

use breezy::utextwrap::{AmbiguousWidth, EaWidth, EastAsianWidth, Options, TextWrapper, WrapError};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyModule, PyString};
use std::cell::RefCell;
use std::collections::HashMap;

/// Classifier backed by `unicodedata.east_asian_width`, caching results per
/// codepoint so repeated characters don't re-cross the Python boundary. It
/// borrows the current GIL token; callers already hold the GIL.
struct UnicodeDataEaw<'py> {
    east_asian_width: Bound<'py, PyAny>,
    cache: RefCell<HashMap<char, EaWidth>>,
}

impl<'py> UnicodeDataEaw<'py> {
    fn new(py: Python<'py>) -> PyResult<Self> {
        let east_asian_width = py
            .import("unicodedata")?
            .getattr("east_asian_width")?
            .into_any();
        Ok(UnicodeDataEaw {
            east_asian_width,
            cache: RefCell::new(HashMap::new()),
        })
    }

    fn lookup(&self, c: char) -> EaWidth {
        let mut buf = [0u8; 4];
        let arg = PyString::new(self.east_asian_width.py(), c.encode_utf8(&mut buf));
        // east_asian_width is defined for every scalar value, so a failure
        // here means the environment is broken rather than an unclassifiable
        // character; surfacing it as a panic is more debuggable than pretending
        // the character is neutral.
        let cat: String = self
            .east_asian_width
            .call1((arg,))
            .and_then(|v| v.extract())
            .expect("unicodedata.east_asian_width failed");
        match cat.as_str() {
            "F" | "W" => EaWidth::Wide,
            "A" => EaWidth::Ambiguous,
            _ => EaWidth::Narrow,
        }
    }
}

impl EastAsianWidth for UnicodeDataEaw<'_> {
    fn width_category(&self, c: char) -> EaWidth {
        if let Some(w) = self.cache.borrow().get(&c) {
            return *w;
        }
        let w = self.lookup(c);
        self.cache.borrow_mut().insert(c, w);
        w
    }
}

fn map_wrap_error(e: WrapError) -> PyErr {
    PyValueError::new_err(e.to_string())
}

/// Wrap a single paragraph of text, returning a list of wrapped lines.
#[pyfunction]
#[pyo3(signature = (text, width = None, **kwargs))]
fn wrap(
    py: Python,
    text: &str,
    width: Option<isize>,
    kwargs: Option<&Bound<PyDict>>,
) -> PyResult<Vec<String>> {
    let opts = build_options(py, width, kwargs)?;
    let ea = UnicodeDataEaw::new(py)?;
    TextWrapper::new(opts, &ea)
        .wrap(text)
        .map_err(map_wrap_error)
}

/// Fill a single paragraph of text, returning a single string.
#[pyfunction]
#[pyo3(signature = (text, width = None, **kwargs))]
fn fill(
    py: Python,
    text: &str,
    width: Option<isize>,
    kwargs: Option<&Bound<PyDict>>,
) -> PyResult<String> {
    let opts = build_options(py, width, kwargs)?;
    let ea = UnicodeDataEaw::new(py)?;
    TextWrapper::new(opts, &ea)
        .fill(text)
        .map_err(map_wrap_error)
}

/// Build `Options` from the keyword arguments accepted by `UTextWrapper`,
/// falling back to the terminal width when `width` is not given. Unknown
/// keywords raise `TypeError`, matching the Python constructor.
fn build_options(
    py: Python,
    width: Option<isize>,
    kwargs: Option<&Bound<PyDict>>,
) -> PyResult<Options> {
    let mut opts = Options {
        width: match width {
            Some(w) => w,
            None => default_width(py)?,
        },
        ..Options::default()
    };

    let Some(kwargs) = kwargs else {
        return Ok(opts);
    };

    for (key, value) in kwargs.iter() {
        let key: String = key.extract()?;
        match key.as_str() {
            "width" => opts.width = value.extract()?,
            "initial_indent" => opts.initial_indent = value.extract()?,
            "subsequent_indent" => opts.subsequent_indent = value.extract()?,
            "break_long_words" => opts.break_long_words = value.is_truthy()?,
            "ambiguous_width" => {
                opts.ambiguous_width = match value.extract::<u8>()? {
                    1 => AmbiguousWidth::Single,
                    2 => AmbiguousWidth::Double,
                    _ => return Err(PyValueError::new_err("ambiguous_width should be 1 or 2")),
                }
            }
            other => {
                return Err(pyo3::exceptions::PyTypeError::new_err(format!(
                    "unexpected keyword argument {other:?}"
                )))
            }
        }
    }
    Ok(opts)
}

fn default_width(py: Python) -> PyResult<isize> {
    let osutils = py.import("breezy.osutils")?;
    let tw: Option<isize> = osutils.call_method0("terminal_width")?.extract()?;
    let width = match tw {
        Some(w) => w,
        None => osutils.getattr("default_terminal_width")?.extract()?,
    };
    Ok(width - 1)
}

/// Register the `utextwrap` submodule on `parent`.
pub fn utextwrap(parent: &Bound<PyModule>) -> PyResult<()> {
    parent.add_function(wrap_pyfunction!(wrap, parent)?)?;
    parent.add_function(wrap_pyfunction!(fill, parent)?)?;
    Ok(())
}
