# Apply PyTorch 2.6 weights safety load patch before importing other modules
import torch
original_load = torch.load
def safe_torch_load(*args, **kwargs):
    if 'weights_only' not in kwargs:
        kwargs['weights_only'] = False
    return original_load(*args, **kwargs)
torch.load = safe_torch_load

import cv2
import os
import time
import numpy as np
from ultralytics import YOLO

class SafetyDetector:
    def __init__(self, base_model_path="models/yolov8n.pt", helmet_model_path="models/best.pt"):
        # Load the models
        self.base_model = YOLO(base_model_path)
        self.helmet_model = YOLO(helmet_model_path)
        
    def process_video(self, input_path, output_path, task_id, update_progress):
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open input video {input_path}")
            
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # We try using mp4v codec for output.
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        frame_idx = 0
        
        # Track peaks/max concurrent counts per frame
        max_concurrent_persons = 0
        max_concurrent_motorcycles = 0
        max_concurrent_helmets = 0
        max_concurrent_violations = 0
        
        # Determine helmet model class names
        helmet_names = self.helmet_model.names
        print(f"[Task {task_id}] Helmet model classes: {helmet_names}")
        
        # Figure out which class indices correspond to helmet vs no_helmet
        helmet_class_ids = []
        no_helmet_class_ids = []
        
        for cid, name in helmet_names.items():
            name_lower = name.lower()
            if "no" in name_lower or "without" in name_lower or "head" == name_lower:
                no_helmet_class_ids.append(cid)
            elif "helmet" in name_lower or "wear" in name_lower or "with" in name_lower:
                helmet_class_ids.append(cid)
                
        # Fallback if names are simple integers or not matching keywords
        if not helmet_class_ids and not no_helmet_class_ids:
            # Usually: 0 represents helmet, 1 represents head
            helmet_class_ids = [0]
            no_helmet_class_ids = [1]
            
        print(f"[Task {task_id}] Mapped helmet classes: {helmet_class_ids}, Mapped no-helmet/head classes: {no_helmet_class_ids}")
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                    
                frame_idx += 1
                
                # Step A: Run base model to detect persons (class 0) or motorcycles (class 3)
                # Using lower image resolution (320) for speed/performance optimization
                base_results = self.base_model(frame, imgsz=320, verbose=False, classes=[0, 3])
                
                persons_in_frame = 0
                motorcycles_in_frame = 0
                helmets_in_frame = 0
                violations_in_frame = 0
                
                for r in base_results:
                    boxes = r.boxes
                    for box in boxes:
                        cls_id = int(box.cls[0])
                        xyxy = box.xyxy[0].cpu().numpy()
                        x1, y1, x2, y2 = map(int, xyxy)
                        
                        if cls_id == 0:  # Person
                            persons_in_frame += 1
                            
                            # Pad the crop box slightly to ensure we capture the head/helmet area
                            pad_w = int((x2 - x1) * 0.1)
                            pad_h_top = int((y2 - y1) * 0.15)
                            pad_h_bottom = int((y2 - y1) * 0.05)
                            
                            cx1 = max(0, x1 - pad_w)
                            cy1 = max(0, y1 - pad_h_top)
                            cx2 = min(width, x2 + pad_w)
                            cy2 = min(height, y2 + pad_h_bottom)
                            
                            crop = frame[cy1:cy2, cx1:cx2]
                            if crop.size > 0:
                                # Step B: Run the custom helmet model on the cropped region
                                helmet_results = self.helmet_model(crop, imgsz=320, verbose=False, conf=0.03)
                                
                                has_helmet = False
                                has_bare_head = False
                                detected_helmet_boxes = []
                                
                                for hr in helmet_results:
                                    h_boxes = hr.boxes
                                    for h_box in h_boxes:
                                        h_cls = int(h_box.cls[0])
                                        h_conf = float(h_box.conf[0])
                                        h_xyxy = h_box.xyxy[0].cpu().numpy()
                                        hx1, hy1, hx2, hy2 = map(int, h_xyxy)
                                        
                                        # Translate back to original frame coordinates
                                        orig_hx1 = cx1 + hx1
                                        orig_hy1 = cy1 + hy1
                                        orig_hx2 = cx1 + hx2
                                        orig_hy2 = cy1 + hy2
                                        
                                        if h_cls in helmet_class_ids and h_conf > 0.03:
                                            has_helmet = True
                                            detected_helmet_boxes.append((orig_hx1, orig_hy1, orig_hx2, orig_hy2, True, h_conf))
                                        elif h_cls in no_helmet_class_ids and h_conf > 0.03:
                                            has_bare_head = True
                                            detected_helmet_boxes.append((orig_hx1, orig_hy1, orig_hx2, orig_hy2, False, h_conf))
                                            
                                # Classify person safety compliance
                                # If a helmet is detected, the rider is safe.
                                is_safe = has_helmet
                                
                                if is_safe:
                                    helmets_in_frame += 1
                                    label_text = "Rider: Helmet"
                                    color = (46, 204, 113)  # Green (BGR: 113, 204, 46)
                                else:
                                    violations_in_frame += 1
                                    label_text = "Rider: NO HELMET"
                                    color = (60, 76, 231)   # Red (BGR: 60, 76, 231)
                                    
                                # Draw bounding box for the object
                                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                                
                                # Draw small badge for class status
                                (text_w, text_h), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                                cv2.rectangle(frame, (x1, y1 - 22), (x1 + text_w + 10, y1), color, -1)
                                cv2.putText(frame, label_text, (x1 + 5, y1 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
                                
                                # Draw individual helmet box overlays from crop if any
                                for hx1, hy1, hx2, hy2, is_h, conf in detected_helmet_boxes:
                                    h_color = (46, 204, 113) if is_h else (60, 76, 231)
                                    h_label = f"Helmet {conf:.1%}" if is_h else f"No Helmet {conf:.1%}"
                                    cv2.rectangle(frame, (hx1, hy1), (hx2, hy2), h_color, 1)
                                    cv2.putText(frame, h_label, (hx1, hy1 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.35, h_color, 1, cv2.LINE_AA)
                                    
                        elif cls_id == 3:  # Motorcycle
                            motorcycles_in_frame += 1
                            label_text = "Motorcycle"
                            color = (241, 196, 15)  # Cyan/Blue neutral color
                            
                            # Draw bounding box for motorcycle
                            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                            
                            # Draw badge
                            (text_w, text_h), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                            cv2.rectangle(frame, (x1, y1 - 22), (x1 + text_w + 10, y1), color, -1)
                            cv2.putText(frame, label_text, (x1 + 5, y1 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
                
                # Write annotated frame to disk
                out.write(frame)
                
                # Update peak counts
                max_concurrent_persons = max(max_concurrent_persons, persons_in_frame)
                max_concurrent_motorcycles = max(max_concurrent_motorcycles, motorcycles_in_frame)
                max_concurrent_violations = max(max_concurrent_violations, violations_in_frame)
                max_concurrent_helmets = max(max_concurrent_helmets, helmets_in_frame)
                
                # Send periodic progress updates
                if total_frames > 0:
                    progress = min(99.0, (frame_idx / total_frames) * 100.0)
                else:
                    progress = 50.0
                    
                # Limit callbacks frequency to avoid slowing down execution
                if frame_idx % 5 == 0 or frame_idx == total_frames:
                    update_progress(
                        task_id,
                        progress=round(progress, 1),
                        frames_processed=frame_idx,
                        total_frames=total_frames,
                        stats={
                            "persons": max_concurrent_persons,
                            "motorcycles": max_concurrent_motorcycles,
                            "helmets": max_concurrent_helmets,
                            "violations": max_concurrent_violations
                        }
                    )
                    
        except Exception as e:
            print(f"[Task {task_id}] Error occurred in detection loop: {e}")
            raise e
        finally:
            cap.release()
            out.release()
            
        # Final update
        update_progress(
            task_id,
            progress=100.0,
            frames_processed=frame_idx,
            total_frames=total_frames,
            stats={
                "persons": max_concurrent_persons,
                "motorcycles": max_concurrent_motorcycles,
                "helmets": max_concurrent_helmets,
                "violations": max_concurrent_violations
            },
            status="completed"
        )
