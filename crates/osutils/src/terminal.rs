use std::io::stdout;
use termion::is_tty;

pub fn terminal_size() -> std::io::Result<(u16, u16)> {
    termion::terminal_size()
}

pub fn has_ansi_colors() -> bool {
    #[cfg(windows)]
    {
        return false;
    }

    if !is_tty(&stdout()) {
        return false;
    }

    #[cfg(not(windows))]
    {
        use termion::color::{AnsiValue, Bg, DetectColors};
        use termion::raw::IntoRawMode;

        match stdout().into_raw_mode() {
            Ok(mut term) => match term.available_colors() {
                Ok(count) => count >= 8,
                Err(_) => false,
            },
            Err(_) => false,
        }
    }
}
