-- EcoStep QCU (IPT2) PostgreSQL 3NF Schema (Tables 1 to 4)

CREATE TABLE IF NOT EXISTS components (
    component_id SERIAL PRIMARY KEY,
    component_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    specification VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    source_notes VARCHAR(255),
    inspection_status VARCHAR(50) NOT NULL DEFAULT 'Pending',
    sia_synced BOOLEAN NOT NULL DEFAULT FALSE,
    last_updated TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS measurement_runs (
    run_id SERIAL PRIMARY KEY,
    component_id INTEGER NOT NULL REFERENCES components(component_id) ON DELETE RESTRICT,
    run_date TIMESTAMP NOT NULL DEFAULT NOW(),
    operator_name VARCHAR(100),
    steps_count INTEGER NOT NULL DEFAULT 100 CHECK (steps_count > 0),
    energy_mwh NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (energy_mwh >= 0),
    energy_joules NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (energy_joules >= 0),
    joules_per_step NUMERIC(10, 4) NOT NULL DEFAULT 0.0000 CHECK (joules_per_step >= 0),
    adc_peak_volts NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    charging_path VARCHAR(20) NOT NULL DEFAULT 'Path A',
    status VARCHAR(50) NOT NULL DEFAULT 'Pending',
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    sia_run_id VARCHAR(64),
    sia_synced BOOLEAN NOT NULL DEFAULT FALSE,
    sia_synced_at TIMESTAMP,
    sia_deleted_synced BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS telemetry_logs (
    log_id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES measurement_runs(run_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    adc_raw INTEGER NOT NULL CHECK (adc_raw >= 0 AND adc_raw <= 1023),
    adc_voltage NUMERIC(10, 2) NOT NULL,
    baud_rate INTEGER NOT NULL DEFAULT 115200,
    recorded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    sia_synced BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_telemetry_logs_run_id ON telemetry_logs(run_id);

CREATE TABLE IF NOT EXISTS sign_tests (
    test_id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES measurement_runs(run_id) ON DELETE CASCADE,
    test_date TIMESTAMP NOT NULL DEFAULT NOW(),
    sign_mode VARCHAR(50) NOT NULL,
    resistor_value VARCHAR(20) NOT NULL DEFAULT '1.5 kΩ',
    load_ma NUMERIC(10, 2) NOT NULL CHECK (load_ma >= 0),
    power_mw NUMERIC(10, 2) NOT NULL CHECK (power_mw >= 0),
    runtime_minutes NUMERIC(10, 2) NOT NULL CHECK (runtime_minutes >= 0),
    status VARCHAR(50) NOT NULL DEFAULT 'Completed',
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    sia_synced BOOLEAN NOT NULL DEFAULT FALSE,
    last_updated TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sign_tests_run_id ON sign_tests(run_id);
