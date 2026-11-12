//! Writing translatable strings in ``.pot`` format for ``brz export-pot``.
//!
//! The messages come from command help, options, error formats and help
//! topics; this module formats them and tracks where in the source they came
//! from. Sorting and merging with the output of xgettext is left to the
//! Makefile.

use std::collections::{HashMap, HashSet};
use std::io::{self, Write};
use std::rc::Rc;

/// Escape `s` for use inside a double-quoted ``.po`` string.
pub fn escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '"' => out.push_str("\\\""),
            c => out.push(c),
        }
    }
    out
}

/// Render `s` as a ``.po`` string: a single quoted line, or for multi-line
/// text an empty first line followed by one quoted line per source line.
pub fn normalize(s: &str) -> String {
    let mut lines: Vec<String> = s.split('\n').map(str::to_string).collect();
    if lines.len() == 1 {
        return format!("\"{}\"", escape(s));
    }
    if lines.last().is_some_and(String::is_empty) {
        lines.pop();
        if let Some(last) = lines.last_mut() {
            last.push('\n');
        }
    }
    let escaped: Vec<String> = lines.iter().map(|l| escape(l)).collect();
    format!("\"\"\n\"{}\"", escaped.join("\\n\"\n\""))
}

/// Clean up the indentation of a docstring, like Python's ``inspect.cleandoc``.
///
/// Tabs are expanded, the first line is stripped of leading spaces, the
/// common indentation of the remaining lines is removed and leading and
/// trailing empty lines are dropped.
pub fn cleandoc(doc: &str) -> String {
    let expanded = expandtabs(doc, 8);
    let mut lines: Vec<&str> = expanded.split('\n').collect();
    let margin = lines[1..]
        .iter()
        .filter_map(|line| {
            let content = line.trim_start_matches(' ');
            (!content.is_empty()).then(|| line.len() - content.len())
        })
        .min();
    lines[0] = lines[0].trim_start_matches(' ');
    if let Some(margin) = margin {
        // Only the spaces before the margin are removed: every line with
        // content is indented by at least `margin` spaces, and a shorter line
        // consists of spaces only.
        for line in &mut lines[1..] {
            *line = line.get(margin..).unwrap_or("");
        }
    }
    let end = lines
        .iter()
        .rposition(|l| !l.is_empty())
        .map_or(0, |i| i + 1);
    let start = lines[..end]
        .iter()
        .position(|l| !l.is_empty())
        .unwrap_or(end);
    lines[start..end].join("\n")
}

/// Expand tabs to the next multiple of `tabsize` columns, like Python's
/// ``str.expandtabs``; the column restarts after ``\n`` and ``\r``.
fn expandtabs(s: &str, tabsize: usize) -> String {
    let mut out = String::with_capacity(s.len());
    let mut column = 0;
    for c in s.chars() {
        match c {
            '\t' => {
                let n = tabsize - column % tabsize;
                out.extend(std::iter::repeat_n(' ', n));
                column += n;
            }
            '\n' | '\r' => {
                out.push(c);
                column = 0;
            }
            c => {
                out.push(c);
                column += 1;
            }
        }
    }
    out
}

/// Whether the help paragraph `p` is a ``:Usage:`` section, which holds
/// example command lines rather than text to translate.
pub fn is_usage_paragraph(p: &str) -> bool {
    p.lines().next() == Some(":Usage:")
}

/// The line numbers of the definitions in a source file.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct SourceInfo {
    /// The line each class is defined on, by class name.
    pub classes: HashMap<String, u32>,
    /// The line each class docstring starts on, by class name.
    pub docstrings: HashMap<String, u32>,
    /// The line each string literal is on, by value.
    pub strings: HashMap<String, u32>,
}

/// A location within a source file, used for the ``#:`` reference of an
/// entry.
#[derive(Debug, Clone)]
pub struct ModuleContext {
    /// The path of the source file.
    pub path: String,
    /// The line within the file.
    pub lineno: u32,
    source: Rc<SourceInfo>,
}

impl ModuleContext {
    /// A location at line `lineno` of `path`, which has the definitions in
    /// `source`.
    pub fn new(path: impl Into<String>, lineno: u32, source: Rc<SourceInfo>) -> Self {
        ModuleContext {
            path: path.into(),
            lineno,
            source,
        }
    }

    fn at(&self, lineno: Option<u32>) -> Self {
        ModuleContext {
            lineno: lineno.unwrap_or(self.lineno),
            ..self.clone()
        }
    }

    /// The location of the definition of class `name`, or this location if
    /// the class is not defined in the file.
    pub fn from_class(&self, name: &str) -> Self {
        let lineno = self.source.classes.get(name).copied();
        if lineno.is_none() {
            log::debug!(target: "brz", "Definition of {name:?} not found in {:?}", self.path);
        }
        self.at(lineno)
    }

    /// The location of the docstring of class `name`, or this location if
    /// the class has no docstring in the file.
    pub fn from_docstring(&self, name: &str) -> Self {
        let lineno = self.source.docstrings.get(name).copied();
        if lineno.is_none() {
            log::debug!(target: "brz", "Docstring of {name:?} not found in {:?}", self.path);
        }
        self.at(lineno)
    }

    /// The location of the string literal `s`, or this location if the
    /// string does not occur as a literal in the file.
    pub fn from_string(&self, s: &str) -> Self {
        let lineno = self.source.strings.get(s).copied();
        if lineno.is_none() {
            log::debug!(
                target: "brz",
                "String {:?} not found in {:?}",
                s.chars().take(20).collect::<String>(),
                self.path
            );
        }
        self.at(lineno)
    }
}

/// Writes message entries in ``.pot`` format, by default skipping messages
/// that were already written.
#[derive(Debug)]
pub struct PotExporter {
    seen: Option<HashSet<String>>,
}

impl PotExporter {
    /// A new exporter; with `include_duplicates`, a message is written again
    /// each time it is exported.
    pub fn new(include_duplicates: bool) -> Self {
        PotExporter {
            seen: (!include_duplicates).then(HashSet::new),
        }
    }

    /// Write the entry for message `s` found at `path`:`lineno`, with an
    /// optional translator comment.
    pub fn poentry(
        &mut self,
        out: &mut dyn Write,
        path: &str,
        lineno: u32,
        s: &str,
        comment: Option<&str>,
    ) -> io::Result<()> {
        if let Some(seen) = &mut self.seen {
            if !seen.insert(s.to_string()) {
                return Ok(());
            }
        }
        log::debug!(
            target: "brz",
            "Exporting msg {:?} at line {lineno} in {path:?}",
            s.chars().take(20).collect::<String>()
        );
        writeln!(out, "#: {path}:{lineno}")?;
        if let Some(comment) = comment {
            writeln!(out, "# {comment}")?;
        }
        write!(out, "msgid {}\nmsgstr \"\"\n\n", normalize(s))
    }

    /// Write the entry for message `s`, located by its literal in `context`.
    pub fn poentry_in_context(
        &mut self,
        out: &mut dyn Write,
        context: &ModuleContext,
        s: &str,
        comment: Option<&str>,
    ) -> io::Result<()> {
        let context = context.from_string(s);
        self.poentry(out, &context.path, context.lineno, s, comment)
    }

    /// Write one entry per paragraph of `msgid` that `include` accepts,
    /// starting at line `lineno` of `path`.
    ///
    /// The line number advances only past included paragraphs, as it always
    /// has.
    pub fn poentry_per_paragraph(
        &mut self,
        out: &mut dyn Write,
        path: &str,
        mut lineno: u32,
        msgid: &str,
        include: impl Fn(&str) -> bool,
    ) -> io::Result<()> {
        for p in msgid.split("\n\n").filter(|p| include(p)) {
            self.poentry(out, path, lineno, p, None)?;
            lineno += p.matches('\n').count() as u32 + 2;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn output(f: impl FnOnce(&mut PotExporter, &mut Vec<u8>)) -> String {
        let mut exporter = PotExporter::new(false);
        let mut out = Vec::new();
        f(&mut exporter, &mut out);
        String::from_utf8(out).unwrap()
    }

    #[test]
    fn escape_simple() {
        assert_eq!("foobar", escape("foobar"));
        assert_eq!(
            "foo\\nbar\\r\\tbaz\\\\\\\"spam\\\"",
            escape("foo\nbar\r\tbaz\\\"spam\"")
        );
    }

    #[test]
    fn escape_backslash_sequences() {
        assert_eq!("\\\\r \\\\\\n", escape("\\r \\\n"));
    }

    #[test]
    fn normalize_single_line() {
        assert_eq!("\"foobar\"", normalize("foobar"));
        assert_eq!("\"foo\\\"bar\"", normalize("foo\"bar"));
    }

    #[test]
    fn normalize_multi_line() {
        assert_eq!("\"\"\n\"foo\\n\"\n\"bar\\n\"", normalize("foo\nbar\n"));
        assert_eq!(
            "\"\"\n\"\\n\"\n\"foo\\n\"\n\"bar\\n\"",
            normalize("\nfoo\nbar\n")
        );
        assert_eq!("\"\"\n\"foo\\n\"\n\"bar\"", normalize("foo\nbar"));
    }

    #[test]
    fn normalize_lone_newline() {
        assert_eq!("\"\"\n\"\\n\"", normalize("\n"));
    }

    #[test]
    fn cleandoc_removes_common_indent() {
        assert_eq!(
            "Summary.\n\n  Indented.\nBody.",
            cleandoc("  Summary.\n\n      Indented.\n    Body.\n    ")
        );
    }

    #[test]
    fn cleandoc_strips_blank_lines() {
        assert_eq!("Text.", cleandoc("\n\n    Text.\n\n"));
        assert_eq!("", cleandoc(""));
        assert_eq!("  ", cleandoc("\n  \n"));
    }

    #[test]
    fn cleandoc_keeps_whitespace_only_lines_beyond_margin() {
        assert_eq!("a\n  \nb", cleandoc("a\n      \n    b"));
    }

    #[test]
    fn cleandoc_expands_tabs() {
        assert_eq!("a\nb\n    c", cleandoc("a\n\tb\n\t    c"));
        assert_eq!("x       y", cleandoc("x\ty"));
    }

    #[test]
    fn usage_paragraph() {
        assert!(is_usage_paragraph(":Usage:\n    brz demo"));
        assert!(!is_usage_paragraph(":Examples:\n    brz demo"));
        assert!(!is_usage_paragraph(""));
    }

    fn source(classes: &[(&str, u32)], strings: &[(&str, u32)]) -> Rc<SourceInfo> {
        Rc::new(SourceInfo {
            classes: classes.iter().map(|(k, v)| (k.to_string(), *v)).collect(),
            strings: strings.iter().map(|(k, v)| (k.to_string(), *v)).collect(),
            ..Default::default()
        })
    }

    #[test]
    fn context_from_class() {
        let context = ModuleContext::new("cls.py", 1, source(&[("A", 5), ("B", 7)], &[]));
        let a = context.from_class("A");
        assert_eq!(("cls.py", 5), (a.path.as_str(), a.lineno));
        assert_eq!(7, a.from_class("B").lineno);
        assert_eq!(1, context.lineno);
    }

    #[test]
    fn context_from_class_missing() {
        let context = ModuleContext::new("cls.py", 3, source(&[("A", 15)], &[]));
        assert_eq!(3, context.from_class("M").lineno);
        assert_eq!(15, context.from_class("A").from_class("M").lineno);
    }

    #[test]
    fn context_from_docstring() {
        let source = Rc::new(SourceInfo {
            docstrings: [("A".to_string(), 6)].into(),
            ..Default::default()
        });
        let context = ModuleContext::new("doc.py", 5, source);
        assert_eq!(6, context.from_docstring("A").lineno);
        assert_eq!(5, context.from_docstring("B").lineno);
    }

    #[test]
    fn context_from_string() {
        let context = ModuleContext::new("str.py", 4, source(&[], &[("one", 14), ("line\n", 21)]));
        assert_eq!(14, context.from_string("one").lineno);
        assert_eq!(4, context.from_string("not there").lineno);
        assert_eq!(
            21,
            context
                .from_string("line\n")
                .from_string("not there")
                .lineno
        );
    }

    #[test]
    fn poentry() {
        let pot = output(|e, out| {
            e.poentry(out, "dummy", 1, "spam", None).unwrap();
            e.poentry(out, "dummy", 2, "ham", Some("EGG")).unwrap();
        });
        assert_eq!(
            "#: dummy:1\nmsgid \"spam\"\nmsgstr \"\"\n\n\
             #: dummy:2\n# EGG\nmsgid \"ham\"\nmsgstr \"\"\n\n",
            pot
        );
    }

    #[test]
    fn poentry_skips_duplicates() {
        let pot = output(|e, out| {
            e.poentry(out, "dummy", 1, "spam", None).unwrap();
            e.poentry(out, "dummy", 2, "spam", Some("EGG")).unwrap();
        });
        assert_eq!("#: dummy:1\nmsgid \"spam\"\nmsgstr \"\"\n\n", pot);
    }

    #[test]
    fn poentry_includes_duplicates() {
        let mut exporter = PotExporter::new(true);
        let mut out = Vec::new();
        let context = ModuleContext::new("mod.py", 1, Rc::default());
        exporter
            .poentry_in_context(&mut out, &context, "Common line.", None)
            .unwrap();
        exporter
            .poentry_in_context(&mut out, &context.at(Some(3)), "Common line.", None)
            .unwrap();
        assert_eq!(
            "#: mod.py:1\nmsgid \"Common line.\"\nmsgstr \"\"\n\n\
             #: mod.py:3\nmsgid \"Common line.\"\nmsgstr \"\"\n\n",
            String::from_utf8(out).unwrap()
        );
    }

    #[test]
    fn poentry_in_context_uses_string_line() {
        let context = ModuleContext::new("local.py", 3, source(&[], &[("Literally.", 17)]));
        let pot = output(|e, out| {
            e.poentry_in_context(out, &context, "Literally.", Some("help"))
                .unwrap();
            e.poentry_in_context(out, &context, "Elsewhere.", None)
                .unwrap();
        });
        assert_eq!(
            "#: local.py:17\n# help\nmsgid \"Literally.\"\nmsgstr \"\"\n\n\
             #: local.py:3\nmsgid \"Elsewhere.\"\nmsgstr \"\"\n\n",
            pot
        );
    }

    #[test]
    fn poentry_per_paragraph_single() {
        let pot = output(|e, out| {
            e.poentry_per_paragraph(out, "dummy", 10, "foo\nbar\nbaz\n", |_| true)
                .unwrap();
        });
        assert_eq!(
            "#: dummy:10\nmsgid \"\"\n\"foo\\n\"\n\"bar\\n\"\n\"baz\\n\"\nmsgstr \"\"\n\n",
            pot
        );
    }

    #[test]
    fn poentry_per_paragraph_multi() {
        let pot = output(|e, out| {
            e.poentry_per_paragraph(
                out,
                "dummy",
                10,
                "spam\nham\negg\n\nSPAM\nHAM\nEGG\n",
                |_| true,
            )
            .unwrap();
        });
        assert_eq!(
            "#: dummy:10\nmsgid \"\"\n\"spam\\n\"\n\"ham\\n\"\n\"egg\"\nmsgstr \"\"\n\n\
             #: dummy:14\nmsgid \"\"\n\"SPAM\\n\"\n\"HAM\\n\"\n\"EGG\\n\"\nmsgstr \"\"\n\n",
            pot
        );
    }

    #[test]
    fn poentry_per_paragraph_excludes_usage() {
        let doc = cleandoc(
            "A sample command.

            :Usage:
                bzr demo

            :Examples:
                Example 1::

                    cmd arg1

            Blah Blah Blah
            ",
        );
        let pot = output(|e, out| {
            e.poentry_per_paragraph(out, "demo.py", 1, &doc, |p| !is_usage_paragraph(p))
                .unwrap();
        });
        assert_eq!(
            "#: demo.py:1\nmsgid \"A sample command.\"\nmsgstr \"\"\n\n\
             #: demo.py:3\nmsgid \"\"\n\":Examples:\\n\"\n\"    Example 1::\"\nmsgstr \"\"\n\n\
             #: demo.py:6\nmsgid \"        cmd arg1\"\nmsgstr \"\"\n\n\
             #: demo.py:8\nmsgid \"Blah Blah Blah\"\nmsgstr \"\"\n\n",
            pot
        );
    }
}
