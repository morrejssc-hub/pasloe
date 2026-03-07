use anyhow::{Result, anyhow};
use chrono::{DateTime, Utc};
use std::sync::LazyLock;
use tracing::info;
use xcap::Monitor;

use crate::capture::utils::hamming_distance;
use crate::event::CaptureResult;

pub struct SafeMonitor {
    id: String,
    monitor: Monitor,

    last_capture_time: Option<DateTime<Utc>>,
    last_capture_dhash: Option<u64>,
}

// SAFETY: Monitor 的底层句柄在单个任务中独占使用,不会跨线程共享
unsafe impl Send for SafeMonitor {}

// Monitor ID format: "name_width_height_x_y" (e.g., "DP-1_1920_1080_0_0")
static RE: LazyLock<regex::Regex> = LazyLock::new(|| {
    regex::Regex::new(r"(?P<name>.+)_(?P<w>\d+)_(?P<h>\d+)_(?P<x>-?\d+)_(?P<y>-?\d+)")
        .expect("invalid regex")
});

impl SafeMonitor {
    pub fn new(monitor_id: String) -> Result<Self> {
        info!("Creating SafeMonitor for {}", monitor_id);
        let (name, width, height, x, y) = Self::parse_id(&monitor_id)?;
        let monitor = Monitor::from_point(x, y)?;

        let monitor_name = monitor.name()?;
        let monitor_width = monitor.width()?;
        let monitor_height = monitor.height()?;

        if monitor_name != name || monitor_width != width || monitor_height != height {
            return Err(anyhow!(
                "Monitor mismatch: expected '{}' ({}x{}) at ({},{}), got '{}' ({}x{})",
                name,
                width,
                height,
                x,
                y,
                monitor_name,
                monitor_width,
                monitor_height
            ));
        }

        info!("SafeMonitor created for {}", monitor_id);

        Ok(SafeMonitor {
            id: monitor_id,
            monitor: monitor,
            last_capture_time: None,
            last_capture_dhash: None,
        })
    }

    fn parse_id(monitor_id: &str) -> Result<(String, u32, u32, i32, i32)> {
        let cap = RE
            .captures(monitor_id)
            .ok_or_else(|| anyhow!("Invalid monitor ID format: {}", monitor_id))?;
        let name = cap["name"].to_string();
        let width = cap["w"].parse()?;
        let height = cap["h"].parse()?;
        let x = cap["x"].parse()?;
        let y = cap["y"].parse()?;
        Ok((name, width, height, x, y))
    }

    pub fn capture_once(
        &mut self,
        enforce_interval: u64,
        dhash_threshold: u32,
        dhash_resolution: u32,
    ) -> Result<Option<CaptureResult>> {
        let now = Utc::now();
        info!("Starting capture in {}, {}", self.id, now);

        let image = self
            .monitor
            .capture_image()
            .map_err(|e| anyhow!("Failed to capture image: {}", e))?;

        let dhash = crate::capture::utils::dHash(&image, dhash_resolution);
        info!("Captured image with dHash {}", dhash);

        if let Some(last_time) = self.last_capture_time {
            if let Some(last_hash) = self.last_capture_dhash {
                let delta = (now - last_time).num_milliseconds();
                if delta < 0 {
                    self.last_capture_time = Some(now);
                    return Err(anyhow!("Clock went backwards, reset to {}", now));
                }
                let delta = delta as u64;
                let time_too_soon = delta < enforce_interval;

                let hash_too_similar = hamming_distance(dhash, last_hash) < dhash_threshold;
                info!(
                    "Time too soon: {}, hash too similar: {}",
                    time_too_soon, hash_too_similar
                );
                if time_too_soon && hash_too_similar {
                    return Ok(None);
                }
            }
        }
        info!(
            "Current capture in {} should save which dHash is {}",
            self.id, dhash
        );

        self.last_capture_time = Some(now);
        self.last_capture_dhash = Some(dhash);

        Ok(Some(CaptureResult::new(self.id.clone(), image, now)))
    }

    pub fn id(&self) -> &str {
        &self.id
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_id() {
        let (name, width, height, x, y) = SafeMonitor::parse_id("monitor_1920_1080_0_0").unwrap();
        assert_eq!(name, "monitor");
        assert_eq!(width, 1920);
        assert_eq!(height, 1080);
        assert_eq!(x, 0);
        assert_eq!(y, 0);
    }
}
