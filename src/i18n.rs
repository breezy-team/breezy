use std::path::Path;

static mut ENABLED: bool = false;

pub fn disable() {
    unsafe {
        ENABLED = false;
    }
}

pub fn install(lang: Option<&str>, locale_base: Option<&Path>) -> Result<(), std::io::Error> {
    if unsafe { ENABLED } {
        return Ok(());
    }
    gettextrs::textdomain("brz")?;

    if let Some(lang) = lang {
        gettextrs::setlocale(gettextrs::LocaleCategory::LcAll, lang);
    }
    if let Some(locale_base) = locale_base {
        gettextrs::bindtextdomain("brz", locale_base.join("locale"))?;
    }
    gettextrs::bind_textdomain_codeset("brz", "UTF-8")?;
    unsafe {
        ENABLED = true;
    }
    Ok(())
}

pub fn gettext(msgid: &str) -> String {
    if unsafe { ENABLED } {
        gettextrs::gettext(msgid)
    } else {
        msgid.to_string()
    }
}

pub fn ngettext(msgid: &str, msgid_plural: &str, n: u32) -> String {
    if unsafe { ENABLED } {
        gettextrs::ngettext(msgid, msgid_plural, n)
    } else if n == 1 {
        msgid.to_string()
    } else {
        msgid_plural.to_string()
    }
}

pub fn dgettext(textdomain: &str, msgid: &str) -> String {
    if unsafe { ENABLED } {
        gettextrs::dgettext(textdomain, msgid)
    } else {
        msgid.to_string()
    }
}

pub fn install_plugin(textdomain: &str, locale_base: Option<&Path>) -> Result<(), std::io::Error> {
    if let Some(locale_base) = locale_base {
        gettextrs::bindtextdomain(textdomain, locale_base.join("locale"))?;
    }
    gettextrs::bind_textdomain_codeset(textdomain, "UTF-8")?;
    Ok(())
}
