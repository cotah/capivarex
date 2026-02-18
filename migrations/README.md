# Database Migrations

This folder contains SQL migration scripts for the SuperBot God database schema.

## How to Apply Migrations

### Option 1: Supabase Dashboard (Recommended)

1. Log in to [Supabase Dashboard](https://app.supabase.com/)
2. Select your project
3. Go to **SQL Editor**
4. Copy the contents of the migration file
5. Paste and execute

### Option 2: Supabase CLI

```bash
# Install Supabase CLI
npm install -g supabase

# Login
supabase login

# Link to your project
supabase link --project-ref YOUR_PROJECT_REF

# Apply migration
supabase db push
```

## Migration Files

- `001_create_user_vehicles.sql` - Creates `user_vehicles` table for Smartcar integration

## Migration Order

Migrations should be applied in numerical order (001, 002, 003, etc.)

## Notes

- Always backup your database before applying migrations
- Test migrations in a development environment first
- Row Level Security (RLS) policies are included for multi-tenancy
