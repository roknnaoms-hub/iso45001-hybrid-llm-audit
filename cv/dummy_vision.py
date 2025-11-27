# cv/dummy_vision.py  (v0.5)
from typing import List, Dict

def analyze_images(files: List[bytes]) -> Dict:
    # TODO: 교체: YOLO/Detectron2/ViT + PPE 규칙 검증
    return {
        "ppe_check": "not_performed",   # "pass" | "fail" | "not_performed"
        "notes": "샘플 비전 결과(실제 모델 연동 필요)",
        "image_count": len(files),
        "detections": []                # [{"filename": "x.png", "labels": [...]}]
    }
