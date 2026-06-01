from vad.config import load_vad_config
from vad.db import VadDB
from vad.rtsp_sampler import VadRtspSampler

cfg = load_vad_config()
db = VadDB(cfg.db_dsn)
sampler = VadRtspSampler(cfg, db)
