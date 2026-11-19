//! Collecting the messages for ``brz export-pot`` from the live Python breezy.
//!
//! The messages are attributes of Python objects (command docstrings, option
//! help, error formats, help topics) and their locations come from parsing
//! the Python source of the modules defining them; the formatting is in
//! [`crate::export_pot`].

use crate::command::{CommandContext, CommandError};
use crate::export_pot::{cleandoc, is_usage_paragraph, ModuleContext, PotExporter, SourceInfo};
use crate::i18n::gettext;
use pyo3::prelude::*;
use pyo3::types::{PyString, PyType};
use std::collections::HashMap;
use std::rc::Rc;

/// Exports the messages of one run, with the parsed source of each module
/// seen so far.
struct Exporter<'a, 'py> {
    py: Python<'py>,
    ctx: &'a mut dyn CommandContext,
    pot: PotExporter,
    modules: HashMap<String, ModuleContext>,
}

/// Write the messages of breezy, or with `plugin` of just the commands of
/// that plugin, in ``.pot`` format to the command's output.
pub fn export_pot(
    py: Python<'_>,
    ctx: &mut dyn CommandContext,
    plugin: Option<&str>,
    include_duplicates: bool,
) -> Result<(), CommandError> {
    let mut exporter = Exporter {
        py,
        ctx,
        pot: PotExporter::new(include_duplicates),
        modules: HashMap::new(),
    };
    match plugin {
        None => {
            exporter.standard_options()?;
            exporter.command_helps(None)?;
            exporter.error_messages()?;
            exporter.help_topics()?;
        }
        Some(plugin) => exporter.command_helps(Some(plugin))?,
    }
    Ok(())
}

/// The class, class docstring and string literal line numbers of the Python
/// source `text`.
fn parse_source(py: Python<'_>, text: &str, filename: &str) -> PyResult<SourceInfo> {
    let ast = py.import("ast")?;
    let class_def = ast.getattr("ClassDef")?;
    let constant = ast.getattr("Constant")?;
    let expr = ast.getattr("Expr")?;
    let tree = ast.call_method1("parse", (text, filename))?;
    let mut info = SourceInfo::default();
    for node in ast.call_method1("walk", (tree,))?.try_iter()? {
        let node = node?;
        let lineno = || node.getattr("lineno")?.extract::<u32>();
        if node.is_instance(&class_def)? {
            let name: String = node.getattr("name")?.extract()?;
            // Matched by position rather than by value, as __doc__ has its
            // indentation stripped since Python 3.13.
            let first = node.getattr("body")?.get_item(0)?;
            if first.is_instance(&expr)? {
                let value = first.getattr("value")?;
                if value.is_instance(&constant)?
                    && value.getattr("value")?.is_instance_of::<PyString>()
                {
                    info.docstrings
                        .insert(name.clone(), value.getattr("lineno")?.extract()?);
                }
            }
            info.classes.insert(name, lineno()?);
        } else if node.is_instance(&constant)? {
            if let Ok(s) = node.getattr("value")?.cast_into::<PyString>() {
                info.strings.insert(s.to_str()?.to_string(), lineno()?);
            }
        }
    }
    Ok(info)
}

/// The Python ``repr`` of `s`, for quoting names in translator comments.
fn repr(py: Python<'_>, s: &str) -> PyResult<String> {
    Ok(PyString::new(py, s).repr()?.to_str()?.to_string())
}

impl<'py> Exporter<'_, 'py> {
    /// The location of `obj`: its class definition for a class, otherwise the
    /// start of its module.
    fn context(&mut self, obj: &Bound<'py, PyAny>) -> PyResult<ModuleContext> {
        let inspect = self.py.import("inspect")?;
        let module = inspect.call_method1("getmodule", (obj,))?;
        let name: String = module.getattr("__name__")?.extract()?;
        let context = match self.modules.get(&name) {
            Some(context) => context.clone(),
            None => {
                let context = self.module_context(&module)?;
                self.modules.insert(name, context.clone());
                context
            }
        };
        Ok(match obj.cast::<PyType>() {
            Ok(cls) => context.from_class(&cls.name()?.to_string()),
            Err(_) => context,
        })
    }

    fn module_context(&self, module: &Bound<'py, PyAny>) -> PyResult<ModuleContext> {
        let inspect = self.py.import("inspect")?;
        let sourcepath = inspect.call_method1("getsourcefile", (module,))?;
        // TODO: fix this to do the right thing rather than rely on cwd
        let relpath: String = self
            .py
            .import("os.path")?
            .call_method1("relpath", (sourcepath,))?
            .extract()?;
        let lines: Vec<String> = inspect
            .call_method1("findsource", (module,))?
            .get_item(0)?
            .extract()?;
        let filename: String = module.getattr("__file__")?.extract()?;
        let info = parse_source(self.py, &lines.concat(), &filename)?;
        Ok(ModuleContext::new(relpath, 1, Rc::new(info)))
    }

    /// Export the title and the help of each visible switch of the Python
    /// ``Option`` `opt`.
    fn option(
        &mut self,
        context: &ModuleContext,
        opt: &Bound<'py, PyAny>,
        note: &str,
    ) -> Result<(), CommandError> {
        if let Some(hidden) = opt.getattr_opt("hidden")? {
            if hidden.is_truthy()? {
                return Ok(());
            }
        }
        let optname: String = opt.getattr("name")?.extract()?;
        if let Some(title) = opt.getattr_opt("title")? {
            if title.is_truthy()? {
                let title: String = title.extract()?;
                let comment = format!("title of {} {note}", repr(self.py, &optname)?);
                self.pot
                    .poentry_in_context(self.ctx.out(), context, &title, Some(&comment))?;
            }
        }
        for switch in opt.call_method0("iter_switches")?.try_iter()? {
            let (name, _, _, helptxt): (
                String,
                Bound<'py, PyAny>,
                Bound<'py, PyAny>,
                Option<String>,
            ) = switch?.extract()?;
            let name = if name == optname {
                name
            } else if opt.call_method1("is_hidden", (&name,))?.is_truthy()? {
                continue;
            } else {
                format!("{optname}={name}")
            };
            if let Some(helptxt) = helptxt.filter(|h| !h.is_empty()) {
                let comment = format!("help of {} {note}", repr(self.py, &name)?);
                self.pot
                    .poentry_in_context(self.ctx.out(), context, &helptxt, Some(&comment))?;
            }
        }
        Ok(())
    }

    /// Export the standard options (``Option.OPTIONS``), sorted by name.
    fn standard_options(&mut self) -> Result<(), CommandError> {
        let option = self.py.import("breezy.option")?;
        let options = option.getattr("Option")?.getattr("OPTIONS")?;
        let context = self.context(option.as_any())?;
        let mut names = options
            .try_iter()?
            .map(|name| name?.extract())
            .collect::<PyResult<Vec<String>>>()?;
        names.sort();
        for name in names {
            let opt = options.get_item(&name)?;
            self.option(&context.from_string(&name), &opt, "option")?;
        }
        Ok(())
    }

    /// Export the help of the Python command `cmd` paragraph by paragraph,
    /// leaving out the ``:Usage:`` section, followed by its own options.
    fn command_help(&mut self, cmd: &Bound<'py, PyAny>) -> Result<(), CommandError> {
        let cls = cmd.get_type();
        let context = self.context(cls.as_any())?;
        let rawdoc: String = cmd.getattr("__doc__")?.extract()?;
        let dcontext = context.from_docstring(&cls.name()?.to_string());
        let doc = cleandoc(&rawdoc);
        self.pot.poentry_per_paragraph(
            self.ctx.out(),
            &dcontext.path,
            dcontext.lineno,
            &doc,
            |p| !is_usage_paragraph(p),
        )?;

        let cmd_name: String = cmd.call_method0("name")?.extract()?;
        let note = format!("option of {} command", repr(self.py, &cmd_name)?);
        for opt in cmd.getattr("takes_options")?.try_iter()? {
            let opt = opt?;
            // Names in the option list refer to standard options, exported
            // separately.
            if !opt.is_instance_of::<PyString>() {
                self.option(&context, &opt, &note)?;
            }
        }
        Ok(())
    }

    /// Export the help of the visible commands: the builtin ones and those of
    /// the plugins shipped with breezy, or only those of `plugin_name`.
    fn command_helps(&mut self, plugin_name: Option<&str>) -> Result<(), CommandError> {
        if plugin_name.is_none() {
            for name in crate::commands::builtin_command_names(self.py)? {
                let cmd =
                    crate::commands::get_cmd_object(self.py, &name, false)?.into_bound(self.py);
                if cmd.getattr("hidden")?.is_truthy()? {
                    continue;
                }
                self.ctx.note(
                    &gettext("Exporting messages from builtin command: %s")
                        .replacen("%s", &name, 1),
                )?;
                self.command_help(&cmd)?;
            }
        }

        let plugins = self.py.import("breezy.plugin")?.call_method0("plugins")?;
        if let Some(plugin_name) = plugin_name {
            if !plugins.contains(plugin_name)? {
                return Err(CommandError::User(
                    gettext("Plugin {} is not loaded").replacen("{}", plugin_name, 1),
                ));
            }
        }
        let breezy_dir: String = self
            .py
            .import("breezy")?
            .getattr("__path__")?
            .get_item(0)?
            .extract()?;
        let mut core_plugins = Vec::new();
        for item in plugins.call_method0("items")?.try_iter()? {
            let (name, plugin): (String, Bound<'py, PyAny>) = item?.extract()?;
            let path: String = plugin.call_method0("path")?.extract()?;
            if path.starts_with(&breezy_dir) {
                core_plugins.push(name);
            }
        }

        for name in crate::commands::plugin_command_names() {
            let cmd = crate::commands::get_cmd_object(self.py, &name, false)?.into_bound(self.py);
            if cmd.getattr("hidden")?.is_truthy()? {
                continue;
            }
            let cmd_plugin: Option<String> = cmd.call_method0("plugin_name")?.extract()?;
            let wanted = match plugin_name {
                Some(plugin_name) => cmd_plugin.as_deref() == Some(plugin_name),
                // TODO: Support extracting from third party plugins.
                None => cmd_plugin
                    .as_ref()
                    .is_some_and(|p| core_plugins.contains(p)),
            };
            if !wanted {
                continue;
            }
            self.ctx.note(
                &gettext("Exporting messages from plugin command: {0} in {1}")
                    .replacen("{0}", &name, 1)
                    .replacen("{1}", cmd_plugin.as_deref().unwrap_or_default(), 1),
            )?;
            self.command_help(&cmd)?;
        }
        Ok(())
    }

    /// Export the format strings of the user-facing errors in
    /// ``breezy.errors``.
    fn error_messages(&mut self) -> Result<(), CommandError> {
        let errors = self.py.import("breezy.errors")?;
        let context = self.context(errors.as_any())?;
        let base = errors
            .getattr("BzrError")?
            .cast_into::<PyType>()
            .map_err(PyErr::from)?;
        for name in errors.dir()? {
            let name: String = name.extract()?;
            let Ok(klass) = errors.getattr(&name)?.cast_into::<PyType>() else {
                continue;
            };
            if klass.is(&base) || !klass.is_subclass(&base)? {
                continue;
            }
            if klass.getattr("internal_error")?.is_truthy()? {
                continue;
            }
            let Some(fmt) = klass.getattr_opt("_fmt")? else {
                continue;
            };
            if !fmt.is_truthy()? {
                continue;
            }
            let fmt: String = fmt.extract()?;
            self.ctx
                .note(&gettext("Exporting message from error: %s").replacen("%s", &name, 1))?;
            self.pot
                .poentry_in_context(self.ctx.out(), &context, &fmt, None)?;
        }
        Ok(())
    }

    /// Export the text, paragraph by paragraph, and the summary of each help
    /// topic.
    fn help_topics(&mut self) -> Result<(), CommandError> {
        // A dynamic topic replaces a static one with the same name, as in the
        // help topic registry.
        let topics = crate::help::iter_static_topics()
            .map(|t| match crate::help::get_dynamic_topic(t.name) {
                Some(d) => (
                    d.name.clone(),
                    d.get_contents().into_owned(),
                    d.summary.clone(),
                ),
                None => (
                    t.name.to_string(),
                    t.get_contents().into_owned(),
                    t.summary.to_string(),
                ),
            })
            .chain(crate::help::iter_dynamic_topics().map(|d| {
                (
                    d.name.clone(),
                    d.get_contents().into_owned(),
                    d.summary.clone(),
                )
            }));
        for (name, contents, summary) in topics {
            let path = format!("dummy/help_topics/{name}/detail.txt");
            self.pot
                .poentry_per_paragraph(self.ctx.out(), &path, 1, &contents, |_| true)?;
            let path = format!("dummy/help_topics/{name}/summary.txt");
            self.pot.poentry(self.ctx.out(), &path, 1, &summary, None)?;
        }
        Ok(())
    }
}
