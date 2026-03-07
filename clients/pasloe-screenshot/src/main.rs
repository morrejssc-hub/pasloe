mod capture;
mod cli;
mod config;
mod event;
mod pasloe_client;
mod storage;

use anyhow::Result;

#[tokio::main]
async fn main() -> Result<()> {
    cli::run().await
}
