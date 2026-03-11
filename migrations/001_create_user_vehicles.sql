-- Migration: Create user_vehicles table for Smartcar integration
-- Description: Stores vehicle connection data and access tokens for each user
-- Author: Manus AI
-- Date: 2026-02-12

-- Create user_vehicles table
CREATE TABLE IF NOT EXISTS user_vehicles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vehicle_id VARCHAR(255) NOT NULL UNIQUE,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    token_type VARCHAR(50) DEFAULT 'Bearer',
    
    -- Vehicle information
    make VARCHAR(100),
    model VARCHAR(100),
    year INTEGER,
    vin VARCHAR(17),
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_synced_at TIMESTAMP WITH TIME ZONE,
    
    -- Ensure one vehicle per user (a user can have multiple vehicles)
    CONSTRAINT unique_user_vehicle UNIQUE (user_id, vehicle_id)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_vehicles_user_id ON user_vehicles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_vehicles_vehicle_id ON user_vehicles(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_user_vehicles_expires_at ON user_vehicles(expires_at);

-- Create updated_at trigger
CREATE OR REPLACE FUNCTION update_user_vehicles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_user_vehicles_updated_at
    BEFORE UPDATE ON user_vehicles
    FOR EACH ROW
    EXECUTE FUNCTION update_user_vehicles_updated_at();

-- Add RLS (Row Level Security) policies
ALTER TABLE user_vehicles ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own vehicles
CREATE POLICY user_vehicles_select_policy ON user_vehicles
    FOR SELECT
    USING (auth.uid() = user_id);

-- Policy: Users can only insert their own vehicles
CREATE POLICY user_vehicles_insert_policy ON user_vehicles
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Policy: Users can only update their own vehicles
CREATE POLICY user_vehicles_update_policy ON user_vehicles
    FOR UPDATE
    USING (auth.uid() = user_id);

-- Policy: Users can only delete their own vehicles
CREATE POLICY user_vehicles_delete_policy ON user_vehicles
    FOR DELETE
    USING (auth.uid() = user_id);

-- Grant permissions to authenticated users
GRANT SELECT, INSERT, UPDATE, DELETE ON user_vehicles TO authenticated;

-- Comments for documentation
COMMENT ON TABLE user_vehicles IS 'Stores Smartcar vehicle connections and access tokens for users';
COMMENT ON COLUMN user_vehicles.user_id IS 'Reference to the user who owns this vehicle connection';
COMMENT ON COLUMN user_vehicles.vehicle_id IS 'Smartcar vehicle ID (unique identifier from Smartcar API)';
COMMENT ON COLUMN user_vehicles.access_token IS 'Smartcar access token for API calls (encrypted in production)';
COMMENT ON COLUMN user_vehicles.refresh_token IS 'Smartcar refresh token for renewing access (encrypted in production)';
COMMENT ON COLUMN user_vehicles.expires_at IS 'Timestamp when the access token expires';
COMMENT ON COLUMN user_vehicles.last_synced_at IS 'Last time vehicle data was synced from Smartcar';
