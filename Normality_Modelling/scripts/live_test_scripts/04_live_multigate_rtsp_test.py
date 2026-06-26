#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""

Live RTSP independent-gate tester
Implemented:
- Pose gate: YOLOv8s-pose + pose RobustScaler/GMM
- RAFT gate: torchvision RAFT-large + velocity RobustScaler/GMM
- Deep gate: supports saved kNN joblib artifacts via --deep_gate_dir; also keeps old --deep_memory_npy fallback

No raw score fusion. Final anomaly = any gate persistent hit.
"""
import argparse,json,math,time
from collections import defaultdict
from pathlib import Path
import cv2, joblib, numpy as np
from ultralytics import YOLO
from live_gate_common import (CsvAppender,OnlineGateState,TrackTubeletBuffer,TubeletSample,ensure_dir,write_jsonl,draw_box,
                              make_montage,make_pose_feature_from_tubelet,union_box,crop_frame,pad_box_xyxy)

POSE_FEATURE_NAMES = [
    "pose_valid_frame_ratio",
    "pose_mean_keypoint_conf",
    "pose_valid_keypoint_ratio_mean",
    "pose_wrist_speed_mean",
    "pose_wrist_speed_p95",
    "pose_wrist_speed_max",
    "pose_ankle_speed_mean",
    "pose_ankle_speed_p95",
    "pose_ankle_speed_max",
    "pose_limb_speed_mean",
    "pose_limb_speed_p95",
    "pose_limb_speed_max",
    "pose_limb_accel_mean",
    "pose_limb_accel_p95",
    "pose_limb_accel_max",
    "pose_torso_center_speed_mean",
    "pose_torso_center_speed_p95",
    "pose_torso_center_speed_max",
    "pose_body_angle_change_mean",
    "pose_body_angle_change_p95",
    "pose_body_angle_change_max",
    "pose_crouch_change_mean",
    "pose_crouch_change_p95",
    "pose_crouch_change_max",
    "pose_arm_extension_change_mean",
    "pose_arm_extension_change_p95",
    "pose_arm_extension_change_max",
    "pose_asymmetry_motion_mean",
    "pose_asymmetry_motion_p95",
    "pose_asymmetry_motion_max",
]

def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return ""


def xyxy_clip(box,w,h):
    x1,y1,x2,y2=[float(v) for v in box]
    x1=max(0.0,min(float(w-1),x1)); y1=max(0.0,min(float(h-1),y1))
    x2=max(0.0,min(float(w),x2)); y2=max(0.0,min(float(h),y2))
    if x2<x1: x1,x2=x2,x1
    if y2<y1: y1,y2=y2,y1
    return x1,y1,x2,y2

def union_crop_box(box0,box1,w,h,pad_ratio,min_crop_size):
    b0=xyxy_clip(box0,w,h); b1=xyxy_clip(box1,w,h)
    x1=min(b0[0],b1[0]); y1=min(b0[1],b1[1]); x2=max(b0[2],b1[2]); y2=max(b0[3],b1[3])
    bw=max(1.0,x2-x1); bh=max(1.0,y2-y1); pad=float(pad_ratio)*max(bw,bh)
    x1-=pad; y1-=pad; x2+=pad; y2+=pad
    cx=(x1+x2)/2.0; cy=(y1+y2)/2.0
    target_w=max(float(min_crop_size),x2-x1); target_h=max(float(min_crop_size),y2-y1)
    x1=cx-target_w/2.0; x2=cx+target_w/2.0; y1=cy-target_h/2.0; y2=cy+target_h/2.0
    return int(max(0,math.floor(x1))),int(max(0,math.floor(y1))),int(min(w,math.ceil(x2))),int(min(h,math.ceil(y2)))

def pad_to_multiple(t,multiple=8):
    import torch.nn.functional as F
    _,_,h,w=t.shape
    pad_h=(multiple-h%multiple)%multiple; pad_w=(multiple-w%multiple)%multiple
    if pad_h or pad_w: t=F.pad(t,(0,pad_w,0,pad_h),mode="replicate")
    return t,(pad_h,pad_w)

def bgr_to_raft_tensor(img_bgr,device,half=False):
    import torch
    img_rgb=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2RGB)
    t=torch.from_numpy(img_rgb).permute(2,0,1).unsqueeze(0).to(device=device)
    t=t.float()/255.0
    # Match offline 04b extractor: torchvision RAFT input normalized to [-1, 1].
    t=(t-0.5)/0.5
    if half: t=t.half()
    return t

def load_raft(device="cuda",raft_model="large"):
    from torchvision.models.optical_flow import raft_large,raft_small,Raft_Large_Weights,Raft_Small_Weights
    if raft_model=="large":
        model=raft_large(weights=Raft_Large_Weights.DEFAULT,progress=True)
    else:
        model=raft_small(weights=Raft_Small_Weights.DEFAULT,progress=True)
    # IMPORTANT: keep FP32. Offline RAFT-large calibration was FP32, not --half.
    return model.to(device).eval(),None

def flow_histogram_8d(flow_xy,min_mag,num_bins=8,aggregation="sum_area"):
    if flow_xy.size==0:
        return np.zeros(num_bins,dtype=np.float32),{"valid_pixels":0,"mean_mag":0.0,"max_mag":0.0}
    u=flow_xy[...,0]; v=flow_xy[...,1]
    mag=np.sqrt(u*u+v*v)
    mask=np.isfinite(mag)&(mag>=float(min_mag))
    valid=int(mask.sum())
    if valid==0:
        return np.zeros(num_bins,dtype=np.float32),{"valid_pixels":0,"mean_mag":0.0,"max_mag":float(np.nanmax(mag)) if mag.size else 0.0}
    angles=np.arctan2(v[mask],u[mask])
    mags=mag[mask]
    bin_idx=np.floor((angles+math.pi)/(2*math.pi)*num_bins).astype(np.int64)
    bin_idx=np.clip(bin_idx,0,num_bins-1)
    region_area=max(1,int(flow_xy.shape[0])*int(flow_xy.shape[1])); valid_area=max(1,valid)
    hist=np.zeros(num_bins,dtype=np.float32)
    aggregation=str(aggregation).lower().strip()
    for b in range(num_bins):
        vals=mags[bin_idx==b]
        if vals.size:
            if aggregation=="mean": hist[b]=float(vals.mean())
            elif aggregation=="sum_area": hist[b]=float(vals.sum())/float(region_area)
            elif aggregation=="sum_valid": hist[b]=float(vals.sum())/float(valid_area)
            else: raise ValueError(f"Unknown histogram aggregation: {aggregation}")
    stats={"valid_pixels":valid,"region_area_pixels":int(region_area),"valid_pixel_ratio":float(valid)/float(region_area),"hist_aggregation":aggregation,"mean_mag":float(mags.mean()) if mags.size else 0.0,"max_mag":float(mags.max()) if mags.size else 0.0,"sum_mag_per_area":float(mags.sum())/float(region_area) if mags.size else 0.0}
    return hist,stats

def compute_pair_feature(model,frame0_bgr,frame1_bgr,box0_xyxy,box1_xyxy,dt_sec,device,flow_scope="crop",crop_pad_ratio=.20,min_crop_size=192,min_flow_magnitude=.2,hist_aggregation="sum_area",use_dt_normalization=True,max_full_side=960):
    import torch
    h,w=frame0_bgr.shape[:2]
    if frame1_bgr.shape[:2]!=(h,w):
        raise RuntimeError("Frame size changed inside tubelet; cannot compute stable RAFT flow.")
    b0=xyxy_clip(box0_xyxy,w,h); b1=xyxy_clip(box1_xyxy,w,h)
    scale=1.0
    if flow_scope=="crop":
        cx1,cy1,cx2,cy2=union_crop_box(b0,b1,w,h,crop_pad_ratio,min_crop_size)
        if cx2-cx1<8 or cy2-cy1<8: raise RuntimeError(f"Crop too small: {(cx1,cy1,cx2,cy2)}")
        img0=frame0_bgr[cy1:cy2,cx1:cx2]; img1=frame1_bgr[cy1:cy2,cx1:cx2]
        crop_origin=(cx1,cy1); crop_h,crop_w=img0.shape[:2]
        # Match offline 04b: summarize only the person bbox region inside the union crop, not the full crop.
        region_x1=int(max(0,math.floor(b0[0]-cx1))); region_y1=int(max(0,math.floor(b0[1]-cy1)))
        region_x2=int(min(crop_w,math.ceil(b0[2]-cx1))); region_y2=int(min(crop_h,math.ceil(b0[3]-cy1)))
    else:
        img0=frame0_bgr; img1=frame1_bgr; crop_origin=(0,0); crop_h,crop_w=h,w
        region_x1=int(max(0,math.floor(b0[0]))); region_y1=int(max(0,math.floor(b0[1])))
        region_x2=int(min(w,math.ceil(b0[2]))); region_y2=int(min(h,math.ceil(b0[3])))
        if max_full_side and max(crop_h,crop_w)>max_full_side:
            scale=float(max_full_side)/float(max(crop_h,crop_w))
            new_w=max(8,int(round(crop_w*scale))); new_h=max(8,int(round(crop_h*scale)))
            img0=cv2.resize(img0,(new_w,new_h),interpolation=cv2.INTER_LINEAR); img1=cv2.resize(img1,(new_w,new_h),interpolation=cv2.INTER_LINEAR)
            region_x1=int(round(region_x1*scale)); region_x2=int(round(region_x2*scale)); region_y1=int(round(region_y1*scale)); region_y2=int(round(region_y2*scale))
            crop_h,crop_w=new_h,new_w
    if region_x2<=region_x1 or region_y2<=region_y1:
        raise RuntimeError("Invalid person region inside flow crop.")
    t0=bgr_to_raft_tensor(img0,device=device,half=False); t1=bgr_to_raft_tensor(img1,device=device,half=False)
    t0,(pad_h,pad_w)=pad_to_multiple(t0,8); t1,_=pad_to_multiple(t1,8)
    with torch.inference_mode():
        flow=model(t0,t1)[-1][0,:,:crop_h,:crop_w].detach().float().cpu().numpy()
    flow=np.transpose(flow,(1,2,0))
    if flow_scope=="full" and max_full_side and scale!=1.0:
        flow[...,0]/=scale; flow[...,1]/=scale
    if use_dt_normalization:
        flow=flow/max(float(dt_sec),1e-6)
    region_flow=flow[region_y1:region_y2,region_x1:region_x2,:]
    hist,stats=flow_histogram_8d(region_flow,min_mag=min_flow_magnitude,num_bins=8,aggregation=hist_aggregation)
    meta={"flow_scope":flow_scope,"crop_origin_x":int(crop_origin[0]),"crop_origin_y":int(crop_origin[1]),"crop_w":int(crop_w),"crop_h":int(crop_h),"region_w":int(region_x2-region_x1),"region_h":int(region_y2-region_y1),"pad_w":int(pad_w),"pad_h":int(pad_h),"dt_sec":float(dt_sec),**stats}
    return hist.astype(np.float32),meta

def raft_feature(model,transforms,tub,device="cuda",pad=.20,min_crop=192,min_mag=.2,max_side=960,flow_scope="crop",hist_aggregation="sum_area",use_dt_normalization=True,return_meta=False):
    del transforms
    frames=[s.frame for s in tub]; boxes=[s.bbox_xyxy for s in tub]; times=[float(s.t_wall) for s in tub]
    hs=[]; pair_meta=[]
    for i in range(len(frames)-1):
        dt=max(times[i+1]-times[i],1e-6)
        hist,meta=compute_pair_feature(model,frames[i],frames[i+1],boxes[i],boxes[i+1],dt,device,flow_scope,crop_pad_ratio=pad,min_crop_size=min_crop,min_flow_magnitude=min_mag,hist_aggregation=hist_aggregation,use_dt_normalization=use_dt_normalization,max_full_side=max_side)
        hs.append(hist); pair_meta.append(meta)
    if not hs:
        X=np.zeros((1,8),dtype=np.float32)
    else:
        X=np.mean(np.stack(hs,axis=0),axis=0).astype(np.float32).reshape(1,-1)
    if return_meta:
        meta={"raft_valid_pairs":len(hs),"raft_use_dt_normalization":bool(use_dt_normalization),"raft_hist_aggregation":hist_aggregation,"raft_flow_scope":flow_scope}
        if pair_meta:
            meta.update({"raft_mean_pair_valid_pixels":float(np.mean([m.get("valid_pixels",0) for m in pair_meta])),"raft_mean_pair_flow_mag":float(np.mean([m.get("mean_mag",0.0) for m in pair_meta])),"raft_max_pair_flow_mag":float(np.max([m.get("max_mag",0.0) for m in pair_meta])),"raft_mean_region_area_pixels":float(np.mean([m.get("region_area_pixels",0) for m in pair_meta]))})
        return X,meta
    return X

class DeepGate:
    def __init__(self,memory_npy,device="cuda"):
        import torch
        from transformers import AutoImageProcessor, VideoMAEModel
        self.torch=torch; self.device=device
        self.processor=AutoImageProcessor.from_pretrained("MCG-NJU/videomae-base")
        self.model=VideoMAEModel.from_pretrained("MCG-NJU/videomae-base").to(device).eval()
        mem=np.load(memory_npy).astype(np.float32); self.mem=mem/np.maximum(1e-12,np.linalg.norm(mem,axis=1,keepdims=True))
    def score(self,tub):
        crops=[]
        for s in tub:
            h,w=s.frame.shape[:2]; cb=pad_box_xyxy(s.bbox_xyxy,w,h,.20,224); cr=crop_frame(s.frame,cb)
            if cr is None: cr=s.frame
            crops.append(cv2.cvtColor(cr,cv2.COLOR_BGR2RGB))
        inp=self.processor(crops,return_tensors="pt"); inp={k:v.to(self.device) for k,v in inp.items()}
        with self.torch.no_grad(): emb=self.model(**inp).last_hidden_state.mean(dim=1)[0].detach().float().cpu().numpy().astype(np.float32)
        emb=emb/max(1e-12,float(np.linalg.norm(emb)))
        return float(np.min(np.linalg.norm(self.mem-emb.reshape(1,-1),axis=1)))

class DeepGateJoblib:
    """
    Deep VideoMAE+kNN gate using the saved artifact folder produced by
    03b_build_deep_branch_distribution_v2_gaussian.py.

    Expected files:
      <deep_gate_dir>/models/03_knn_index.joblib
      <deep_gate_dir>/04_thresholds.json
    """
    def __init__(self,deep_gate_dir,device="cuda",k=1,threshold_key="p99_5"):
        import torch
        from transformers import AutoImageProcessor, VideoMAEModel
        self.torch=torch; self.device=device; self.k=int(k); self.threshold_key=str(threshold_key)
        deep_gate_dir=Path(deep_gate_dir)
        self.deep_gate_dir=deep_gate_dir
        self.knn=joblib.load(deep_gate_dir/"models"/"03_knn_index.joblib")
        th_path=deep_gate_dir/"04_thresholds.json"
        thresholds=json.loads(th_path.read_text(encoding="utf-8"))
        self.threshold=float(thresholds[f"k{self.k}"][self.threshold_key])
        self.processor=AutoImageProcessor.from_pretrained("MCG-NJU/videomae-base")
        self.model=VideoMAEModel.from_pretrained("MCG-NJU/videomae-base").to(device).eval()
        print(f"[DEEP] loaded source={deep_gate_dir/'models'/'03_knn_index.joblib'} | k={self.k} | threshold={self.threshold:.6f}")
    def score(self,tub):
        crops=[]
        for s in tub:
            h,w=s.frame.shape[:2]; cb=pad_box_xyxy(s.bbox_xyxy,w,h,.20,224); cr=crop_frame(s.frame,cb)
            if cr is None: cr=s.frame
            crops.append(cv2.cvtColor(cr,cv2.COLOR_BGR2RGB))
        inp=self.processor(crops,return_tensors="pt"); inp={k:v.to(self.device) for k,v in inp.items()}
        with self.torch.no_grad(): emb=self.model(**inp).last_hidden_state.mean(dim=1)[0].detach().float().cpu().numpy().astype(np.float32)
        emb=emb/max(1e-12,float(np.linalg.norm(emb)))
        distances,_=self.knn.kneighbors(emb.reshape(1,-1),n_neighbors=self.k,return_distance=True)
        return float(distances[0,:self.k].mean())

def parse_args():
    ap=argparse.ArgumentParser()
    ap.add_argument("--rtsp_url",required=True); ap.add_argument("--output_dir",required=True); ap.add_argument("--device",default="cuda")
    ap.add_argument("--det_model",default=r"D:\Embeddings_Distribution\yolov8n.pt"); ap.add_argument("--det_conf",type=float,default=.25); ap.add_argument("--det_imgsz",type=int,default=640); ap.add_argument("--tracker",default="bytetrack.yaml")
    ap.add_argument("--sample_fps",type=float,default=2.5); ap.add_argument("--tubelet_frames",type=int,default=16); ap.add_argument("--stride",type=int,default=8)
    ap.add_argument("--enable_pose",action="store_true"); ap.add_argument("--pose_model",default="yolov8s-pose.pt"); ap.add_argument("--pose_gate_dir",default=r"D:\Embeddings_Distribution\normality_models\pose_micro_gmm_gate_v1_yolov8s")
    ap.add_argument("--pose_threshold",type=float,default=71.38647402255272); ap.add_argument("--pose_imgsz",type=int,default=256); ap.add_argument("--pose_conf",type=float,default=.25); ap.add_argument("--pose_kpt_conf",type=float,default=.30); ap.add_argument("--pose_crop_pad_ratio",type=float,default=.25); ap.add_argument("--pose_min_crop_size",type=int,default=192)
    ap.add_argument("--enable_raft",action="store_true"); ap.add_argument("--raft_model",default="large",choices=["large","small"]); ap.add_argument("--raft_gate_dir",default=r"D:\Embeddings_Distribution\normality_models\raft_velocity_gmm_gate_v1_large_mincrop192")
    ap.add_argument("--raft_threshold",type=float,default=41.214315962694954); ap.add_argument("--raft_crop_pad_ratio",type=float,default=.20); ap.add_argument("--raft_min_crop_size",type=int,default=192); ap.add_argument("--raft_min_flow_magnitude",type=float,default=.2); ap.add_argument("--raft_max_full_side",type=int,default=960)
    ap.add_argument("--raft_flow_scope",default="crop",choices=["crop","full"]); ap.add_argument("--raft_hist_aggregation",default="sum_area",choices=["sum_area","mean","sum_valid"])
    ap.add_argument("--raft_use_dt_normalization",dest="raft_use_dt_normalization",action="store_true",default=True); ap.add_argument("--no_raft_use_dt_normalization",dest="raft_use_dt_normalization",action="store_false")
    ap.add_argument("--dump_raft_features",dest="dump_raft_features",action="store_true",default=True); ap.add_argument("--no_dump_raft_features",dest="dump_raft_features",action="store_false")
    ap.add_argument("--enable_deep",action="store_true")
    ap.add_argument("--deep_gate_dir",default=r"D:\Embeddings_Distribution\normality_models\deep_branch_artifacts_v2_gaussian",help="Deep branch artifact folder containing models\03_knn_index.joblib and 04_thresholds.json")
    ap.add_argument("--deep_k",type=int,default=1,help="k used for the saved deep kNN score. Default 1 matches the calibrated threshold.")
    ap.add_argument("--deep_threshold_key",default="p99_5",help="Threshold key in 04_thresholds.json. Default p99_5.")
    ap.add_argument("--deep_memory_npy",default="",help="Legacy fallback only. Prefer --deep_gate_dir.")
    ap.add_argument("--deep_threshold",type=float,default=.14855410158634186)
    ap.add_argument("--smoothing_sigma",type=float,default=2.0); ap.add_argument("--persistence_hits",type=int,default=3); ap.add_argument("--persistence_window",type=int,default=5)
    # Debug/safety switches for live-vs-offline comparability.
    # Offline pose features were computed on fixed 2.5-fps source times, not wall-clock gaps.
    ap.add_argument("--pose_time_mode",choices=["sample","wall"],default="sample",help="Use fixed sample time for pose/velocity features by default; wall is only for comparison debugging.")
    ap.add_argument("--max_track_gap_samples",type=int,default=8,help="Reset a track buffer if the tracker ID disappears for more than this many sampled frames. Default 8 because live RTSP tracking is noisier than offline extraction.")
    ap.add_argument("--dump_pose_features",dest="dump_pose_features",action="store_true",default=True,help="Write the 30-D live pose vector to pose_features_live.csv/jsonl for distribution debugging.")
    ap.add_argument("--no_dump_pose_features",dest="dump_pose_features",action="store_false",help="Disable the 30-D live pose feature dump.")
    ap.add_argument("--display",action="store_true"); ap.add_argument("--save_evidence",action="store_true"); ap.add_argument("--save_all_tubelets",action="store_true"); ap.add_argument("--max_runtime_sec",type=float,default=0.0); ap.add_argument("--print_every_tubelet",action="store_true")
    return ap.parse_args()

def main():
    a=parse_args(); out=ensure_dir(Path(a.output_dir)); ev=ensure_dir(out/"evidence")
    print("="*90); print("LIVE MULTI-GATE RTSP TEST - TRACKFIX + DEEP JOBLIB"); print(f"pose={a.enable_pose} raft={a.enable_raft} deep={a.enable_deep}"); print("No fusion: anomaly = any persistent gate hit"); print("="*90)
    det=YOLO(a.det_model)
    pose_model=pose_scaler=pose_gmm=None
    if a.enable_pose:
        pose_model=YOLO(a.pose_model); pose_scaler=joblib.load(Path(a.pose_gate_dir)/"models"/"pose_robust_scaler.joblib"); pose_gmm=joblib.load(Path(a.pose_gate_dir)/"models"/"pose_gmm_components_5.joblib")
    raft_model=raft_trans=vel_scaler=vel_gmm=None
    if a.enable_raft:
        raft_model,raft_trans=load_raft(a.device,a.raft_model); vel_scaler=joblib.load(Path(a.raft_gate_dir)/"models"/"velocity_robust_scaler.joblib"); vel_gmm=joblib.load(Path(a.raft_gate_dir)/"models"/"velocity_gmm_components_5.joblib")
    deep=None
    if a.enable_deep:
        if a.deep_gate_dir:
            deep=DeepGateJoblib(a.deep_gate_dir,a.device,k=a.deep_k,threshold_key=a.deep_threshold_key)
            a.deep_threshold=deep.threshold
        elif a.deep_memory_npy:
            print("[DEEP] Using legacy --deep_memory_npy fallback")
            deep=DeepGate(a.deep_memory_npy,a.device)
        else:
            raise ValueError("--enable_deep requires --deep_gate_dir or legacy --deep_memory_npy")
    cap=cv2.VideoCapture(a.rtsp_url)
    if not cap.isOpened(): raise RuntimeError("Could not open RTSP")
    buffers=defaultdict(lambda:TrackTubeletBuffer(a.tubelet_frames,a.stride))
    last_seen_sample={}
    latest_label={}
    states={"pose":defaultdict(lambda:OnlineGateState(a.pose_threshold,a.smoothing_sigma,a.persistence_hits,a.persistence_window)),
            "raft":defaultdict(lambda:OnlineGateState(a.raft_threshold,a.smoothing_sigma,a.persistence_hits,a.persistence_window)),
            "deep":defaultdict(lambda:OnlineGateState(a.deep_threshold,a.smoothing_sigma,a.persistence_hits,a.persistence_window))}
    csv=CsvAppender(out/"tubelets.csv",["wall_time","track_id","sample_start_i","sample_end_i","tubelet_start_time","tubelet_end_time","tubelet_duration_sec","deep_score","deep_hit_raw","deep_persistent_hit","raft_score","raft_score_smooth","raft_hit_raw","raft_hit_smooth","raft_persistent_hit","pose_score","pose_score_smooth","pose_hit_raw","pose_hit_smooth","pose_persistent_hit","pose_valid_frame_ratio","pose_mean_keypoint_conf","pose_valid_keypoint_ratio_mean","anomaly","reasons","evidence_frame","evidence_montage"])
    pose_feature_csv=None
    if a.enable_pose and a.dump_pose_features:
        pose_feature_csv=CsvAppender(out/"pose_features_live.csv",["wall_time","track_id","tubelet_index","sample_start_i","sample_end_i","tubelet_start_time","tubelet_end_time","tubelet_duration_sec","pose_score","pose_score_smooth","pose_hit_raw","pose_hit_smooth","pose_persistent_hit","pose_valid_frames","pose_total_frames"]+POSE_FEATURE_NAMES)
    raft_feature_csv=None
    if a.enable_raft and a.dump_raft_features:
        raft_feature_csv=CsvAppender(out/"raft_features_live.csv",["wall_time","track_id","tubelet_index","sample_start_i","sample_end_i","tubelet_start_time","tubelet_end_time","tubelet_duration_sec","raft_score","raft_score_smooth","raft_hit_raw","raft_hit_smooth","raft_persistent_hit","raft_threshold","raft_valid_pairs","raft_use_dt_normalization","raft_hist_aggregation","raft_flow_scope","raft_mean_pair_valid_pixels","raft_mean_pair_flow_mag","raft_max_pair_flow_mag","raft_mean_region_area_pixels","vbin_0","vbin_1","vbin_2","vbin_3","vbin_4","vbin_5","vbin_6","vbin_7"])
    period=1.0/a.sample_fps; last=0; sample_i=0; tubelet_count=0; event_count=0; start=time.time()
    try:
        while True:
            if a.max_runtime_sec and time.time()-start>=a.max_runtime_sec: break
            ok,frame=cap.read()
            if not ok or frame is None: print("[WARN] failed frame"); time.sleep(.1); continue
            now=time.time()

            # CRITICAL TRACKING FIX:
            # Run the tracker on EVERY camera frame, not only on sampled tubelet frames.
            # The previous version called YOLO.track() only every 0.4 sec at sample_fps=2.5.
            # That starved ByteTrack/BoT-SORT and caused ID switches/resets.
            # We still add to the anomaly tubelet buffer only at sample_fps.
            sample_due = (now-last) >= period
            if sample_due:
                last=now
                sample_i+=1

            res=det.track(source=frame,persist=True,classes=[0],conf=a.det_conf,imgsz=a.det_imgsz,tracker=a.tracker,device=a.device,verbose=False)
            annotated=frame.copy()
            if not res or res[0].boxes is None or res[0].boxes.xyxy is None:
                if a.display:
                    cv2.imshow("live_multigate",annotated)
                    if cv2.waitKey(1)&0xFF==ord("q"): break
                continue
            boxes=res[0].boxes; xyxy=boxes.xyxy.detach().cpu().numpy(); confs=boxes.conf.detach().cpu().numpy() if boxes.conf is not None else np.ones(len(xyxy),dtype=np.float32); ids=boxes.id.detach().cpu().numpy().astype(int) if boxes.id is not None else np.arange(len(xyxy),dtype=int)
            for box,conf,tid in zip(xyxy,confs,ids):
                tid=int(tid)
                b=[float(v) for v in box.tolist()]

                # Always draw live tracker output, even when this frame is not sampled into a tubelet.
                draw_box(annotated,b,latest_label.get(tid,f"id={tid}"))

                # Only sample into the 16-frame tubelet buffer at the calibrated sample_fps.
                # Tracking itself continues every frame above.
                if not sample_due:
                    continue

                prev_seen=last_seen_sample.get(tid)
                if prev_seen is not None and (sample_i-prev_seen) > (a.max_track_gap_samples+1):
                    buffers[tid]=TrackTubeletBuffer(a.tubelet_frames,a.stride)
                    states["pose"][tid]=OnlineGateState(a.pose_threshold,a.smoothing_sigma,a.persistence_hits,a.persistence_window)
                    states["raft"][tid]=OnlineGateState(a.raft_threshold,a.smoothing_sigma,a.persistence_hits,a.persistence_window)
                    states["deep"][tid]=OnlineGateState(a.deep_threshold,a.smoothing_sigma,a.persistence_hits,a.persistence_window)
                    latest_label.pop(tid,None)
                    print(f"[TRACK_RESET] track={tid} gap_samples={sample_i-prev_seen}; buffer/state reset")
                last_seen_sample[tid]=sample_i
                feature_time=(sample_i/a.sample_fps) if a.pose_time_mode=="sample" else now
                tub=buffers[tid].add(TubeletSample(frame.copy(),feature_time,sample_i,b,float(conf)))
                if tub is None: continue
                tubelet_count+=1; scores={}; gate={}; reasons=[]; pose_feature_values={}; raft_feature_values={}; raft_feature_meta={}
                sample_start_i=getattr(tub[0],"sample_i",""); sample_end_i=getattr(tub[-1],"sample_i","")
                tubelet_duration=float(tub[-1].t_wall-tub[0].t_wall)
                if a.enable_pose:
                    try:
                        X,meta=make_pose_feature_from_tubelet(pose_model,tub,a.pose_imgsz,a.pose_conf,a.pose_kpt_conf,a.pose_crop_pad_ratio,a.pose_min_crop_size,a.device)
                        X=np.asarray(X,dtype=np.float32).reshape(1,-1)
                        if X.shape[1] != len(POSE_FEATURE_NAMES):
                            raise ValueError(f"Pose feature dimension mismatch: got {X.shape[1]}, expected {len(POSE_FEATURE_NAMES)}")
                        pose_feature_values={name:_safe_float(X[0,i]) for i,name in enumerate(POSE_FEATURE_NAMES)}
                        sc=float(-pose_gmm.score_samples(pose_scaler.transform(X))[0]); gr=states["pose"][tid].update(sc); gate["pose"]=gr; scores["pose_score"]=sc; scores.update(meta); scores["pose_features"]=pose_feature_values
                        latest_label[tid]=f"id={tid} pose={sc:.1f}/{a.pose_threshold:.1f} sm={gr.get('score_smooth',''):.1f} raw={int(bool(gr.get('hit_raw')))} sh={int(bool(gr.get('hit_smooth')))} p={int(bool(gr.get('persistent_hit')))}"
                        if gr["persistent_hit"]: reasons.append("rare_pose_articulation")
                    except Exception as e:
                        gate["pose"]={"error":str(e)}; scores["pose_error"]=str(e); latest_label[tid]=f"id={tid} pose_error={str(e)[:40]}"
                if a.enable_raft:
                    try:
                        X,raft_feature_meta=raft_feature(raft_model,raft_trans,tub,a.device,a.raft_crop_pad_ratio,a.raft_min_crop_size,a.raft_min_flow_magnitude,a.raft_max_full_side,a.raft_flow_scope,a.raft_hist_aggregation,a.raft_use_dt_normalization,return_meta=True)
                        if X.shape[1] != 8:
                            raise ValueError(f"RAFT feature dimension mismatch: got {X.shape[1]}, expected 8")
                        raft_feature_values={f"vbin_{i}":_safe_float(X[0,i]) for i in range(8)}
                        sc=float(-vel_gmm.score_samples(vel_scaler.transform(X))[0]); gr=states["raft"][int(tid)].update(sc); gate["raft"]=gr; scores["raft_score"]=sc; scores["raft_features"]=raft_feature_values; scores.update(raft_feature_meta)
                        latest_label[tid]=f"id={tid} RAFT {sc:.1f}/{a.raft_threshold:.1f} S={gr.get('score_smooth',''):.1f} R={int(bool(gr.get('hit_raw')))} P={int(bool(gr.get('persistent_hit')))}"
                        if gr["persistent_hit"]: reasons.append("rare_motion_raft_velocity")
                    except Exception as e: gate["raft"]={"error":str(e)}; scores["raft_error"]=str(e); latest_label[tid]=f"id={tid} raft_error={str(e)[:40]}"
                if a.enable_deep:
                    try:
                        sc=deep.score(tub); gr=states["deep"][int(tid)].update(sc); gate["deep"]=gr; scores["deep_score"]=sc
                        if gr["persistent_hit"]: reasons.append("rare_deep_embedding")
                    except Exception as e: gate["deep"]={"error":str(e)}; scores["deep_error"]=str(e)
                anomaly=bool(reasons); ef=em=""
                if a.save_evidence and (anomaly or a.save_all_tubelets):
                    efp=ev/f"tubelet_{tubelet_count:06d}_track_{tid}_frame.jpg"; emp=ev/f"tubelet_{tubelet_count:06d}_track_{tid}_montage.jpg"
                    f=tub[-1].frame.copy(); draw_box(f,tub[-1].bbox_xyxy,",".join(reasons) if reasons else "normal",(0,0,255) if anomaly else (0,255,0)); cv2.imwrite(str(efp),f); ef=str(efp)
                    ims=[]
                    for s in tub:
                        im=s.frame.copy(); draw_box(im,s.bbox_xyxy,f"id={tid}"); ims.append(im)
                    m=make_montage(ims)
                    if m is not None: cv2.imwrite(str(emp),m); em=str(emp)
                row={"wall_time":now,"track_id":tid,"tubelet_index":tubelet_count,"sample_start_i":sample_start_i,"sample_end_i":sample_end_i,"tubelet_start_time":tub[0].t_wall,"tubelet_end_time":tub[-1].t_wall,"tubelet_duration_sec":tubelet_duration,"pose_time_mode":a.pose_time_mode,"anomaly":anomaly,"reasons":reasons,"scores":scores,"gate_results":gate,"bbox_xyxy":tub[-1].bbox_xyxy,"evidence_frame":ef,"evidence_montage":em}
                write_jsonl(out/"tubelets.jsonl",row)
                pose_gr=gate.get("pose",{})
                raft_gr=gate.get("raft",{})
                csv.write({"wall_time":now,"track_id":tid,"sample_start_i":sample_start_i,"sample_end_i":sample_end_i,"tubelet_start_time":tub[0].t_wall,"tubelet_end_time":tub[-1].t_wall,"tubelet_duration_sec":tubelet_duration,"deep_score":scores.get("deep_score",""),"deep_hit_raw":gate.get("deep",{}).get("hit_raw",""),"deep_persistent_hit":gate.get("deep",{}).get("persistent_hit",""),"raft_score":scores.get("raft_score",""),"raft_score_smooth":raft_gr.get("score_smooth",""),"raft_hit_raw":raft_gr.get("hit_raw",""),"raft_hit_smooth":raft_gr.get("hit_smooth",""),"raft_persistent_hit":raft_gr.get("persistent_hit",""),"pose_score":scores.get("pose_score",""),"pose_score_smooth":pose_gr.get("score_smooth",""),"pose_hit_raw":pose_gr.get("hit_raw",""),"pose_hit_smooth":pose_gr.get("hit_smooth",""),"pose_persistent_hit":pose_gr.get("persistent_hit",""),"pose_valid_frame_ratio":scores.get("pose_valid_frame_ratio",""),"pose_mean_keypoint_conf":scores.get("pose_mean_keypoint_conf",""),"pose_valid_keypoint_ratio_mean":scores.get("pose_valid_keypoint_ratio_mean",""),"anomaly":anomaly,"reasons":"|".join(reasons),"evidence_frame":ef,"evidence_montage":em})
                if pose_feature_csv is not None and pose_feature_values:
                    feature_row={"wall_time":now,"track_id":tid,"tubelet_index":tubelet_count,"sample_start_i":sample_start_i,"sample_end_i":sample_end_i,"tubelet_start_time":tub[0].t_wall,"tubelet_end_time":tub[-1].t_wall,"tubelet_duration_sec":tubelet_duration,"pose_score":scores.get("pose_score",""),"pose_score_smooth":pose_gr.get("score_smooth",""),"pose_hit_raw":pose_gr.get("hit_raw",""),"pose_hit_smooth":pose_gr.get("hit_smooth",""),"pose_persistent_hit":pose_gr.get("persistent_hit",""),"pose_valid_frames":scores.get("pose_valid_frames",""),"pose_total_frames":scores.get("pose_total_frames","")}
                    feature_row.update(pose_feature_values)
                    pose_feature_csv.write(feature_row)
                if raft_feature_csv is not None and raft_feature_values:
                    raft_feature_row={"wall_time":now,"track_id":tid,"tubelet_index":tubelet_count,"sample_start_i":sample_start_i,"sample_end_i":sample_end_i,"tubelet_start_time":tub[0].t_wall,"tubelet_end_time":tub[-1].t_wall,"tubelet_duration_sec":tubelet_duration,"raft_score":scores.get("raft_score",""),"raft_score_smooth":raft_gr.get("score_smooth",""),"raft_hit_raw":raft_gr.get("hit_raw",""),"raft_hit_smooth":raft_gr.get("hit_smooth",""),"raft_persistent_hit":raft_gr.get("persistent_hit",""),"raft_threshold":a.raft_threshold}
                    raft_feature_row.update(raft_feature_meta)
                    raft_feature_row.update(raft_feature_values)
                    raft_feature_csv.write(raft_feature_row)
                if anomaly:
                    event_count+=1; row["event_id"]=f"live_event_{event_count:06d}"; write_jsonl(out/"events.jsonl",row); print(f"[ANOMALY] {row['event_id']} track={tid} reasons={reasons} pose={scores.get('pose_score','')} raft={scores.get('raft_score','')} deep={scores.get('deep_score','')}")
                elif a.print_every_tubelet:
                    print(f"[TUBELET] #{tubelet_count} track={tid} normal pose={scores.get('pose_score','')} raft={scores.get('raft_score','')} deep={scores.get('deep_score','')}")
            if a.display:
                cv2.imshow("live_multigate",annotated)
                if cv2.waitKey(1)&0xFF==ord("q"): break
    except KeyboardInterrupt: print("\n[STOP]")
    finally:
        cap.release()
        if a.display: cv2.destroyAllWindows()
    summary={"script":"04_live_multigate_rtsp_test_FIXED_DEEP_TRACKING.py","tubelets_processed":tubelet_count,"events":event_count,"sample_fps":a.sample_fps,"tubelet_frames":a.tubelet_frames,"stride":a.stride,"pose_time_mode":a.pose_time_mode,"max_track_gap_samples":a.max_track_gap_samples,"dump_pose_features":a.dump_pose_features,"dump_raft_features":a.dump_raft_features,"enable_pose":a.enable_pose,"enable_raft":a.enable_raft,"enable_deep":a.enable_deep,"deep_gate_dir":getattr(a,"deep_gate_dir",None),"deep_k":getattr(a,"deep_k",None),"deep_threshold":getattr(a,"deep_threshold",None),"raft_flow_scope":a.raft_flow_scope,"raft_hist_aggregation":a.raft_hist_aggregation,"raft_use_dt_normalization":a.raft_use_dt_normalization,"raft_min_crop_size":a.raft_min_crop_size,"raft_crop_pad_ratio":a.raft_crop_pad_ratio,"raft_min_flow_magnitude":a.raft_min_flow_magnitude,"output_dir":str(out),"note":"No raw score fusion. Independent gates only. RAFT live feature extraction now matches offline 04b person-region histogram path."}
    (out/"live_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8"); print(json.dumps(summary,indent=2))
if __name__=="__main__": main()
