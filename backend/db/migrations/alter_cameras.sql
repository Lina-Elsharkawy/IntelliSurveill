-- Add live stream URL to cameras table
ALTER TABLE public.cameras
ADD COLUMN IF NOT EXISTS stream_url TEXT;

-- Optional: set default local MediaMTX stream for the first camera
UPDATE public.cameras
SET stream_url = 'http://localhost:8889/rapoo/'
WHERE id = 1
  AND (stream_url IS NULL OR stream_url = '');