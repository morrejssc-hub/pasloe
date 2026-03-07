use anyhow::{Result, anyhow};
use chrono::{DateTime, Utc};
use xcap::Window;

use crate::capture::utils::hamming_distance;
use crate::event::CaptureResult;

/// 安全的窗口捕获封装
///
/// 专注于捕获当前焦点窗口的截图,支持基于时间和图像相似度的去重
pub struct SafeWindow {
    last_capture_time: Option<DateTime<Utc>>,
    last_capture_dhash: Option<u64>,
    last_window_info: Option<WindowInfo>,
}

/// 窗口信息快照
#[derive(Debug, Clone)]
struct WindowInfo {
    id: u32,
    title: String,
    app_name: String,
}

impl SafeWindow {
    pub fn new() -> Self {
        Self {
            last_capture_time: None,
            last_capture_dhash: None,
            last_window_info: None,
        }
    }

    /// 捕获当前焦点窗口的截图
    ///
    /// # 参数
    /// - `enforce_interval`: 强制截图的最小时间间隔(毫秒)
    /// - `dhash_threshold`: dhash 汉明距离阈值,小于此值认为图像相似
    /// - `dhash_resolution`: dhash 计算的分辨率
    /// - `enable_ocr`: 是否启用 OCR(预留,暂未实现)
    ///
    /// # 返回
    /// - `Ok(Some(CaptureResult))`: 成功捕获新截图
    /// - `Ok(None)`: 由于去重策略,跳过此次捕获
    /// - `Err`: 捕获失败
    pub fn capture_once(
        &mut self,
        enforce_interval: u64,
        dhash_threshold: u32,
        dhash_resolution: u32,
        _enable_ocr: bool, // 预留 OCR 功能
    ) -> Result<Option<CaptureResult>> {
        let now = Utc::now();

        // 获取当前焦点窗口
        let focused_window = Self::get_focused_window()?;

        // 获取窗口信息
        let window_info = WindowInfo {
            id: focused_window.id()?,
            title: focused_window
                .title()
                .unwrap_or_else(|_| "Unknown".to_string()),
            app_name: focused_window
                .app_name()
                .unwrap_or_else(|_| "Unknown".to_string()),
        };

        // 检查窗口是否可以截图
        if focused_window.is_minimized().unwrap_or(false) {
            return Ok(None); // 最小化窗口无法截图
        }

        // 捕获窗口图像
        let image = focused_window
            .capture_image()
            .map_err(|e| anyhow!("Failed to capture window image: {:?}", e))?;

        // 计算图像 hash
        let dhash = crate::capture::utils::dHash(&image, dhash_resolution);

        // 去重检查
        if let Some(last_time) = self.last_capture_time {
            if let (Some(last_hash), Some(last_info)) =
                (self.last_capture_dhash, &self.last_window_info)
            {
                let delta = (now - last_time).num_milliseconds();
                if delta < 0 {
                    // 时钟回退,记录警告并继续
                    tracing::warn!("Clock went backwards, forcing capture");
                } else {
                    let delta = delta as u64;

                    // 检查是否是同一个窗口
                    let same_window = last_info.id == window_info.id;

                    // 时间间隔检查
                    let time_too_soon = delta < enforce_interval;

                    // 图像相似度检查
                    let hash_too_similar = hamming_distance(dhash, last_hash) < dhash_threshold;

                    // 如果是同一个窗口,时间太近且图像相似,则跳过
                    if same_window && time_too_soon && hash_too_similar {
                        return Ok(None);
                    }
                }
            }
        }

        // 更新状态
        self.last_capture_time = Some(now);
        self.last_capture_dhash = Some(dhash);
        self.last_window_info = Some(window_info.clone());

        // 生成窗口 ID (格式: "window_{app_name}_{window_id}")
        let capture_id = format!("window_{}_{}", window_info.app_name, window_info.id);

        // TODO: OCR 功能预留位置
        // if enable_ocr {
        //     let ocr_result = perform_ocr(&image)?;
        //     // 将 OCR 结果附加到 CaptureResult 或事件元数据中
        // }

        Ok(Some(CaptureResult::new(capture_id, image, now)))
    }

    /// 获取当前焦点窗口
    ///
    /// 遍历所有窗口,找到焦点窗口
    fn get_focused_window() -> Result<Window> {
        let windows = Window::all().map_err(|e| anyhow!("Failed to get window list: {:?}", e))?;

        for window in windows {
            if window.is_focused().unwrap_or(false) {
                return Ok(window);
            }
        }

        Err(anyhow!("No focused window found"))
    }

    /// 获取上次捕获的窗口信息(用于调试)
    pub fn last_window_info(&self) -> Option<(String, String)> {
        self.last_window_info
            .as_ref()
            .map(|info| (info.app_name.clone(), info.title.clone()))
    }
}

impl Default for SafeWindow {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_safe_window_creation() {
        let window = SafeWindow::new();
        assert!(window.last_capture_time.is_none());
        assert!(window.last_capture_dhash.is_none());
        assert!(window.last_window_info.is_none());
    }

    #[test]
    fn test_window_info_format() {
        let info = WindowInfo {
            id: 12345,
            title: "Test Window".to_string(),
            app_name: "TestApp".to_string(),
        };

        let capture_id = format!("window_{}_{}", info.app_name, info.id);
        assert_eq!(capture_id, "window_TestApp_12345");
    }
}
