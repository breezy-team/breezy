use chrono::{DateTime, Local, TimeZone, Utc};

pub fn local_time_offset(t: Option<i64>) -> i64 {
    let timestamp = t.unwrap_or_else(|| Utc::now().timestamp());
    let local_time: DateTime<Local> = Utc.timestamp(timestamp, 0).with_timezone(&Local);
    let utc_time: DateTime<Utc> = Utc.timestamp(timestamp, 0);

    let local_naive_datetime = local_time.naive_utc();
    let utc_naive_datetime = utc_time.naive_utc();

    let offset = local_naive_datetime - utc_naive_datetime;
    offset.num_seconds()
}
