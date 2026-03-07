use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fmt;
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub pasloe: PasloeConfig,
    pub storage: StorageConfig,
    pub monitors: HashMap<String, MonitorConfig>,
    pub window: WindowConfig,
    pub logging: LoggingConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PasloeConfig {
    pub url: String,
    pub api_key: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageConfig {
    pub s3: S3Config,
    pub local: LocalConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct S3Config {
    pub enable: bool,
    #[serde(default)]
    pub prefix: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalConfig {
    pub enable: bool,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MonitorConfig {
    pub enable: bool,
    pub interval: u64,
    pub enforce_interval: u64,
    pub dhash_resolution: u32,
    pub dhash_threshold: u32,
}

impl fmt::Display for MonitorConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "interval={}ms, enforce={}ms, resolution={}, threshold={}",
            self.interval, self.enforce_interval, self.dhash_resolution, self.dhash_threshold
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WindowConfig {
    pub enable: bool,
    pub interval: u64,
    pub enforce_interval: u64,
    pub dhash_resolution: u32,
    pub dhash_threshold: u32,
    pub enable_ocr: bool,
}

impl fmt::Display for WindowConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "interval={}ms, enforce={}ms, resolution={}, threshold={}, ocr={}",
            self.interval,
            self.enforce_interval,
            self.dhash_resolution,
            self.dhash_threshold,
            self.enable_ocr
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoggingConfig {
    pub level: String,
}

impl Config {
    /// 从指定路径加载配置
    pub fn load_from<P: AsRef<Path>>(path: P) -> Result<Self> {
        let content = fs::read_to_string(path.as_ref()).context("Failed to read config file")?;
        let config: Config = toml::from_str(&content).context("Failed to parse config file")?;
        config.validate()?;
        Ok(config)
    }

    /// 获取默认配置文件路径
    pub fn default_config_path() -> Result<std::path::PathBuf> {
        let config_dir = dirs::config_dir()
            .context("无法获取配置目录")?
            .join("pasloe-screenshot");
        Ok(config_dir.join("config.toml"))
    }

    pub fn validate(&self) -> Result<()> {
        if self.monitors.is_empty() {
            anyhow::bail!("至少需要配置一个显示器");
        }

        let mut enable_monitor = 0;
        for (name, monitor) in &self.monitors {
            if monitor.interval == 0 {
                anyhow::bail!("显示器 {} 的 interval 必须大于 0", name);
            }
            if monitor.dhash_threshold > 255 {
                anyhow::bail!("显示器 {} 的 dhash_threshold 必须在 0-255 之间", name);
            }
            if monitor.enable {
                enable_monitor += 1;
            }
        }

        if enable_monitor == 0 {
            anyhow::bail!("至少需要启用一个显示器");
        }

        if !self.storage.s3.enable && !self.storage.local.enable {
            anyhow::bail!("至少需要启用一个存储");
        }

        Ok(())
    }
}

impl Default for Config {
    fn default() -> Self {
        let mut monitors = HashMap::new();
        monitors.insert(
            "default".to_string(),
            MonitorConfig {
                enable: true,
                interval: 1000,
                enforce_interval: 30000,
                dhash_resolution: 16,
                dhash_threshold: 10,
            },
        );

        Self {
            pasloe: PasloeConfig {
                url: "http://localhost:8000".to_string(),
                api_key: String::new(),
            },
            storage: StorageConfig {
                s3: S3Config {
                    enable: false,
                    prefix: "screenshots/".to_string(),
                },
                local: LocalConfig {
                    enable: true,
                    path: "/tmp/aw-screenshots".to_string(),
                },
            },
            monitors,
            window: WindowConfig {
                enable: false,
                interval: 1000,
                enforce_interval: 30000,
                dhash_resolution: 16,
                dhash_threshold: 10,
                enable_ocr: false,
            },
            logging: LoggingConfig {
                level: "info".to_string(),
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_load_config() {
        let config = Config::load_from("config/config.example.toml").unwrap();
        assert_eq!(config.pasloe.url, "http://localhost:8000");
    }

    #[test]
    fn test_validate_no_monitors() {
        let mut config = Config::default();
        config.monitors.clear();
        assert!(config.validate().is_err());
    }

    #[test]
    fn test_validate_no_enabled_monitors() {
        let mut config = Config::default();
        for monitor in config.monitors.values_mut() {
            monitor.enable = false;
        }
        assert!(config.validate().is_err());
    }

    #[test]
    fn test_validate_zero_interval() {
        let mut config = Config::default();
        config.monitors.get_mut("default").unwrap().interval = 0;
        assert!(config.validate().is_err());
    }

    #[test]
    fn test_validate_invalid_threshold() {
        let mut config = Config::default();
        config.monitors.get_mut("default").unwrap().dhash_threshold = 256;
        assert!(config.validate().is_err());
    }

    #[test]
    fn test_validate_no_storage() {
        let mut config = Config::default();
        config.storage.s3.enable = false;
        config.storage.local.enable = false;
        assert!(config.validate().is_err());
    }
}
