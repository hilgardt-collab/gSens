# gSens Rust Port - Comprehensive Implementation Plan

## Executive Summary

This document outlines the plan to port gSens, a ~14,819 line Python/GTK4 system monitoring application, to Rust. The port will maintain feature parity while leveraging Rust's performance, memory safety, and type system benefits.

**Current State:** Python 3 + GTK4 + PyGObject
**Target State:** Rust + gtk4-rs
**Estimated Scope:** ~15,000 lines Python → ~20,000-25,000 lines Rust (expanded due to explicit types and error handling)

---

## 1. Current Architecture Analysis

### 1.1 Core Components (14,819 total LOC)

#### Application Core (3,062 LOC)
- `main.py` (561 LOC) - GTK4 application lifecycle, window management
- `grid_layout_manager.py` (981 LOC) - Drag-and-drop grid layout system
- `panel_base.py` (527 LOC) - Base panel widget implementation
- `config_manager.py` (278 LOC) - INI-based configuration persistence
- `config_dialog.py` (526 LOC) - Configuration UI dialogs
- `panel_builder_dialog.py` (280 LOC) - Panel creation wizard

#### Data Architecture (2,637 LOC)
- `data_source.py` (135 LOC) - Abstract data source base class
- `data_displayer.py` (105 LOC) - Abstract displayer base class
- `data_panel.py` (322 LOC) - Panel widget combining source + displayer
- **Data Sources:** (1,413 LOC)
  - CPU (302 LOC)
  - GPU (188 LOC)
  - Memory (78 LOC)
  - Disk (188 LOC)
  - Network (170 LOC)
  - Sensors (150 LOC)
  - Fans (149 LOC)
  - Clock (230 LOC)
  - Combo sources (402 LOC)
- **GPU Managers:** (520 LOC)
  - NVIDIA (163 LOC)
  - AMD (183 LOC)
  - Intel (158 LOC)

#### Visualization Layer (6,442 LOC)
- **Display Types:**
  - Arc Gauge (450 LOC)
  - Arc Combo (602 LOC)
  - Level Bar (595 LOC)
  - Level Bar Combo (390 LOC)
  - Graph (284 LOC)
  - Bar Chart (339 LOC)
  - Speedometer (307 LOC)
  - Text (320 LOC)
  - Indicator (304 LOC)
  - LCARS (1,291 LOC combined)
  - Analog Clock (764 LOC)
  - CPU Multicore (474 LOC)
  - Dashboard Combo (394 LOC)
  - Table (298 LOC)
  - Static (189 LOC)

#### Utility/UI Layer (2,678 LOC)
- UI helpers (380 + 384 + 48 = 812 LOC)
- Color dialog (380 LOC)
- Style manager (155 LOC)
- Update manager (166 LOC)
- Module registry (90 LOC)
- Utilities (110 LOC)

---

## 2. Rust Ecosystem Mapping

### 2.1 Core Dependencies

| Python Library | Rust Equivalent | Purpose | Maturity |
|---------------|-----------------|---------|----------|
| GTK4 | `gtk4` (0.9+) | GUI framework | ⭐⭐⭐⭐⭐ Stable |
| PyGObject | `gtk4-rs` | GTK bindings | ⭐⭐⭐⭐⭐ Stable |
| Cairo | `cairo-rs` | 2D graphics | ⭐⭐⭐⭐⭐ Stable |
| GdkPixbuf | `gdk-pixbuf` | Image loading | ⭐⭐⭐⭐⭐ Stable |
| psutil | `sysinfo` (0.31+) | System metrics | ⭐⭐⭐⭐⭐ Stable |
| pynvml | `nvml-wrapper` (0.10+) | NVIDIA GPU | ⭐⭐⭐⭐ Stable |
| configparser | `ini` or `toml` | Config files | ⭐⭐⭐⭐⭐ Stable |
| threading | `std::thread` + `tokio` | Concurrency | ⭐⭐⭐⭐⭐ Stable |
| pytz | `chrono-tz` | Timezones | ⭐⭐⭐⭐⭐ Stable |

### 2.2 Additional Rust Crates Needed

```toml
[dependencies]
# GUI Framework
gtk4 = "0.9"
gdk4 = "0.9"
cairo-rs = "0.20"
gdk-pixbuf = "0.20"
pango = "0.20"

# System Monitoring
sysinfo = "0.31"
nvml-wrapper = "0.10"

# Serialization & Config
serde = { version = "1.0", features = ["derive"] }
serde_ini = "0.2"
toml = "0.8"

# Async Runtime
tokio = { version = "1.0", features = ["full"] }
async-channel = "2.0"

# Error Handling
anyhow = "1.0"
thiserror = "1.0"

# Time
chrono = "0.4"
chrono-tz = "0.9"

# Logging
tracing = "0.1"
tracing-subscriber = "0.3"

# Math & Utils
num-traits = "0.2"
```

### 2.3 AMD/Intel GPU Support

**AMD:**
- Use `libdrm` bindings or direct sysfs reads (`/sys/class/drm/card*/`)
- Consider `amdgpu-rs` or custom implementation

**Intel:**
- Intel GPU metrics via sysfs (`/sys/class/drm/card*/gt/`)
- Consider `intel-gpu-tools` bindings or custom implementation

---

## 3. Phased Implementation Plan

### Phase 1: Foundation & Core Architecture (Weeks 1-3)

#### 1.1 Project Setup
- [ ] Initialize Cargo workspace with proper structure
- [ ] Set up CI/CD (GitHub Actions for tests, clippy, fmt)
- [ ] Configure logging with `tracing`
- [ ] Create error types with `thiserror`

**Workspace Structure:**
```
gSens-rust/
├── Cargo.toml (workspace)
├── src/
│   ├── main.rs
│   ├── lib.rs
│   └── modules/
│       ├── core/
│       │   ├── mod.rs
│       │   ├── config.rs
│       │   ├── types.rs
│       │   └── errors.rs
│       ├── data/
│       │   ├── mod.rs
│       │   ├── source.rs
│       │   ├── displayer.rs
│       │   └── panel.rs
│       ├── sources/
│       │   └── ... (data source implementations)
│       ├── displayers/
│       │   └── ... (displayer implementations)
│       ├── ui/
│       │   ├── mod.rs
│       │   ├── window.rs
│       │   ├── grid_layout.rs
│       │   └── dialogs/
│       └── system/
│           ├── gpu/
│           └── sensors/
```

#### 1.2 Type System & Traits
- [ ] Define core traits:
  - `DataSource` trait with async `get_data()` method
  - `DataDisplayer` trait with `draw()` method
  - `Configurable` trait for config models
- [ ] Create type-safe config structures using `serde`
- [ ] Implement error handling strategy

**Example Trait Definitions:**
```rust
#[async_trait]
pub trait DataSource: Send + Sync {
    fn name(&self) -> &str;
    fn description(&self) -> &str;
    async fn get_data(&self) -> Result<DataValue>;
    fn config_model(&self) -> ConfigModel;
}

pub trait DataDisplayer: Send + Sync {
    fn name(&self) -> &str;
    fn draw(&self, ctx: &cairo::Context, value: &DataValue, config: &DisplayerConfig);
    fn config_model(&self) -> ConfigModel;
}
```

#### 1.3 Configuration Management
- [ ] Port `config_manager.py` to Rust
- [ ] Use `serde` + `serde_ini` for INI serialization
- [ ] Implement auto-save with debouncing using `tokio::time`
- [ ] Add file watcher for external config changes

### Phase 2: System Data Collection (Weeks 4-5)

#### 2.1 Basic Data Sources
- [ ] CPU source using `sysinfo`
- [ ] Memory source
- [ ] Disk usage source
- [ ] Network source (requires additional crate like `netstat` or direct `/proc` parsing)

#### 2.2 GPU Management
- [ ] NVIDIA support via `nvml-wrapper`
- [ ] AMD support via sysfs (`/sys/class/drm/`)
- [ ] Intel support via sysfs
- [ ] GPU manager abstraction trait

#### 2.3 Sensor Support
- [ ] Parse `lm-sensors` data from sysfs (`/sys/class/hwmon/`)
- [ ] CPU temperature sensors
- [ ] System temperature sensors
- [ ] Fan speed sensors
- [ ] Create sensor cache similar to Python version

### Phase 3: Basic UI & Layout (Weeks 6-8)

#### 3.1 Application Window
- [ ] Port `main.py` → `main.rs` + `window.rs`
- [ ] GTK4 application lifecycle
- [ ] Header bar with menu
- [ ] Command-line argument parsing (use `clap`)
- [ ] Fullscreen support
- [ ] Monitor selection

#### 3.2 Grid Layout Manager
- [ ] Port `grid_layout_manager.py` → `grid_layout.rs`
- [ ] Drag-and-drop panel support
- [ ] Multi-selection with rubber band
- [ ] Grid snapping
- [ ] Background styling (color, gradient, image)

#### 3.3 Panel System
- [ ] Port `data_panel.py` → `panel.rs`
- [ ] Panel widget with GTK4
- [ ] Right-click context menu
- [ ] Panel selection/highlighting
- [ ] Title rendering

### Phase 4: Basic Displayers (Weeks 9-10)

Implement simplest displayers first to validate architecture:

- [ ] Text displayer
- [ ] Level bar displayer
- [ ] Simple indicator
- [ ] Basic arc gauge

### Phase 5: Advanced Displayers (Weeks 11-14)

- [ ] Complete arc gauge with all features
- [ ] Speedometer
- [ ] Graph (time-series)
- [ ] Bar chart
- [ ] Arc combo
- [ ] Level bar combo
- [ ] CPU multicore
- [ ] Analog clock
- [ ] LCARS combo (most complex)
- [ ] Dashboard combo
- [ ] Table

### Phase 6: Configuration UI (Weeks 15-16)

- [ ] Port `panel_builder_dialog.py`
- [ ] Port `config_dialog.py`
- [ ] Color picker dialog
- [ ] Font selection
- [ ] Gradient editor
- [ ] All property editors

### Phase 7: Advanced Features (Weeks 17-18)

- [ ] Save/load layouts
- [ ] Multiple layout support
- [ ] Window size snapping
- [ ] Fullscreen per-monitor
- [ ] Background mode
- [ ] Update manager with async updates

### Phase 8: Testing & Polish (Weeks 19-20)

- [ ] Unit tests for all data sources
- [ ] Integration tests for UI
- [ ] Memory leak detection
- [ ] Performance profiling
- [ ] Documentation (rustdoc)
- [ ] User guide updates

---

## 4. Key Technical Challenges & Solutions

### 4.1 Async Architecture

**Challenge:** Python uses `threading` + GTK main loop; Rust needs proper async/await integration

**Solution:**
- Use `tokio` runtime for async operations
- Use `async-channel` for communication between async tasks and GTK main thread
- Use `glib::MainContext::spawn_local()` for GTK-safe async tasks
- Keep data collection async, UI updates synchronous

**Pattern:**
```rust
// Data collection in async context
let (tx, rx) = async_channel::unbounded();
tokio::spawn(async move {
    loop {
        let data = collect_metrics().await;
        tx.send(data).await.ok();
        tokio::time::sleep(Duration::from_millis(1000)).await;
    }
});

// UI updates in GTK main thread
glib::spawn_future_local(async move {
    while let Ok(data) = rx.recv().await {
        panel.update(data);
    }
});
```

### 4.2 GTK4 Object Ownership

**Challenge:** GTK uses reference counting; Rust has strict ownership

**Solution:**
- Use `Rc<RefCell<T>>` for shared mutable state
- Use `gtk::glib::WeakRef` for circular references
- Leverage GTK4-rs's built-in smart pointers
- Create builder pattern APIs for complex widgets

### 4.3 Plugin/Module System

**Challenge:** Python uses dynamic imports; Rust needs compile-time types

**Solution:**
- Use trait objects: `Box<dyn DataSource>`
- Create registry macro for compile-time registration
- Use `inventory` crate for distributed registration

**Example:**
```rust
inventory::collect!(SourceFactory);

pub struct SourceFactory {
    pub name: &'static str,
    pub create: fn() -> Box<dyn DataSource>,
}

inventory::submit! {
    SourceFactory {
        name: "cpu",
        create: || Box::new(CpuSource::new()),
    }
}
```

### 4.4 Cairo Drawing Performance

**Challenge:** Python's Cairo binding overhead vs Rust's zero-cost

**Solution:**
- Direct cairo-rs usage eliminates GIL overhead
- Pre-compute drawing paths where possible
- Use caching for expensive calculations
- Leverage Rust's SIMD where applicable

### 4.5 Configuration Schema Evolution

**Challenge:** Python uses loose dict-based configs; Rust needs typed configs

**Solution:**
- Use `serde` with `#[serde(default)]` for backward compatibility
- Implement custom deserializers for migration
- Version config files
- Provide migration path for old configs

```rust
#[derive(Deserialize)]
#[serde(default)]
struct PanelConfig {
    #[serde(default = "default_width")]
    width: i32,
    // ... more fields
}
```

---

## 5. Performance Improvements Expected

### 5.1 Startup Time
- **Python:** ~500-800ms (import overhead, interpreter warmup)
- **Rust:** ~100-200ms (native binary, instant startup)
- **Improvement:** ~4x faster

### 5.2 Memory Usage
- **Python:** ~80-120MB baseline (interpreter + loaded modules)
- **Rust:** ~20-40MB baseline (native binary, no runtime)
- **Improvement:** ~3x reduction

### 5.3 CPU Usage
- **Python:** 2-5% idle with 1s update interval
- **Rust:** 0.5-1% idle (no GIL, optimized polling)
- **Improvement:** ~3-4x reduction

### 5.4 Update Latency
- **Python:** GTK callbacks + GIL can cause jitter
- **Rust:** Lock-free channels + no GIL = consistent timing
- **Improvement:** More predictable, lower jitter

---

## 6. Migration Strategy Options

### Option A: Big Bang Rewrite (Recommended for this project)
- ✅ Clean slate, modern architecture
- ✅ No legacy technical debt
- ✅ Can redesign pain points
- ❌ No incremental testing
- ❌ Longer time to delivery

### Option B: Incremental Port
- ✅ Can test each module
- ✅ Maintains working application
- ❌ Complex FFI boundary
- ❌ Dual maintenance burden
- ❌ Not practical for GTK apps

**Recommendation:** Option A (Big Bang) - The GUI framework boundary makes incremental porting impractical.

---

## 7. Testing Strategy

### 7.1 Unit Tests
```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_cpu_source_returns_valid_data() {
        let source = CpuSource::new();
        let data = source.get_data().await.unwrap();
        assert!(data.as_percentage() >= 0.0);
        assert!(data.as_percentage() <= 100.0);
    }
}
```

### 7.2 Integration Tests
- Test full panel creation workflow
- Test config save/load
- Test layout serialization

### 7.3 Property-Based Testing
Use `proptest` for configuration fuzzing

### 7.4 Manual Testing Checklist
- [ ] All 15+ displayer types render correctly
- [ ] Drag-and-drop works smoothly
- [ ] Config dialogs function properly
- [ ] No memory leaks over 24h run
- [ ] GPU monitoring works (NVIDIA, AMD, Intel)
- [ ] Sensor detection works
- [ ] Fullscreen modes work
- [ ] Layout save/load works

---

## 8. Documentation Plan

### 8.1 Code Documentation
- Rustdoc comments on all public APIs
- Module-level documentation
- Example code snippets

### 8.2 User Documentation
- Update README.md with Rust instructions
- Installation guide (cargo, pre-built binaries)
- Building from source guide
- Architecture documentation

### 8.3 Developer Documentation
- Contributing guide
- Architecture overview
- Adding new data sources guide
- Adding new displayers guide
- Testing guidelines

---

## 9. Release Strategy

### 9.1 Alpha Release (Feature Complete)
- All core features ported
- Basic testing done
- Known bugs documented

### 9.2 Beta Release (Stabilization)
- All critical bugs fixed
- Performance optimization done
- Memory leaks addressed

### 9.3 v1.0 Release (Production Ready)
- All tests passing
- Documentation complete
- Benchmarks show improvements
- User migration guide available

---

## 10. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| gtk4-rs API changes | Low | High | Pin specific versions, track upstream |
| GPU library unavailable | Medium | Medium | Graceful degradation, fallback to sysfs |
| Performance worse than Python | Low | High | Profile early, optimize critical paths |
| UI behavior differences | Medium | Low | Extensive manual testing, screenshots |
| Config migration issues | Medium | Medium | Implement robust migration, version configs |
| Resource exhaustion bugs | Low | High | Leak detection, long-running tests |

---

## 11. Success Metrics

### Functional Parity
- [ ] All 15+ display types working
- [ ] All 10+ data sources working
- [ ] All GPU vendors supported
- [ ] All configuration options available

### Performance
- [ ] Startup time < 200ms
- [ ] Memory usage < 50MB baseline
- [ ] CPU usage < 1% at idle
- [ ] No frame drops during animations

### Code Quality
- [ ] 100% of public APIs documented
- [ ] >80% code coverage in tests
- [ ] 0 clippy warnings on default lints
- [ ] No unsafe code outside GPU interfacing

---

## 12. Next Steps

1. **Immediate Actions:**
   - Set up Cargo workspace
   - Create core trait definitions
   - Implement config management
   - Port simplest data source (CPU)

2. **Week 1 Deliverables:**
   - Compiling skeleton application
   - Basic window with GTK4
   - CPU data source functional
   - Config save/load working

3. **Quick Win Demo:**
   - Simple window with one text panel showing CPU usage
   - Demonstrates full data flow: source → panel → displayer
   - Validates architecture decisions early

---

## Appendix A: Cargo.toml Template

```toml
[workspace]
members = [".", "crates/*"]
resolver = "2"

[package]
name = "gsens"
version = "1.0.0"
edition = "2021"
rust-version = "1.75"
authors = ["gSens Team"]
description = "A highly customizable GTK4 system monitor"
license = "MIT OR Apache-2.0"
repository = "https://github.com/yourusername/gSens"

[dependencies]
# GUI
gtk4 = { version = "0.9", features = ["v4_12"] }
gdk4 = "0.9"
cairo-rs = { version = "0.20", features = ["png"] }
gdk-pixbuf = "0.20"
pango = "0.20"

# System monitoring
sysinfo = "0.31"
nvml-wrapper = { version = "0.10", optional = true }

# Serialization
serde = { version = "1.0", features = ["derive"] }
serde_ini = "0.2"

# Async
tokio = { version = "1.0", features = ["rt-multi-thread", "time", "sync"] }
async-channel = "2.0"
async-trait = "0.1"

# Error handling
anyhow = "1.0"
thiserror = "1.0"

# Time
chrono = "0.4"
chrono-tz = "0.9"

# Utilities
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
clap = { version = "4.0", features = ["derive"] }

[dev-dependencies]
proptest = "1.0"

[features]
default = ["nvidia"]
nvidia = ["nvml-wrapper"]

[profile.release]
opt-level = 3
lto = "thin"
codegen-units = 1
strip = true
```

---

## Appendix B: Project Timeline Visualization

```
Month 1: Foundation
├── Week 1: Project setup, core traits
├── Week 2: Config management, type system
├── Week 3: Basic data sources (CPU, Memory)
└── Week 4: GPU management, sensors

Month 2: UI Foundation
├── Week 5: Sensor support complete
├── Week 6: Application window, header bar
├── Week 7: Grid layout manager
└── Week 8: Panel system, drag-drop

Month 3: Visualization
├── Week 9: Basic displayers (text, bar, indicator)
├── Week 10: Arc gauge, speedometer
├── Week 11: Graph, bar chart, combos
└── Week 12: Advanced displayers (LCARS, clock)

Month 4: Configuration & Polish
├── Week 13: More complex displayers
├── Week 14: Displayer completion
├── Week 15: Config UI dialogs
└── Week 16: Panel builder dialog

Month 5: Advanced Features & Testing
├── Week 17: Layout management, advanced features
├── Week 18: Background mode, optimizations
├── Week 19: Testing, bug fixes
└── Week 20: Documentation, release prep
```

---

## Conclusion

This plan provides a comprehensive roadmap for porting gSens from Python to Rust. The phased approach allows for iterative validation of architecture decisions while building toward feature parity. The expected performance improvements and memory safety guarantees make this a worthwhile investment for the project's long-term maintainability and user experience.

**Estimated Timeline:** 20 weeks (5 months) for feature-complete v1.0
**Effort:** 1-2 full-time developers
**Complexity:** Medium-High (mature GTK4 bindings make this tractable)
