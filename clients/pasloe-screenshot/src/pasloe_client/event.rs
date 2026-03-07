use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// 发送到 pasloe 的截图事件
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScreenshotEvent {
    pub source_id: String,
    #[serde(rename = "type")]
    pub event_type: String,
    pub data: ScreenshotPayload,
    pub session_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScreenshotPayload {
    pub url: String,
    pub monitor_id: String,
}

impl ScreenshotEvent {
    pub fn new(url: String, monitor_id: String, timestamp: DateTime<Utc>) -> Self {
        Self {
            source_id: "pasloe-screenshot".to_string(),
            event_type: "screenshot.captured".to_string(),
            data: ScreenshotPayload { url, monitor_id },
            session_id: None,
        }
    }
}
