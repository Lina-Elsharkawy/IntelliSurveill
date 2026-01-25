const express = require('express');
const router = express.Router();
const notificationsController = require('../controllers/notificationsController');

// GET /api/notifications/recent - Get recent notifications
router.get('/recent', notificationsController.getRecentNotifications);

// GET /api/notifications/unread-count - Get unread notification count
router.get('/unread-count', notificationsController.getUnreadCount);

// PUT /api/notifications/:id/read - Mark a notification as read
router.put('/:id/read', notificationsController.markAsRead);

// PUT /api/notifications/mark-all-read - Mark all notifications as read
router.put('/mark-all-read', notificationsController.markAllAsRead);

// POST /api/notifications - Create a notification
router.post('/', notificationsController.createNotification);

// DELETE /api/notifications/:id - Delete a notification
router.delete('/:id', notificationsController.deleteNotification);

module.exports = router;
