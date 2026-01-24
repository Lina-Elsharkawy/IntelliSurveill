/**
 * Notifications API service.
 */

import { apiGet, apiPut, apiPost, apiDelete } from '@/lib/api';
import type { Notification, SuccessMessage } from '@/types/types';

/**
 * Get recent notifications (limit 10, unread first).
 */
export async function getRecentNotifications(): Promise<Notification[]> {
    return apiGet<Notification[]>('/api/notifications/recent');
}

/**
 * Get unread notification count.
 */
export async function getUnreadCount(): Promise<{ count: number }> {
    return apiGet<{ count: number }>('/api/notifications/unread-count');
}

/**
 * Mark a notification as read.
 */
export async function markAsRead(id: number): Promise<SuccessMessage> {
    return apiPut<SuccessMessage, object>(`/api/notifications/${id}/read`, {});
}

/**
 * Mark all notifications as read.
 */
export async function markAllAsRead(): Promise<SuccessMessage> {
    return apiPut<SuccessMessage, object>('/api/notifications/mark-all-read', {});
}

/**
 * Create a notification.
 */
export async function createNotification(notification: Omit<Notification, 'id' | 'is_read' | 'created_at'>): Promise<Notification> {
    return apiPost<Notification, typeof notification>('/api/notifications', notification);
}

/**
 * Delete a notification.
 */
export async function deleteNotification(id: number): Promise<SuccessMessage> {
    return apiDelete<SuccessMessage>(`/api/notifications/${id}`);
}
