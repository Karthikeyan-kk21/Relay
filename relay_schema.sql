-- Relay v1 Initial Schema Migration
-- Run this in your Supabase SQL Editor

-- Users table (already exists, extend if needed)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    employee_id VARCHAR(20) UNIQUE NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(20) DEFAULT 'user',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Attendance table
CREATE TABLE IF NOT EXISTS attendance (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    date DATE NOT NULL,
    check_in TIMESTAMP,
    check_out TIMESTAMP,
    status VARCHAR(20) DEFAULT 'Absent',
    ip_address VARCHAR(50),
    CONSTRAINT uq_attendance_user_date UNIQUE (user_id, date)
);

-- Worksheets table
CREATE TABLE IF NOT EXISTS worksheets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    date DATE NOT NULL,
    content TEXT,
    is_locked BOOLEAN DEFAULT FALSE,
    admin_unlocked BOOLEAN DEFAULT FALSE,
    submitted_at TIMESTAMP,
    updated_at TIMESTAMP,
    CONSTRAINT uq_worksheet_user_date UNIQUE (user_id, date)
);

-- Settings table
CREATE TABLE IF NOT EXISTS settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(60) UNIQUE NOT NULL,
    value VARCHAR(300) NOT NULL DEFAULT '',
    description VARCHAR(200)
);

-- Default settings
INSERT INTO settings (key, value, description) VALUES
    ('office_ip', '', 'Office IP address for attendance validation (leave empty to disable)'),
    ('checkin_time', '09:30', 'On-time check-in deadline (HH:MM, 24h format)'),
    ('late_threshold', '09:35', 'Late check-in threshold -- after this time, marked Late (HH:MM)'),
    ('halfday_checkout', '13:30', 'If checked out before this time, marked as Half Day (HH:MM)'),
    ('worksheet_lock_time', '18:30', 'Worksheet locks at this time every day (HH:MM)')
ON CONFLICT (key) DO NOTHING;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_attendance_user_date ON attendance(user_id, date);
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);
CREATE INDEX IF NOT EXISTS idx_worksheets_user_date ON worksheets(user_id, date);
CREATE INDEX IF NOT EXISTS idx_worksheets_date ON worksheets(date);
