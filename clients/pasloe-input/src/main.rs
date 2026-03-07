use rdev::{listen, Event, EventType};
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicUsize, Ordering};
use std::thread;
use std::time::Duration;

static KEYBOARD_EVENTS: AtomicUsize = AtomicUsize::new(0);
static MOUSE_CLICKS: AtomicUsize = AtomicUsize::new(0);
static MOUSE_DISTANCE: AtomicUsize = AtomicUsize::new(0);
static LAST_X: AtomicI64 = AtomicI64::new(0);
static LAST_Y: AtomicI64 = AtomicI64::new(0);
static HAS_LAST_POS: AtomicBool = AtomicBool::new(false);

fn main() {
    // Spawn a thread to print and reset stats every second
    thread::spawn(|| {
        loop {
            thread::sleep(Duration::from_secs(1));
            
            let keyboards = KEYBOARD_EVENTS.swap(0, Ordering::Relaxed);
            let clicks = MOUSE_CLICKS.swap(0, Ordering::Relaxed);
            let distance = MOUSE_DISTANCE.swap(0, Ordering::Relaxed);
            
            // Output format: keyboard_events, mouse_clicks, mouse_distance
            // Output format is CSV-like to be easily readable by other processes
            println!("{},{},{}", keyboards, clicks, distance);
        }
    });

    if let Err(error) = listen(callback) {
        eprintln!("Error: {:?}", error);
    }
}

fn callback(event: Event) {
    match event.event_type {
        EventType::KeyPress(_) => {
            KEYBOARD_EVENTS.fetch_add(1, Ordering::Relaxed);
        }
        EventType::ButtonPress(_) => {
            MOUSE_CLICKS.fetch_add(1, Ordering::Relaxed);
        }
        EventType::MouseMove { x, y } => {
            let current_x = x.round() as i64;
            let current_y = y.round() as i64;
            
            if !HAS_LAST_POS.load(Ordering::Relaxed) {
                LAST_X.store(current_x, Ordering::Relaxed);
                LAST_Y.store(current_y, Ordering::Relaxed);
                HAS_LAST_POS.store(true, Ordering::Relaxed);
            } else {
                let last_x = LAST_X.load(Ordering::Relaxed);
                let last_y = LAST_Y.load(Ordering::Relaxed);
                
                let dx = (current_x - last_x) as f64;
                let dy = (current_y - last_y) as f64;
                let dist = (dx * dx + dy * dy).sqrt().round() as usize;
                
                MOUSE_DISTANCE.fetch_add(dist, Ordering::Relaxed);
                LAST_X.store(current_x, Ordering::Relaxed);
                LAST_Y.store(current_y, Ordering::Relaxed);
            }
        }
        _ => {}
    }
}
