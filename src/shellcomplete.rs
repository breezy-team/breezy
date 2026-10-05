//! Output formatting for ``brz shell-complete``.

/// The listing line for the command (or alias) `name`: ``name:summary``,
/// where the summary is the first line of `help` lowercased and with its last
/// character (normally a full stop) dropped, or just ``name`` without help.
pub fn command_line(name: &str, help: Option<&str>) -> String {
    let Some(help) = help else {
        return name.to_string();
    };
    let first_line = help.lines().next().unwrap_or_default().to_lowercase();
    let mut chars = first_line.chars();
    chars.next_back();
    format!("{name}:{}", chars.as_str())
}

/// The completion line for the option `name`, with its short name if any.
pub fn option_line(name: &str, short_name: Option<&str>) -> String {
    match short_name {
        Some(short) => format!("\"(--{name} -{short})\"{{--{name},-{short}}}"),
        None => format!("--{name}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn command_line_strips_full_stop() {
        assert_eq!(
            "version:show version of brz",
            command_line("version", Some("Show version of brz.\n\nMore text."))
        );
    }

    #[test]
    fn command_line_drops_last_char_without_full_stop() {
        assert_eq!("foo:do somethin", command_line("foo", Some("Do something")));
    }

    #[test]
    fn command_line_without_help() {
        assert_eq!("foo", command_line("foo", None));
    }

    #[test]
    fn command_line_empty_help() {
        assert_eq!("foo:", command_line("foo", Some("")));
    }

    #[test]
    fn option_line_with_short_name() {
        assert_eq!("\"(--help -h)\"{--help,-h}", option_line("help", Some("h")));
    }

    #[test]
    fn option_line_without_short_name() {
        assert_eq!("--usage", option_line("usage", None));
    }
}
