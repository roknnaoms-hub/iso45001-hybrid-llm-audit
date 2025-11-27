
# app.py — v1.0 (compat + audit log)
from dotenv import load_dotenv
load_dotenv()

import os, json, datetime, io, pathlib, platform, mimetypes, time
from io import BytesIO
import pandas as pd
import streamlit as st

from llm_backends import get_backend
from utils.audit_logic import (
    read_csv_utf8sig, select_relevant_rows, build_system_prompt,
    build_user_prompt, offline_baseline, validate_clause_schema,
    find_requirement_text, normalize_findings_json, Finding, to_sha1, find_column
)
from utils.audit_logger import write_audit_log

# optional deps
try:
    import chardet
except Exception:
    chardet = None
try:
    from PIL import Image, ExifTags
except Exception:
    Image, ExifTags = None, None
try:
    import pytesseract
except Exception:
    pytesseract = None
try:
    import PyPDF2
except Exception:
    PyPDF2 = None

# fonts
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
if platform.system() == "Windows":
    plt.rc("font", family="Malgun Gothic")
elif platform.system() == "Darwin":
    plt.rc("font", family="AppleGothic")
else:
    plt.rc("font", family="NanumGothic")
plt.rcParams["axes.unicode_minus"] = False
st.markdown("""
    <style>
    html, body, [class*="css"] {
        font-family: "Malgun Gothic", "AppleGothic", "NanumGothic", sans-serif !important;
    }
    div[data-testid="stDataFrame"], code, pre {
        font-family: "Malgun Gothic", "AppleGothic", "NanumGothic", monospace !important;
    }
    </style>
""", unsafe_allow_html=True)

st.set_page_config(layout="wide", page_title="ISO45001 Audit v0.7.3 (LM-2500)")

DATA_DIR = pathlib.Path("./data")
CLAUSE_CSV = DATA_DIR / "iso45001_clause_mapping_utf8sig.csv"
CHECKLIST_CSV = DATA_DIR / "iso45001_agent_prompt_tuning_checklist_utf8sig.csv"
LOG_DIR = "./logs"

@st.cache_data
def load_df(path: str):
    return read_csv_utf8sig(path)

def sidebar():
    with st.sidebar:
        st.subheader("⚙️ 백엔드/모델")
        backend_name = st.selectbox("LLM 백엔드", ["openai","ollama","lmstudio"], index=["openai","ollama","lmstudio"].index(os.getenv("LLM_BACKEND","openai")))
        model_name = st.text_input("모델명(로컬)", os.getenv("OLLAMA_MODEL","llama3:8b-instruct"))
        clause_hint = st.text_input("조항 힌트", "")
        lm2500 = st.toggle("LM-2500 작업장 프리셋", value=True)
        ocr_on = st.toggle("이미지 OCR(한/영)", value=False)
        run_btn = st.button("심사 실행", type="primary", use_container_width=True)
    return backend_name, model_name, clause_hint, lm2500, ocr_on, run_btn

# evidence helpers (binary-safe)
def _guess_encoding(b: bytes) -> str:
    if chardet:
        try:
            det = chardet.detect(b or b"")
            enc = (det.get("encoding") or "").strip()
            if enc:
                return enc
        except Exception:
            pass
    return "utf-8-sig"

def _is_binary_bytes(b: bytes, sample=512) -> bool:
    head = b[:sample]
    nontext = sum(c < 9 or (13 < c < 32) for c in head)
    return (0 in head) or (nontext / max(1, len(head)) > 0.2)

def _ext_from_name(name: str) -> str:
    return (name.rsplit(".", 1)[-1] if "." in name else "").lower()

def _mime_from_name(name: str) -> str:
    import mimetypes
    return (mimetypes.guess_type(name)[0] or "").lower()

def _summarize_image(name: str, b: bytes, ocr: bool=False, ocr_lang: str="kor+eng") -> str:
    if not Image:
        return f"[{name}] (이미지 파일, 미리보기만 표시. OCR 미지원)"
    try:
        im = Image.open(BytesIO(b))
        info = f"[{name}] 이미지 {im.format} {im.width}x{im.height}px"
        exif_txt = ""
        try:
            exif = im.getexif()
            if exif and len(exif):
                from PIL import ExifTags
                kv = []
                for k, v in exif.items():
                    try:
                        tag = ExifTags.TAGS.get(k, str(k))
                        if tag in ("DateTime","Make","Model","Software","Orientation"):
                            kv.append(f"{tag}={v}")
                    except Exception:
                        pass
                if kv:
                    exif_txt = " | EXIF: " + ", ".join(kv[:6])
        except Exception:
            pass
        ocr_txt = ""
        if ocr and pytesseract:
            try:
                ocr_txt = pytesseract.image_to_string(im, lang=ocr_lang)
                ocr_txt = (ocr_txt or "").strip()
                if ocr_txt:
                    ocr_txt = "\n[OCR]\n" + ocr_txt[:800]
            except Exception as e:
                ocr_txt = f"\n[OCR 실패] {e}"
        elif ocr and not pytesseract:
            ocr_txt = "\n[OCR 비활성화] pytesseract 미설치"
        return info + exif_txt + ocr_txt
    except Exception as e:
        return f"[{name}] (이미지 파싱 실패: {e})"

def _summarize_pdf(name: str, b: bytes, max_chars=1200) -> str:
    if not PyPDF2:
        return f"[{name}] (PDF 파일, PyPDF2 미설치로 본문 미리보기 생략)"
    try:
        reader = PyPDF2.PdfReader(BytesIO(b))
        texts = []
        for i, page in enumerate(reader.pages[:2]):
            try:
                t = page.extract_text() or ""
                if t.strip():
                    texts.append(t.strip())
            except Exception:
                pass
        text = "\n".join(texts)[:max_chars]
        if not text:
            return f"[{name}] (PDF, 추출된 텍스트 없음)"
        return f"[{name}] (PDF 요약)\n{text}"
    except Exception as e:
        return f"[{name}] (PDF 파싱 실패: {e})"

def digest_evidence(uploaded_files, enable_ocr=False) -> str:
    parts = []
    for f in (uploaded_files or []):
        name = getattr(f, "name", "evidence.bin")
        b = f.getvalue()

        ext = _ext_from_name(name)
        mime = _mime_from_name(name)

        # 이미지
        if mime.startswith("image/") or ext in ("jpg","jpeg","png","bmp","tif","tiff","gif","webp"):
            parts.append(_summarize_image(name, b, ocr=enable_ocr))
            continue

        # PDF
        if mime == "application/pdf" or ext == "pdf":
            parts.append(_summarize_pdf(name, b))
            continue

        # 텍스트
        if not _is_binary_bytes(b):
            try:
                enc = _guess_encoding(b)
                txt = b.decode(enc, errors="replace")
                parts.append(f"[{name}] (텍스트/{enc})\n{txt[:1200]}")
                continue
            except Exception as e:
                parts.append(f"[{name}] (텍스트 디코딩 실패: {e})")
                continue

        # 기타 바이너리
        parts.append(f"[{name}] (바이너리 파일, {len(b)} bytes)")
    return "\n---\n".join(parts) if parts else "증거 없음"

def main():
    st.title("온/오프라인 LLM기반 ISO 45001 인증심사 플랫폼 v1.0")
    backend_name, model_name, clause_hint, use_lm2500, ocr_on, run_btn = sidebar()

    # 데이터 로드
    df_clause = load_df(str(CLAUSE_CSV))
    df_check  = load_df(str(CHECKLIST_CSV))
    with st.expander("데이터 확인 / 컬럼 매핑", expanded=False):
        st.write("Checklist CSV columns:", list(df_check.columns))
        st.write("Detected:", {
            "clause": find_column(df_check,"clause"),
            "title": find_column(df_check,"title"),
            "question": find_column(df_check,"question"),
            "evidence_type": find_column(df_check,"evidence_type"),
        })
        st.dataframe(df_check.head(15), height=220)

    if "files" not in st.session_state:
        st.session_state.files = []

    st.subheader("증거 업로드")
    files = st.file_uploader("문서(txt/pdf->txt), 로그, 절차서 등 업로드", accept_multiple_files=True)
    if files:
        st.session_state.files = files

    ev_digest = digest_evidence(st.session_state.files, enable_ocr=ocr_on)
    st.text_area("증거 요약(자동 생성 미리보기)", ev_digest, height=180)

    # LM-2500 프리셋 로드
    lm2500_weight = None
    if use_lm2500:
        try:
            preset = json.load(open("./presets/lm2500_profile.json", "r", encoding="utf-8"))
            lm2500_weight = preset.get("keywords_weight", {})
            if not clause_hint:
                clause_hint = preset.get("clause_hint","")
        except Exception as e:
            st.warning(f"LM-2500 프리셋 로드 실패: {e}")

    # 컨텍스트 선택
    st.subheader("컨텍스트 선택")
    try:
        df_ctx = select_relevant_rows(df_check, clause_hint, lm2500_weight=lm2500_weight)
    except Exception as e:
        st.warning(f"행 선택 로직 경고: {e}")
        df_ctx = df_check.copy()
    st.dataframe(df_ctx.head(15), height=260)

    if run_btn:
        start_t = time.time()

        os.environ["LLM_BACKEND"] = backend_name
        if backend_name == "ollama":
            os.environ["OLLAMA_MODEL"] = model_name
        if backend_name == "lmstudio":
            os.environ["LMSTUDIO_MODEL"] = model_name
        backend = get_backend(backend_name)

        system = build_system_prompt(df_ctx)
        user   = build_user_prompt(ev_digest, clause_hint)

        st.info(f"백엔드={backend_name}, 모델={model_name}, 조항힌트='{clause_hint}', OCR={'ON' if ocr_on else 'OFF'}")
        try:
            result = backend.generate(system=system, user=user, clause_hint=clause_hint)
            result = normalize_findings_json(result)
            findings = [Finding(**f).model_dump() for f in result.get("findings",[])]
        except Exception as e:
            st.error(f"LLM 실패: {e} → 오프라인 규칙으로 폴백합니다.")
            result = offline_baseline(df_ctx, ev_digest, clause_hint)
            findings = result["findings"]

        st.subheader("심사 결과")
        st.json({"findings": findings})

        # 로그/다운로드
        audit_id = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ") + "_" + to_sha1(ev_digest)[:8]
        st.write(f"Audit ID: `{audit_id}`")
        csv_rows = []
        for f in findings:
            csv_rows.append({
                "audit_id": audit_id,
                "clause": f["clause"],
                "title": f["title"],
                "result": f["result"],
                "reason": f["reason"],
                "backend": backend_name,
                "model": model_name
            })
        out_df = pd.DataFrame(csv_rows)
        csv_bytes = out_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("결과 CSV 다운로드", csv_bytes, file_name=f"audit_{audit_id}.csv", mime="text/csv")

        # 재현성 로그 기록
        elapsed = time.time() - start_t
        log_path = write_audit_log(LOG_DIR, audit_id, backend_name, model_name, clause_hint, ev_digest, csv_bytes, len(findings), "v0.7.3", elapsed)
        st.caption(f"Audit log recorded: {log_path}")

if __name__ == "__main__":
    main()
