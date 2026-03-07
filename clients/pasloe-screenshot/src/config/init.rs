use crate::config::LoggingConfig;
use tracing_subscriber::{EnvFilter, fmt};

/// 初始化日志系统
pub fn init(config: &LoggingConfig) {
    // 从配置或环境变量读取日志级别
    let filter =
        EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(&config.level));

    // 配置日志格式
    fmt()
        .with_env_filter(filter)
        .with_target(true)
        .with_thread_names(true)
        .with_file(true)
        .with_line_number(true)
        .init();
}
