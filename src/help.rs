use regex::Regex;
use std::convert::TryFrom;

pub enum HelpContents {
    Text(&'static str),
    Callback(Box<dyn Fn(&HelpTopic) -> String + Sync + Send>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Section {
    Command,
    Concept,
    Hidden,
    List,
    Plugin,
}

impl TryFrom<&str> for Section {
    type Error = String;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value {
            "command" => Ok(Section::Command),
            "concept" => Ok(Section::Concept),
            "hidden" => Ok(Section::Hidden),
            "list" => Ok(Section::List),
            "plugin" => Ok(Section::Plugin),
            _ => Err(format!("Unknown help section: {}", value)),
        }
    }
}

pub struct HelpTopic {
    pub name: &'static str,
    pub contents: HelpContents,
    pub summary: &'static str,
    pub section: Section,
}

impl HelpTopic {
    pub fn get_contents(&self) -> String {
        match self.contents {
            HelpContents::Text(text) => text.to_string(),
            HelpContents::Callback(ref callback) => callback(self),
        }
    }

    pub fn get_summary(&self) -> String {
        self.summary.to_string()
    }

    pub fn get_section(&self) -> Section {
        self.section
    }

    pub fn get_name(&self) -> String {
        self.name.to_string()
    }

    /// Return a string with the help for this topic.
    ///
    /// Args:
    ///   additional_see_also: Additional help topics to be
    ///   cross-referenced.
    /// plain: if False, raw help (reStructuredText) is
    ///   returned instead of plain text.
    pub fn get_help_text(&self, additional_see_also: Vec<&str>, plain: bool) -> String {
        let mut text = String::new();
        text.push_str(self.get_contents().as_str());
        let see_also = format_see_also(&additional_see_also);
        text.push_str(see_also.as_str());
        if plain {
            text = help_as_plain_text(text.as_str());
        }
        #[cfg(feature = "i18n")]
        {
            text = crate::i18n::gettext_per_paragraph(text.as_str());
        }
        text
    }
}

pub fn format_see_also(additional_see_also: &[&str]) -> String {
    let mut text = String::new();
    if !additional_see_also.is_empty() {
        text.push_str("\nSee also: ");
        text.push_str(additional_see_also.join(", ").as_str());
        text.push('\n');
    }
    text
}

/// Minimal converter of reStructuredText to plain text.
pub fn help_as_plain_text(text: &str) -> String {
    lazy_static::lazy_static! {
        static ref RE_STANDALONE_BLOCK: Regex = Regex::new(r"(?m)^\s*::\n\s*$").unwrap();
        static ref RE_DOC_REF: Regex = Regex::new(r":doc:`(.+?)-help`").unwrap();
    };
    // Remove the standalone code block marker
    let text = RE_STANDALONE_BLOCK.replace_all(text, "");
    let lines = text.split('\n');
    let mut ret = lines
        .map(|l| {
            let l = if l.starts_with(':') {
                l[1..].to_string()
            } else if l.ends_with("::") {
                l[..l.len() - 1].to_string()
            } else {
                l.to_string()
            };
            // Map :doc:`xxx-help` to ``brz help xxx``
            RE_DOC_REF
                .replace_all(l.as_str(), r"``brz help \1``")
                .to_string()
        })
        .collect::<Vec<_>>()
        .join("\n");
    if !ret.ends_with('\n') {
        ret.push('\n');
    }
    ret
}

impl HelpTopic {
    pub const fn new(
        section: Section,
        name: &'static str,
        summary: &'static str,
        contents: HelpContents,
    ) -> Self {
        Self {
            name,
            contents,
            summary,
            section,
        }
    }
}

inventory::collect!(HelpTopic);

const GLOBAL_OPTIONS: &str = r#"Global Options

These options may be used with any command, and may appear in front of any
command.  (e.g. ``brz --profile help``).

--version      Print the version number. Must be supplied before the command.
--no-aliases   Do not process command aliases when running this command.
--builtin      Use the built-in version of a command, not the plugin version.
               This does not suppress other plugin effects.
--no-plugins   Do not process any plugins.
--no-l10n      Do not translate messages.
--concurrency  Number of processes that can be run concurrently (selftest).

--profile      Profile execution using the hotshot profiler.
--lsprof       Profile execution using the lsprof profiler.
--lsprof-file  Profile execution using the lsprof profiler, and write the
               results to a specified file.  If the filename ends with ".txt",
               text format will be used.  If the filename either starts with
               "callgrind.out" or end with ".callgrind", the output will be
               formatted for use with KCacheGrind. Otherwise, the output
               will be a pickle.
--coverage     Generate line coverage report in the specified directory.

-Oname=value   Override the ``name`` config option setting it to ``value`` for
               the duration of the command.  This can be used multiple times if
               several options need to be overridden.

See https://www.breezy-vcs.org/developers/profiling.html for more
information on profiling.

A number of debug flags are also available to assist troubleshooting and
development.  See :doc:`debug-flags-help`.
"#;

inventory::submit! {
    HelpTopic::new(
        Section::List,
        "global-options",
        "Options that control how Breezy runs",
        HelpContents::Text(GLOBAL_OPTIONS))
}

pub fn get_topic(name: &str) -> Option<&'static HelpTopic> {
    iter_topics().find(|t| t.name == name)
}

pub fn iter_topics() -> impl Iterator<Item = &'static HelpTopic> {
    inventory::iter::<HelpTopic>.into_iter()
}
