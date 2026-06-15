/**
 * TypeScript type definitions for all API entities.
 * Based on the OpenAPI specification.
 */

// ========================
// Common Types
// ========================

export interface ApiError {
    error: string;
}

export interface SuccessMessage {
    message: string;
}

export interface HealthResponse {
    status: 'ok' | 'db error';
    error?: string;
}

// ========================
// Camera Types
// ========================

export interface Camera {
    id: number;
    name: string;
    location: string;
    lab_id: number;
}

export interface CameraInput {
    name: string;
    location?: string;
    lab_id?: number;
}

// ========================
// Employee Types
// ========================

export interface Employee {
    id: number;
    name: string;
    department_id: number;
}

export interface EmployeeInput {
    name: string;
    department_id?: number;
}

// ========================
// Visitor Types
// ========================

export interface Visitor {
    id: number;
    name: string;
    visit_date: string;
    purpose: string;
    contact_info: string;
}

export interface VisitorInput {
    name: string;
    visit_date?: string;
    purpose?: string;
    contact_info?: string;
}

// ========================
// Schedule Types
// ========================

export interface Schedule {
    id: number;
    name: string;
    access_start_time: string;
    access_end_time: string;
    applies_to_weekdays: boolean;
    applies_to_weekends: boolean;
    specific_dates: string[];
}

export interface ScheduleInput {
    name: string;
    access_start_time?: string;
    access_end_time?: string;
    applies_to_weekdays?: boolean;
    applies_to_weekends?: boolean;
    specific_dates?: string[];
}

// ========================
// Detected Person Types
// ========================

export interface DetectedPerson {
    id: number;
    name: string;
    additional_info: string;
    employee_id: number | null;
    visitor: boolean;
    visitor_id: number | null;
}

// ========================
// Log Types
// ========================

export interface Log {
    id: number;
    timestamp: string;
    detected_id: number | null;
    camera_id: number | null;
    anomaly_id: number | null;
    authorized: boolean;
    confidence_score: number;
    event_type: string;
    location: string;
    device_status: string;
    image_video_ref: string;
    processing_time: number;
    model_version: string;
}

// ========================
// RAG Types
// ========================

export interface RAGQueryRequest {
    text: string;
}

export interface RAGQueryResponse {
    status: 'success' | 'error';
    data?: unknown;
    message?: string;
}

// ========================
// Anomaly Config Types
// ========================

export interface AnomalyConfig {
    threshold: number;
    windowSeconds: number;
}

export interface AnomalyConfigResponse {
    message: string;
    config: AnomalyConfig & { updatedAt: string };
}

// ========================
// Notification Types
// ========================

export interface Notification {
    id: number;
    title: string;
    message?: string;
    type?: string;          // e.g., 'motion', 'camera_offline', 'low_battery', 'anomaly'
    source?: string;        // e.g., 'camera', 'system', 'anomaly'
    source_id?: number;
    severity?: 'high' | 'medium' | 'low';
    is_read: boolean;
    created_at: string;
}

// ========================
// Cloud Backup Types
// ========================

export interface BackupConfig {
    enabled: boolean;
    interval_hours: number;
    prefixes: string[];
    aws_s3_bucket: string;
    aws_s3_region: string;
}

export interface BackupStatus {
    last_sync_timestamp: string | null;
    last_sync_objects: number;
    last_sync_bytes: number;
    last_sync_duration: number;
    last_sync_failed: number;
    is_running: boolean;
}

export interface BackupTriggerResponse {
    message: string;
    objects_synced: number;
    objects_failed: number;
    bytes_transferred: number;
    duration_seconds: number;
}
