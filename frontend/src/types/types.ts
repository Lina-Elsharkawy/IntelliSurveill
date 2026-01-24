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
// Anomaly Types
// ========================

export interface Anomaly {
    id: number;
    description: string;
    severity_level: string;
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
// Department Types
// ========================

export interface Department {
    id: number;
    name: string;
}

export interface DepartmentInput {
    name: string;
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
// Lab Types
// ========================

export interface Lab {
    id: number;
    name: string;
}

export interface LabInput {
    name: string;
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
// Candidates Types
// ========================

export type AnomalyCandidate = {
    id: number;
    scene_window_embedding_id: number;
    reason?: string;
    status?: string;
    image_ref?: string;
    video_ref?: string;
    created_at?: string;
    updated_at?: string;
    jobs?: OllamaJob[];      // optional array of jobs
    feedback?: Feedback[];   // optional array of feedback
};

export type AnomalyCandidateInput = {
    scene_window_embedding_id: number;
    reason?: string;
    status?: string;
    image_ref?: string;
    video_ref?: string;
};

/* ----------------- Feedback ----------------- */
export type Feedback = {
    id: number;
    anomaly_candidate_id: number;
    label?: string;
    reviewer?: string;
    notes?: string;
    system_decision?: any;
    created_at?: string;
    used_for_retrain?: boolean;
};

export type FeedbackInput = {
    anomaly_candidate_id: number;
    label?: string;
    reviewer?: string;
    notes?: string;
    system_decision?: any;
};

/* ----------------- Jobs ----------------- */
export type OllamaJob = {
    id: number;
    anomaly_candidate_id: number;
    model_name?: string;
    prompt?: string;
    request_json?: any;
    status?: string;
    response_text?: string;
    response_json?: any;
    error?: string;
    created_at?: string;
    started_at?: string;
    finished_at?: string;
};

export type OllamaJobInput = {
    anomaly_candidate_id: number;
    model_name?: string;
    prompt?: string;
    request_json?: any;
};


