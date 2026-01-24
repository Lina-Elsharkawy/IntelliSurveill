/**
 * Candidates, Feedback, and Jobs API service.
 */

import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api';
import type {
    AnomalyCandidate,
    AnomalyCandidateInput,
    Feedback,
    FeedbackInput,
    OllamaJob,
    OllamaJobInput,
    SuccessMessage
} from '@/types/types';

/* ----------------- Candidates ----------------- */

/**
 * Get all anomaly candidates.
 */
export async function getAllCandidates(): Promise<AnomalyCandidate[]> {
    return apiGet<AnomalyCandidate[]>('/api/candidates');
}

/**
 * Get a single candidate by ID (includes jobs + feedback).
 */
export async function getCandidateById(id: number): Promise<AnomalyCandidate> {
    return apiGet<AnomalyCandidate>(`/api/candidates/${id}`);
}

/**
 * Create a new anomaly candidate.
 */
export async function createCandidate(data: AnomalyCandidateInput): Promise<AnomalyCandidate> {
    return apiPost<AnomalyCandidate, AnomalyCandidateInput>('/api/candidates', data);
}

/**
 * Update an existing candidate.
 */
export async function updateCandidate(id: number, data: AnomalyCandidateInput): Promise<AnomalyCandidate> {
    return apiPut<AnomalyCandidate, AnomalyCandidateInput>(`/api/candidates/${id}`, data);
}

/**
 * Delete a candidate by ID.
 */
export async function deleteCandidate(id: number): Promise<SuccessMessage> {
    return apiDelete<SuccessMessage>(`/api/candidates/${id}`);
}

/* ----------------- Feedback ----------------- */

/**
 * Get all feedback.
 */
export async function getAllFeedback(): Promise<Feedback[]> {
    return apiGet<Feedback[]>('/api/feedback');
}

/**
 * Get feedback for a specific candidate.
 */
export async function getFeedbackByCandidate(candidateId: number): Promise<Feedback[]> {
    return apiGet<Feedback[]>(`/api/feedback/candidate/${candidateId}`);
}

/**
 * Create new feedback.
 */
export async function createFeedback(data: FeedbackInput): Promise<Feedback> {
    return apiPost<Feedback, FeedbackInput>('/api/feedback', data);
}

// Removed markFeedbackUsed function since apiPatch is not used

/* ----------------- Jobs ----------------- */

/**
 * Get all jobs.
 */
export async function getAllJobs(): Promise<OllamaJob[]> {
    return apiGet<OllamaJob[]>('/api/jobs');
}

/**
 * Get jobs for a specific candidate.
 */
export async function getJobsByCandidate(candidateId: number): Promise<OllamaJob[]> {
    return apiGet<OllamaJob[]>(`/api/jobs/candidate/${candidateId}`);
}

/**
 * Create a new job.
 */
export async function createJob(data: OllamaJobInput): Promise<OllamaJob> {
    return apiPost<OllamaJob, OllamaJobInput>('/api/jobs', data);
}

/**
 * Update an existing job.
 */
export async function updateJob(id: number, data: OllamaJobInput): Promise<OllamaJob> {
    return apiPut<OllamaJob, OllamaJobInput>(`/api/jobs/${id}`, data);
}
