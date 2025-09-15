use std::io::Read;
use std::io::{stdout, Write};

#[cfg(unix)]
use termion::color::{Bg, Color, Fg, Reset};
#[cfg(unix)]
use termion::is_tty;

pub fn terminal_size() -> std::io::Result<(u16, u16)> {
    #[cfg(unix)]
    {
        termion::terminal_size()
    }
    #[cfg(windows)]
    {
        // Windows terminal size detection
        // For now, return a default size
        Ok((80, 24))
    }
}

pub fn has_ansi_colors() -> bool {
    #[cfg(windows)]
    {
        return false;
    }

    #[cfg(unix)]
    {
        if !is_tty(&stdout()) {
            return false;
        }

        use termion::color::DetectColors;
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

#[cfg(unix)]
pub fn colorstring<F: Color, B: Color>(
    text: &[u8],
    fgcolor: Option<F>,
    bgcolor: Option<B>,
) -> Vec<u8> {
    let mut ret = Vec::new();

    if let Some(color) = fgcolor {
        ret.write_all(Fg(color).to_string().as_bytes()).unwrap();
    }

    if let Some(color) = bgcolor {
        ret.write_all(Bg(color).to_string().as_bytes()).unwrap();
    }

    ret.extend_from_slice(text);

    ret.write_all(Fg(Reset).to_string().as_bytes()).unwrap();
    ret.write_all(Bg(Reset).to_string().as_bytes()).unwrap();

    ret
}

#[cfg(windows)]
pub fn colorstring(
    text: &[u8],
    _fgcolor: Option<()>,
    _bgcolor: Option<()>,
) -> Vec<u8> {
    // On Windows, just return the text without colors for now
    text.to_vec()
}

#[cfg(unix)]
pub fn getchar() -> Result<char, std::io::Error> {
    use std::os::unix::io::AsRawFd;
    let stdin = std::io::stdin();
    let fd = stdin.as_raw_fd();

    // Save the current terminal settings
    let original_termios = termios::Termios::from_fd(fd)?;

    // Set the terminal to raw mode
    let mut raw_termios = original_termios;
    termios::cfmakeraw(&mut raw_termios);
    termios::tcsetattr(fd, termios::TCSADRAIN, &raw_termios)?;

    // Read a single character from stdin
    let mut buffer = [0u8; 1];
    stdin.lock().read_exact(&mut buffer)?;

    // Restore the original terminal settings
    termios::tcsetattr(fd, termios::TCSADRAIN, &original_termios)?;

    // Convert the read byte to a char
    let ch = buffer[0] as char;
    Ok(ch)
}

#[cfg(windows)]
pub fn getchar() -> Result<char, std::io::Error> {
    // Simple Windows implementation - just read from stdin
    let mut buffer = [0u8; 1];
    std::io::stdin().read_exact(&mut buffer)?;
    Ok(buffer[0] as char)
}