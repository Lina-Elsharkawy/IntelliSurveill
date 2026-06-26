#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_gate_common.py
Shared helpers for live RTSP anomaly-gate testing.
No RTSP credentials are hardcoded. Pass --rtsp_url at runtime.
"""
from __future__ import annotations
import csv, json, math, time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import cv2
import numpy as np

COCO_KPTS = {
    "nose":0,"left_eye":1,"right_eye":2,"left_ear":3,"right_ear":4,
    "left_shoulder":5,"right_shoulder":6,"left_elbow":7,"right_elbow":8,
    "left_wrist":9,"right_wrist":10,"left_hip":11,"right_hip":12,
    "left_knee":13,"right_knee":14,"left_ankle":15,"right_ankle":16,
}
WRISTS=[9,10]; ANKLES=[15,16]; LIMBS=[7,8,9,10,13,14,15,16]
LEFT_LIMBS=[7,9,13,15]; RIGHT_LIMBS=[8,10,14,16]
POSE_FEATURE_NAMES = [
"pose_valid_frame_ratio","pose_mean_keypoint_conf","pose_valid_keypoint_ratio_mean",
"pose_wrist_speed_mean","pose_wrist_speed_p95","pose_wrist_speed_max",
"pose_ankle_speed_mean","pose_ankle_speed_p95","pose_ankle_speed_max",
"pose_limb_speed_mean","pose_limb_speed_p95","pose_limb_speed_max",
"pose_limb_accel_mean","pose_limb_accel_p95","pose_limb_accel_max",
"pose_torso_center_speed_mean","pose_torso_center_speed_p95","pose_torso_center_speed_max",
"pose_body_angle_change_mean","pose_body_angle_change_p95","pose_body_angle_change_max",
"pose_crouch_change_mean","pose_crouch_change_p95","pose_crouch_change_max",
"pose_arm_extension_change_mean","pose_arm_extension_change_p95","pose_arm_extension_change_max",
"pose_asymmetry_motion_mean","pose_asymmetry_motion_p95","pose_asymmetry_motion_max",
]

def ensure_dir(p: Path): p.mkdir(parents=True, exist_ok=True); return p
def write_jsonl(path: Path, row: Dict[str, Any]):
    with open(path, "a", encoding="utf-8") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
def safe_float(x, default=0.0):
    try:
        v=float(x); return v if math.isfinite(v) else default
    except Exception: return default
def clamp_box_xyxy(box,w,h):
    x1,y1,x2,y2=[float(v) for v in box]
    x1=max(0,min(x1,w-1)); y1=max(0,min(y1,h-1)); x2=max(0,min(x2,w-1)); y2=max(0,min(y2,h-1))
    if x2<=x1: x2=min(w-1,x1+1)
    if y2<=y1: y2=min(h-1,y1+1)
    return [x1,y1,x2,y2]
def pad_box_xyxy(box,w,h,pad_ratio=0.25,min_crop_size=192):
    x1,y1,x2,y2=clamp_box_xyxy(box,w,h); bw=max(1,x2-x1); bh=max(1,y2-y1); cx=(x1+x2)/2; cy=(y1+y2)/2
    nw=max(bw*(1+2*pad_ratio),float(min_crop_size)); nh=max(bh*(1+2*pad_ratio),float(min_crop_size))
    px1=max(0,min(cx-nw/2,w-1)); py1=max(0,min(cy-nh/2,h-1)); px2=max(0,min(cx+nw/2,w-1)); py2=max(0,min(cy+nh/2,h-1))
    if px2<=px1: px2=min(w-1,px1+1)
    if py2<=py1: py2=min(h-1,py1+1)
    return [int(round(px1)),int(round(py1)),int(round(px2)),int(round(py2))]
def union_box(boxes,w,h,pad_ratio=0.20,min_crop_size=192):
    a=np.asarray(boxes,dtype=np.float32)
    return pad_box_xyxy([np.nanmin(a[:,0]),np.nanmin(a[:,1]),np.nanmax(a[:,2]),np.nanmax(a[:,3])],w,h,pad_ratio,min_crop_size)
def crop_frame(frame, box):
    x1,y1,x2,y2=box; crop=frame[y1:y2,x1:x2]
    return None if crop is None or crop.size==0 else crop
def draw_box(frame, box, label="", color=(0,255,255)):
    x1,y1,x2,y2=[int(round(v)) for v in box]
    cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)
    if label: cv2.putText(frame,label,(x1,max(18,y1-7)),cv2.FONT_HERSHEY_SIMPLEX,0.55,color,2,cv2.LINE_AA)
    return frame

class CsvAppender:
    def __init__(self,path,fieldnames):
        self.path=Path(path); self.fieldnames=fieldnames; self.written=self.path.exists() and self.path.stat().st_size>0
    def write(self,row):
        with open(self.path,"a",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=self.fieldnames)
            if not self.written: w.writeheader(); self.written=True
            w.writerow({k:row.get(k,"") for k in self.fieldnames})

@dataclass
class TubeletSample:
    frame: np.ndarray
    t_wall: float
    sample_index: int
    bbox_xyxy: List[float]
    det_conf: float = 0.0

class TrackTubeletBuffer:
    def __init__(self,tubelet_frames=16,stride=8,max_samples=64):
        self.tubelet_frames=int(tubelet_frames); self.stride=int(stride); self.samples=deque(maxlen=max_samples); self.last_emit=None
    def add(self,sample):
        self.samples.append(sample)
        if len(self.samples)<self.tubelet_frames: return None
        latest=self.samples[-1].sample_index
        if self.last_emit is not None and latest-self.last_emit<self.stride: return None
        self.last_emit=latest
        return list(self.samples)[-self.tubelet_frames:]

class OnlineGateState:
    # Causal approximation of offline gaussian smoothing + persistence
    def __init__(self,threshold,sigma=2.0,persistence_hits=3,persistence_window=5):
        self.threshold=float(threshold); self.sigma=float(sigma); self.hits=int(persistence_hits); self.window=int(persistence_window)
        self.scores=deque(maxlen=max(12,int(round(6*sigma+persistence_window+4)))); self.smooth_hits=deque(maxlen=self.window)
    def _smooth(self):
        vals=np.asarray(list(self.scores),dtype=np.float64)
        if len(vals)==0: return 0.0
        if self.sigma<=0 or len(vals)==1: return float(vals[-1])
        r=int(max(1,round(3*self.sigma))); recent=vals[-(r+1):]
        d=np.arange(len(recent)-1,-1,-1,dtype=np.float64); w=np.exp(-(d*d)/(2*self.sigma*self.sigma)); w/=w.sum()
        return float(np.sum(recent*w))
    def update(self,score):
        score=safe_float(score); self.scores.append(score); sm=self._smooth()
        raw=score>self.threshold; sh=sm>self.threshold; self.smooth_hits.append(sh); ph=sum(self.smooth_hits)>=self.hits
        return {"score":score,"score_smooth":sm,"threshold":self.threshold,"hit_raw":bool(raw),"hit_smooth":bool(sh),"persistent_hit":bool(ph),"recent_smooth_hits":int(sum(self.smooth_hits))}

def choose_best_pose(result):
    if result is None or getattr(result,"keypoints",None) is None: return None,None
    k=result.keypoints; xy=getattr(k,"xy",None); conf=getattr(k,"conf",None)
    if xy is None: return None,None
    xy_np=xy.detach().cpu().numpy()
    conf_np=conf.detach().cpu().numpy() if conf is not None else np.ones((xy_np.shape[0],xy_np.shape[1]),dtype=np.float32)
    if xy_np.ndim!=3 or xy_np.shape[0]==0: return None,None
    best=int(np.nanargmax(np.nanmean(conf_np,axis=1)))
    if xy_np[best].shape[0]<17: return None,None
    return xy_np[best][:17].astype(np.float32), conf_np[best][:17].astype(np.float32)
def aggregate(vals):
    a=np.asarray(vals,dtype=np.float64); a=a[np.isfinite(a)]
    if a.size==0: return 0.0,0.0,0.0
    return float(np.mean(a)),float(np.percentile(a,95)),float(np.max(a))
def center_of(kpts,valid,ids):
    pts=[kpts[i] for i in ids if valid[i]]
    return None if not pts else np.mean(np.asarray(pts),axis=0)
def angle_wrap(delta): return (delta+np.pi)%(2*np.pi)-np.pi
def point_speed_series(kpts,valid,times,ids):
    out=[]
    for t in range(1,len(times)):
        dt=float(times[t]-times[t-1])
        if dt<=1e-6: continue
        for k in ids:
            if valid[t,k] and valid[t-1,k]:
                d=np.linalg.norm(kpts[t,k]-kpts[t-1,k])
                if math.isfinite(d): out.append(float(d/dt))
    return out
def point_accel_series(kpts,valid,times,ids):
    speeds=defaultdict(list); out=[]
    for k in ids:
        for t in range(1,len(times)):
            dt=float(times[t]-times[t-1])
            if dt<=1e-6: continue
            if valid[t,k] and valid[t-1,k]:
                d=np.linalg.norm(kpts[t,k]-kpts[t-1,k])
                if math.isfinite(d): speeds[k].append((t,float(d/dt)))
    for vals in speeds.values():
        for i in range(1,len(vals)):
            tp,sp=vals[i-1]; tc,sc=vals[i]; dt=float(times[tc]-times[tp])
            if dt>1e-6: out.append(abs(sc-sp)/dt)
    return out
def torso_center_speed_series(kpts,valid,times):
    centers=[]
    for t in range(len(times)):
        sh=center_of(kpts[t],valid[t],[5,6]); hp=center_of(kpts[t],valid[t],[11,12])
        centers.append(None if sh is None or hp is None else (sh+hp)/2)
    out=[]
    for t in range(1,len(times)):
        if centers[t] is None or centers[t-1] is None: continue
        dt=float(times[t]-times[t-1])
        if dt>1e-6: out.append(float(np.linalg.norm(centers[t]-centers[t-1])/dt))
    return out
def body_angle_change_series(kpts,valid,times):
    angles=[]
    for t in range(len(times)):
        sh=center_of(kpts[t],valid[t],[5,6]); hp=center_of(kpts[t],valid[t],[11,12])
        angles.append(None if sh is None or hp is None else math.atan2(float((sh-hp)[1]),float((sh-hp)[0])))
    out=[]
    for t in range(1,len(times)):
        if angles[t] is None or angles[t-1] is None: continue
        dt=float(times[t]-times[t-1])
        if dt>1e-6: out.append(abs(angle_wrap(angles[t]-angles[t-1]))/dt)
    return out
def simple_change_series(kpts,valid,times,mode):
    vals=[]
    for t in range(len(times)):
        if mode=="crouch":
            sh=center_of(kpts[t],valid[t],[5,6]); hp=center_of(kpts[t],valid[t],[11,12])
            vals.append(None if sh is None or hp is None else abs(float(hp[1]-sh[1])))
        else:
            pairs=[(5,9),(6,10)]; frame=[]
            for a,b in pairs:
                if valid[t,a] and valid[t,b]:
                    d=np.linalg.norm(kpts[t,a]-kpts[t,b])
                    if math.isfinite(d): frame.append(float(d))
            vals.append(float(np.mean(frame)) if frame else None)
    out=[]
    for t in range(1,len(times)):
        if vals[t] is None or vals[t-1] is None: continue
        dt=float(times[t]-times[t-1])
        if dt>1e-6: out.append(abs(vals[t]-vals[t-1])/dt)
    return out
def asymmetry_motion_series(kpts,valid,times):
    out=[]
    for t in range(1,len(times)):
        dt=float(times[t]-times[t-1])
        if dt<=1e-6: continue
        L=[]; R=[]
        for k in LEFT_LIMBS:
            if valid[t,k] and valid[t-1,k]: L.append(float(np.linalg.norm(kpts[t,k]-kpts[t-1,k])/dt))
        for k in RIGHT_LIMBS:
            if valid[t,k] and valid[t-1,k]: R.append(float(np.linalg.norm(kpts[t,k]-kpts[t-1,k])/dt))
        if L and R: out.append(abs(float(np.mean(L))-float(np.mean(R))))
    return out
def compute_pose_features(kpts_norm,conf,times,kpt_conf_thr):
    T=len(times)
    if T==0: return np.zeros(len(POSE_FEATURE_NAMES),dtype=np.float32),{}
    finite=np.isfinite(kpts_norm).all(axis=2); valid=finite & np.isfinite(conf) & (conf>=kpt_conf_thr)
    valid_frame=valid.sum(axis=1)>=5
    vm=valid_frame.mean() if T else 0; mc=float(np.mean(conf[valid])) if conf[valid].size else 0; vkr=float(np.mean(valid.mean(axis=1))) if T else 0
    ws=aggregate(point_speed_series(kpts_norm,valid,times,WRISTS)); ans=aggregate(point_speed_series(kpts_norm,valid,times,ANKLES))
    ls=aggregate(point_speed_series(kpts_norm,valid,times,LIMBS)); la=aggregate(point_accel_series(kpts_norm,valid,times,LIMBS))
    ts=aggregate(torso_center_speed_series(kpts_norm,valid,times)); ba=aggregate(body_angle_change_series(kpts_norm,valid,times))
    cr=aggregate(simple_change_series(kpts_norm,valid,times,"crouch")); ae=aggregate(simple_change_series(kpts_norm,valid,times,"arm"))
    sy=aggregate(asymmetry_motion_series(kpts_norm,valid,times))
    feat=np.array([vm,mc,vkr,*ws,*ans,*ls,*la,*ts,*ba,*cr,*ae,*sy],dtype=np.float32)
    meta={"pose_valid_frames":int(valid_frame.sum()),"pose_total_frames":int(T),"pose_valid_frame_ratio":float(vm),"pose_mean_keypoint_conf":mc,"pose_valid_keypoint_ratio_mean":vkr}
    return feat,meta

def make_pose_feature_from_tubelet(pose_model,tubelet_samples,imgsz=256,conf=0.25,kpt_conf=0.30,crop_pad_ratio=0.25,min_crop_size=192,device="cuda"):
    crops=[]; infos=[]; bboxes=[]; times=[]
    for s in tubelet_samples:
        h,w=s.frame.shape[:2]; bbox=clamp_box_xyxy(s.bbox_xyxy,w,h); cb=pad_box_xyxy(bbox,w,h,crop_pad_ratio,min_crop_size); cr=crop_frame(s.frame,cb)
        crops.append(cr); infos.append(cb); bboxes.append(bbox); times.append(float(s.t_wall))
    valid_idx=[i for i,c in enumerate(crops) if c is not None]
    if not valid_idx: raise ValueError("No valid crops for pose")
    results=pose_model.predict(source=[crops[i] for i in valid_idx],imgsz=imgsz,conf=conf,device=device,verbose=False)
    n=len(tubelet_samples); kpts=np.full((n,17,2),np.nan,dtype=np.float32); carr=np.zeros((n,17),dtype=np.float32)
    for li,res in enumerate(results):
        i=valid_idx[li]; xy,kconf=choose_best_pose(res)
        if xy is None: continue
        cx1,cy1,_,_=infos[i]; bx1,by1,bx2,by2=bboxes[i]; bw=max(1,bx2-bx1); bh=max(1,by2-by1)
        xyo=xy.copy(); xyo[:,0]+=cx1; xyo[:,1]+=cy1
        norm=np.zeros_like(xyo,dtype=np.float32); norm[:,0]=(xyo[:,0]-bx1)/bw; norm[:,1]=(xyo[:,1]-by1)/bh
        kpts[i]=norm; carr[i]=kconf.astype(np.float32)
    feat,meta=compute_pose_features(kpts,carr,np.asarray(times,dtype=np.float64),kpt_conf)
    if not np.isfinite(feat).all(): raise ValueError("Non-finite pose features")
    return feat.reshape(1,-1),meta

def make_montage(frames,cols=4,width=320):
    if not frames: return None
    small=[]
    for f in frames:
        h,w=f.shape[:2]; nh=max(1,int(round(h*(width/max(1,w))))); small.append(cv2.resize(f,(width,nh)))
    mh=max(im.shape[0] for im in small); padded=[]
    for im in small:
        if im.shape[0]<mh: im=np.vstack([im,np.zeros((mh-im.shape[0],im.shape[1],3),dtype=im.dtype)])
        padded.append(im)
    rows=[]
    for i in range(0,len(padded),cols):
        row=padded[i:i+cols]
        while len(row)<cols: row.append(np.zeros_like(padded[0]))
        rows.append(np.hstack(row))
    return np.vstack(rows)
