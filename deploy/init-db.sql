-- =============================================
-- Task Manager - Database Initialization
-- =============================================
-- This script runs automatically when the
-- PostgreSQL container is first created.
-- =============================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create notification schema for logical separation
CREATE SCHEMA IF NOT EXISTS notifications;
