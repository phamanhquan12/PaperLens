-- Guest trial sessions for anonymous try-before-signup demos.
CREATE TABLE IF NOT EXISTS guest_sessions (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL UNIQUE,
    queries_used INTEGER NOT NULL DEFAULT 0,
    papers_used INTEGER NOT NULL DEFAULT 0,
    images_used INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_guest_sessions_user_id ON guest_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_guest_sessions_expires_at ON guest_sessions (expires_at);
