const Notification = require('../models/notification');

// Get recent notifications (limit 10, unread first, then by date)
exports.getRecentNotifications = async (req, res) => {
    try {
        const notifications = await Notification.findAll({
            order: [
                ['is_read', 'ASC'],
                ['created_at', 'DESC']
            ],
            limit: 10
        });
        res.status(200).json(notifications);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get unread notification count
exports.getUnreadCount = async (req, res) => {
    try {
        const count = await Notification.count({
            where: { is_read: false }
        });
        res.status(200).json({ count });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Mark a notification as read
exports.markAsRead = async (req, res) => {
    try {
        const { id } = req.params;
        const notification = await Notification.findByPk(id);
        if (!notification) {
            return res.status(404).json({ error: 'Notification not found' });
        }
        await notification.update({ is_read: true });
        res.status(200).json({ message: 'Notification marked as read' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Mark all notifications as read
exports.markAllAsRead = async (req, res) => {
    try {
        await Notification.update(
            { is_read: true },
            { where: { is_read: false } }
        );
        res.status(200).json({ message: 'All notifications marked as read' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Create a notification (for future use by other services)
exports.createNotification = async (req, res) => {
    try {
        const { title, message, type, source, source_id, severity } = req.body;
        if (!title) {
            return res.status(400).json({ error: 'Title is required' });
        }
        const notification = await Notification.create({
            title,
            message,
            type,
            source,
            source_id,
            severity: severity || 'low'
        });
        res.status(201).json(notification);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Delete a notification
exports.deleteNotification = async (req, res) => {
    try {
        const { id } = req.params;
        const notification = await Notification.findByPk(id);
        if (!notification) {
            return res.status(404).json({ error: 'Notification not found' });
        }
        await notification.destroy();
        res.status(200).json({ message: 'Notification deleted successfully' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};
