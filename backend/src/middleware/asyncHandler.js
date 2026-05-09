/**
 * Wraps an async route handler to catch errors and pass them to standard Express error handling,
 * or immediately send a 500 status with { error: err.message } to maintain existing API contracts.
 */
const asyncHandler = (fn) => (req, res, next) => {
    Promise.resolve(fn(req, res, next)).catch((err) => {
        // Log the error for debugging purposes
        console.error('AsyncHandler Error:', err);
        // Maintain the exact previous response structure
        res.status(500).json({ error: err.message || 'Internal Server Error' });
    });
};

module.exports = asyncHandler;
