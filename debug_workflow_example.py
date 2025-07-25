"""
실제 RunPod ComfyUI로 전송되는 워크플로우 예시 (디버깅용)
"""

# 이것이 실제로 RunPod ComfyUI /prompt API로 전송되는 JSON 구조입니다
example_payload = {
    "prompt": {
        "id": "f253212e-0ec7-40c5-9671-bafc52d66023",
        "revision": 0,
        "last_node_id": 48,
        "last_link_id": 131,
        "nodes": [
            {
                "id": 6,
                "type": "CLIPTextEncode",
                "pos": [64.37030792236328, 112.25189208984375],
                "size": [422.84503173828125, 164.31304931640625],
                "flags": {},
                "order": 8,
                "mode": 0,
                "inputs": [
                    {"name": "clip", "type": "CLIP", "link": 127},
                    {"name": "text", "type": "STRING", "widget": {"name": "text"}, "link": None}
                ],
                "outputs": [
                    {"name": "CONDITIONING", "type": "CONDITIONING", "slot_index": 0, "links": [41]}
                ],
                "title": "CLIP Text Encode (Positive Prompt)",
                "properties": {"cnr_id": "comfy-core", "ver": "0.3.24", "Node name for S&R": "CLIPTextEncode"},
                # 🔥 여기가 핵심! 최적화된 프롬프트가 들어가는 부분
                "widgets_values": [
                    "Photorealistic portrait of a beautiful woman, captured with cinematic composition and shallow depth of field, golden hour lighting, warm color palette, professional photography, high quality"
                ],
                "color": "#232",
                "bgcolor": "#353"
            },
            # ... 다른 노드들 (FluxGuidance, BasicScheduler, etc.)
            {
                "id": 26,
                "type": "FluxGuidance", 
                "widgets_values": [3.5]  # guidance 값
            },
            {
                "id": 17,
                "type": "BasicScheduler",
                "widgets_values": ["simple", 8, 1]  # steps 값
            }
            # ... 나머지 노드들
        ],
        "links": [
            # 노드 간 연결 정보
            [41, 6, 0, 26, 0, "CONDITIONING"],  # CLIP Text Encode → FluxGuidance
            [42, 26, 0, 22, 1, "CONDITIONING"], # FluxGuidance → BasicGuider
            # ... 기타 연결들
        ]
    }
}

# 이 전체 JSON이 RunPod ComfyUI의 /prompt 엔드포인트로 POST 요청됩니다
print("이 JSON 구조가 실제로 RunPod ComfyUI로 전송됩니다!")
print(f"프롬프트가 삽입되는 위치: nodes[0]['widgets_values'][0]")
print(f"예시 프롬프트: {example_payload['prompt']['nodes'][0]['widgets_values'][0]}")