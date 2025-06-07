//! Tools for converting globs to regular expressions.
//!
//! This module provides functions for converting shell-like globs to regular
//! expressions.

pub use fancy_regex::{Captures, Error, Match, Regex};
use lazy_static::lazy_static;
use std::sync::Arc;

lazy_static! {
    static ref SLASHES_RE: Regex = Regex::new(r"[\\/]+").unwrap();
    static ref EXPAND_RE: Regex = Regex::new("\\\\&").unwrap();
}

/// Converts backslashes in path patterns to forward slashes.
/// Doesn't normalize regular expressions - they may contain escapes.
pub fn normalize_pattern(pattern: &str) -> String {
    let mut pattern = pattern.to_string();
    if !(pattern.starts_with("RE:") || pattern.starts_with("!RE:")) {
        pattern = SLASHES_RE.replace_all(pattern.as_str(), "/").to_string();
    }
    if pattern.len() > 1 {
        pattern = pattern.trim_end_matches('/').to_string();
    }
    pattern
}

pub enum Replacement {
    String(String),
    Function(fn(&str) -> String),
    Closure(Box<dyn FnMut(String) -> String + Sync + Send>),
}

// TODO(jelmer): Consider using RegexSet from the regex crate instead.

/// Do a multiple-pattern substitution.
///
/// The patterns and substitutions are combined into one, so the result of
/// one replacement is never substituted again. Add the patterns and
/// replacements via the add method and then call the object. The patterns
/// must not contain capturing groups.
pub struct Replacer {
    compiled: Option<Regex>,
    pats: Vec<(String, Arc<Replacement>)>,
}

impl Replacer {
    pub fn new(source: Option<&Self>) -> Self {
        let mut ret = Self::empty();
        if let Some(source) = source {
            ret.add_replacer(source);
        }
        ret
    }

    pub fn empty() -> Self {
        Self {
            compiled: None,
            pats: Vec::new(),
        }
    }

    /// Add a pattern and replacement.
    ///
    /// The pattern must not contain capturing groups.
    /// The replacement might be either a string template in which \& will be
    /// replaced with the match, or a function that will get the matching text
    /// as argument. It does not get match object, because capturing is
    /// forbidden anyway.
    pub fn add(&mut self, pat: &str, fun: Replacement) {
        // Need to recompile
        self.compiled = None;
        self.pats.push((pat.to_string(), Arc::new(fun)));
    }

    pub fn add_validate(&mut self, pat: &str, fun: Replacement) -> Result<(), Error> {
        Regex::new(pat)?;
        self.add(pat, fun);
        Ok(())
    }

    /// Add all patterns from another replacer.
    ///
    /// All patterns and replacements from replacer are appended to the ones
    /// already defined.
    pub fn add_replacer(&mut self, replacer: &Replacer) {
        self.compiled = None;
        self.pats.extend(replacer.pats.clone());
    }

    pub fn replace(&mut self, text: &str) -> std::result::Result<String, Error> {
        if self.pats.is_empty() {
            return Ok(text.to_string());
        }
        if self.compiled.is_none() {
            let pat_str = self
                .pats
                .iter()
                .map(|(pat, _)| format!("({})", pat))
                .collect::<Vec<_>>()
                .join("|");
            self.compiled = Some(Regex::new(&pat_str)?);
        }
        let pats = &mut self.pats;

        fn expand(text: &str, rep: &str) -> String {
            rep.replace("\\&", text)
        }

        fn sub(m: &Match, rep: &mut Arc<Replacement>) -> String {
            let replacement = Arc::get_mut(rep).unwrap();
            match replacement {
                Replacement::String(s) => expand(m.as_str(), s.as_str()),
                Replacement::Function(f) => f(m.as_str()),
                Replacement::Closure(f) => f(m.as_str().to_string()),
            }
        }

        Ok(self
            .compiled
            .as_ref()
            .unwrap()
            .replace_all(text, |caps: &Captures| {
                for (index, m) in caps.iter().skip(1).enumerate() {
                    if let Some(m) = m {
                        return sub(&m, &mut pats[index].1);
                    }
                }
                unreachable!();
            })
            .to_string())
    }
}
