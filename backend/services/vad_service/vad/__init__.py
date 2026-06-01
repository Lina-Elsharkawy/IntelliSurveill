"""
Backend-direct VAD package.

First implementation slice:
- Direct RTSP open from backend.
- Stable 5 fps sampling.
- Rolling memory buffer.
- Metadata writes to vad_streams / vad_stream_sessions / vad_sampled_frames.
- Local debug frame saving.
"""
