# ingestion/document_loader.py  (v0.5) - 경로만 정리
import io, os
from typing import Tuple
from PyPDF2 import PdfReader

def _read_pdf_bytes(b: bytes) -> str:
    try:
        r = PdfReader(io.BytesIO(b))
        txt = []
        for p in r.pages:
            try:
                t = p.extract_text() or ""
            except Exception:
                t = ""
            txt.append(t)
        return "\n".join(txt)
    except Exception:
        return ""

def _read_docx_bytes(b: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(b))
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception:
        return ""

def _read_txt_bytes(b: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return ""

def read_text_from_file(uploaded_file) -> Tuple[str, dict]:
    name = uploaded_file.name
    b = uploaded_file.getvalue()
    ext = os.path.splitext(name)[1].lower()
    meta = {"name": name, "type": ext.lstrip("."), "size": len(b)}
    if ext in [".pdf"]:
        return _read_pdf_bytes(b), meta
    if ext in [".docx"]:
        return _read_docx_bytes(b), meta
    if ext in [".txt", ".md", ".csv"]:
        return _read_txt_bytes(b), meta
    if ext in [".png", ".jpg", ".jpeg", ".bmp"]:
        return "", meta
    return "", meta
