# utils/ui.py  (v0.5.1 hotfix)
from typing import Dict
import streamlit as st
import pandas as pd

def dataset_card(title: str, df: pd.DataFrame):
    # expander는 key를 지원하지 않는 버전이 있습니다 → key 제거
    with st.expander(f"{title} (shape={df.shape})", expanded=False):
        #st.dataframe(df, use_container_width=True, height=300)
        st.dataframe(df, width="stretch", height=300) #패치

def evidence_card(ev: Dict, idx: int):
    # expander key 제거
    with st.expander(f"증거: {ev['name']} ({ev['type']})", expanded=False):
        preview_val = (ev.get("preview") or "")[:8000]   # v0.5: 8k
        if preview_val:
            # text_area는 key 사용 가능하므로 유지(동일 세션에서 여러 개 렌더링시 충돌 방지)
            st.text_area("미리보기", preview_val, height=220, key=f"ev_preview_{idx}")
        st.json({k: v for k, v in ev.items() if k not in ["bytes", "preview"]}, expanded=False)

