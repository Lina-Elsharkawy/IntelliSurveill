/**
 * Cloud Backup API service.
 * Communicates with the s3-backup service via the backend proxy.
 */

import { apiGet, apiPost, apiPut } from '@/lib/api';
import type { BackupConfig, BackupStatus, BackupTriggerResponse } from '@/types/types';

/**
 * Get current backup configuration.
 */
export async function getBackupConfig(): Promise<BackupConfig> {
    return apiGet<BackupConfig>('/backup/config');
}

/**
 * Update backup configuration (schedule, prefixes, enabled/disabled).
 */
export async function updateBackupConfig(config: Partial<BackupConfig>): Promise<BackupConfig> {
    return apiPut<BackupConfig, Partial<BackupConfig>>('/backup/config', config);
}

/**
 * Get last backup sync status.
 */
export async function getBackupStatus(): Promise<BackupStatus> {
    return apiGet<BackupStatus>('/backup/status');
}

/**
 * Trigger an immediate backup.
 */
export async function triggerBackup(): Promise<BackupTriggerResponse> {
    return apiPost<BackupTriggerResponse, {}>('/backup/trigger', {});
}