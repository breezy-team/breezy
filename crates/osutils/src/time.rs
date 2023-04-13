use std::time::{SystemTime, UNIX_EPOCH};
use chrono::{DateTime, Local, TimeZone, Utc, FixedOffset};

pub fn local_time_offset(t: Option<i64>) -> i64 {
    let timestamp = t.unwrap_or_else(|| Utc::now().timestamp());
    let local_time: DateTime<Local> = Utc.timestamp(timestamp, 0).with_timezone(&Local);
    let utc_time: DateTime<Utc> = Utc.timestamp(timestamp, 0);

    let local_naive_datetime = local_time.naive_utc();
    let utc_naive_datetime = utc_time.naive_utc();

    let offset = local_naive_datetime - utc_naive_datetime;
    offset.num_seconds()
}

pub fn format_local_date(
    t: i64,
    offset: Option<i32>,
    timezone: Timezone,
    date_fmt: Option<&str>,
    show_offset: bool,
) -> String {
    let offset = offset.unwrap_or(0);
    let tz: FixedOffset = match timezone {
        Timezone::Utc => FixedOffset::east_opt(0).unwrap(),
        Timezone::Original => FixedOffset::east_opt(offset).unwrap(),
        Timezone::Local => *Local::now().offset(),
    };
    let dt: DateTime<FixedOffset> = tz.timestamp(t, 0);
    let date_fmt = date_fmt.unwrap_or("%c");
    let date_str = dt.format(date_fmt).to_string();
    let offset_str = if show_offset {
        let offset_fmt = if offset < 0 { "%z" } else { "%:z" };
        dt.format(offset_fmt).to_string()
    } else {
        "".to_string()
    };
    date_str + &offset_str
}

pub enum Timezone {
    Local,
    Utc,
    Original,
}

pub fn format_delta(delta: i64) -> String {
    let mut delta = delta;
    let direction: &str;
    if delta >= 0 {
        direction = "ago";
    } else {
        direction = "in the future";
        delta = -delta;
    }

    let seconds = delta;
    if seconds < 90 {
        if seconds == 1 {
            return format!("{} second {}", seconds, direction);
        } else {
            return format!("{} seconds {}", seconds, direction);
        }
    }

    let mut minutes = seconds / 60;
    let seconds = seconds % 60;
    let plural_seconds = if seconds == 1 { "" } else { "s" };

    if minutes < 90 {
        if minutes == 1 {
            return format!(
                "{} minute, {} second{} {}",
                minutes, seconds, plural_seconds, direction
            );
        } else {
            return format!(
                "{} minutes, {} second{} {}",
                minutes, seconds, plural_seconds, direction
            );
        }
    }

    let hours = minutes / 60;
    minutes = minutes % 60;
    let plural_minutes = if minutes == 1 { "" } else { "s" };

    if hours == 1 {
        return format!(
            "{} hour, {} minute{} {}",
            hours, minutes, plural_minutes, direction
        );
    } else {
        return format!(
            "{} hours, {} minute{} {}",
            hours, minutes, plural_minutes, direction
        );
    }
}
