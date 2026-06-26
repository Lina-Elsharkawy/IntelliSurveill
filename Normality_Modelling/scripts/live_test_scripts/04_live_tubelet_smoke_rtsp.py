#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse,json,time
from collections import defaultdict
from pathlib import Path
import cv2, numpy as np
from ultralytics import YOLO
from live_gate_common import TrackTubeletBuffer, TubeletSample, ensure_dir, write_jsonl, draw_box, make_montage

def parse_args():
    ap=argparse.ArgumentParser()
    ap.add_argument("--rtsp_url",required=True); ap.add_argument("--output_dir",required=True)
    ap.add_argument("--device",default="cuda"); ap.add_argument("--det_model",default=r"D:\Embeddings_Distribution\yolov8n.pt")
    ap.add_argument("--det_conf",type=float,default=0.25); ap.add_argument("--det_imgsz",type=int,default=640); ap.add_argument("--tracker",default="bytetrack.yaml")
    ap.add_argument("--sample_fps",type=float,default=2.5); ap.add_argument("--tubelet_frames",type=int,default=16); ap.add_argument("--stride",type=int,default=8)
    ap.add_argument("--save_montages",action="store_true"); ap.add_argument("--display",action="store_true"); ap.add_argument("--max_runtime_sec",type=float,default=0.0)
    return ap.parse_args()

def main():
    a=parse_args(); out=ensure_dir(Path(a.output_dir)); ev=ensure_dir(out/"tubelet_montages"); js=out/"tubelets_smoke.jsonl"
    print("LIVE TUBELET SMOKE TEST - no gates loaded")
    model=YOLO(a.det_model); cap=cv2.VideoCapture(a.rtsp_url)
    if not cap.isOpened(): raise RuntimeError("Could not open RTSP stream.")
    buffers=defaultdict(lambda:TrackTubeletBuffer(a.tubelet_frames,a.stride)); period=1.0/a.sample_fps
    last=0; sample_i=0; tubelets=0; frames=0; start=time.time()
    try:
        while True:
            if a.max_runtime_sec and time.time()-start>=a.max_runtime_sec: break
            ok,frame=cap.read()
            if not ok or frame is None: print("[WARN] failed frame"); time.sleep(.1); continue
            frames+=1; now=time.time()
            if now-last<period:
                if a.display:
                    cv2.imshow("smoke",frame)
                    if cv2.waitKey(1)&0xFF==ord("q"): break
                continue
            last=now; sample_i+=1
            res=model.track(source=frame,persist=True,classes=[0],conf=a.det_conf,imgsz=a.det_imgsz,tracker=a.tracker,device=a.device,verbose=False)
            annotated=frame.copy()
            if res and res[0].boxes is not None and res[0].boxes.xyxy is not None:
                boxes=res[0].boxes; xyxy=boxes.xyxy.detach().cpu().numpy()
                confs=boxes.conf.detach().cpu().numpy() if boxes.conf is not None else np.ones(len(xyxy),dtype=np.float32)
                ids=boxes.id.detach().cpu().numpy().astype(int) if boxes.id is not None else np.arange(len(xyxy),dtype=int)
                for box,conf,tid in zip(xyxy,confs,ids):
                    b=[float(v) for v in box.tolist()]; draw_box(annotated,b,f"id={tid}")
                    tub=buffers[int(tid)].add(TubeletSample(frame.copy(),now,sample_i,b,float(conf)))
                    if tub is None: continue
                    tubelets+=1; mp=""
                    if a.save_montages:
                        ims=[]
                        for s in tub:
                            f=s.frame.copy(); draw_box(f,s.bbox_xyxy,f"id={tid}"); ims.append(f)
                        m=make_montage(ims)
                        if m is not None:
                            p=ev/f"tubelet_{tubelets:06d}_track_{tid}.jpg"; cv2.imwrite(str(p),m); mp=str(p)
                    row={"tubelet_index":tubelets,"track_id":int(tid),"sample_index":sample_i,"start_time":tub[0].t_wall,"end_time":tub[-1].t_wall,"montage_path":mp}
                    write_jsonl(js,row); print(f"[TUBELET] #{tubelets} track={tid} montage={mp}")
            if a.display:
                cv2.imshow("smoke",annotated)
                if cv2.waitKey(1)&0xFF==ord("q"): break
    except KeyboardInterrupt: print("\n[STOP]")
    finally:
        cap.release()
        if a.display: cv2.destroyAllWindows()
    summary={"frames_read":frames,"samples":sample_i,"tubelets_created":tubelets,"output_dir":str(out)}
    (out/"smoke_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8"); print(json.dumps(summary,indent=2))
if __name__=="__main__": main()
