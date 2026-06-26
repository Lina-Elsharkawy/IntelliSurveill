# Live RTSP Multi-Gate Test Scripts

## Files

- `live_gate_common.py`
- `04_live_tubelet_smoke_rtsp.py`
- `04_live_multigate_rtsp_test.py`

## Do not hardcode RTSP credentials

Pass the URL at runtime using `--rtsp_url`.

## Test order

### 1. Smoke test: tracking + tubelets only

```powershell
python .\04_live_tubelet_smoke_rtsp.py --rtsp_url "<RTSP_URL>" --output_dir "D:\Embeddings_Distribution\live_tests\smoke" --device cuda --save_montages --max_runtime_sec 120
```

You should see:

```text
[TUBELET] #1 track=...
```

### 2. Pose gate only

```powershell
python .\04_live_multigate_rtsp_test.py --rtsp_url "<RTSP_URL>" --output_dir "D:\Embeddings_Distribution\live_tests\pose_only" --enable_pose --device cuda --save_evidence --print_every_tubelet
```

### 3. RAFT gate only

```powershell
python .\04_live_multigate_rtsp_test.py --rtsp_url "<RTSP_URL>" --output_dir "D:\Embeddings_Distribution\live_tests\raft_only" --enable_raft --device cuda --save_evidence --print_every_tubelet
```

### 4. Pose + RAFT together

```powershell
python .\04_live_multigate_rtsp_test.py --rtsp_url "<RTSP_URL>" --output_dir "D:\Embeddings_Distribution\live_tests\pose_raft" --enable_pose --enable_raft --device cuda --save_evidence --print_every_tubelet
```

## Gates

### Pose gate
- `yolov8s-pose.pt`
- threshold `71.38647402255272`
- RobustScaler + GMM-5
- reason: `rare_pose_articulation`

### RAFT gate
- torchvision RAFT-large, FP32
- threshold `41.214315962694954`
- RobustScaler + GMM-5
- reason: `rare_motion_raft_velocity`

### Deep gate
Optional scaffold. Requires:
- `--enable_deep`
- `--deep_memory_npy <path>`

Reason:
- `rare_deep_embedding`

## Outputs
- `tubelets.jsonl`
- `tubelets.csv`
- `events.jsonl`
- `live_summary.json`
- evidence images if `--save_evidence`

## Important RAFT note

The live RAFT histogram is implemented directly in the live script. If your offline `04b_extract_raft_velocity_features_from_motion_tubelets_v1_1.py` used a different exact `sum_area` formula, replace the live `raft_feature()` / `raft_pair_hist()` helper with the exact offline implementation before final production.
