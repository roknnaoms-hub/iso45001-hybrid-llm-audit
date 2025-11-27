
# utils/audit_logic.py — v0.7.3 (pydantic v2-ready)
import re, hashlib, json, os
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd
from pydantic import BaseModel, Field, ValidationError

CAT_DEFINITIONS = {
    "Cat.1": "ISO45001 요건의 시스템 부재 또는 심각한 시스템적 결함 또는 중대 재해 위험",
    "Cat.2": "문서화된 절차의 경미한 불이행·운영상 실수·법규 위반 가능성",
    "Y":     "관찰사항(개선 필요 가능)",
    "N":     "해당 없음/적합"
}

class Finding(BaseModel):
    title: str = Field(..., description="관찰/결함 제목")
    clause: str = Field(..., description="ISO45001 조항(예: 6.1.2)")
    reason: str = Field(..., description="근거/사유 요약")
    result: str = Field(..., description="Cat.1 | Cat.2 | Y | N")

def to_sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def read_csv_utf8sig(path: str) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")

ALIASES = {
    "clause": ["clause","조항","Clause","항목번호","항목코드"],
    "title": ["title","항목","항목명","요구사항명","점검항목","표제","제목"],
    "question": ["question","요구사항","설명","체크포인트","질문","검증내용","평가질문"],
    "evidence_type": ["evidence_type","evidence","증거유형","증거","입증자료","근거자료"]
}

def find_column(df: pd.DataFrame, logical: str) -> Optional[str]:
    cols_lower = {c.lower(): c for c in df.columns}
    for a in ALIASES.get(logical, []):
        if a.lower() in cols_lower:
            return cols_lower[a.lower()]
    return None

def validate_clause_schema(df: pd.DataFrame) -> bool:
    c = find_column(df, "clause")
    t = find_column(df, "title")
    q = find_column(df, "question")
    return c is not None and (t is not None or q is not None)

def col_or_default(df: pd.DataFrame, logical: str, default: str="") -> pd.Series:
    name = find_column(df, logical)
    if name and name in df.columns:
        return df[name]
    return pd.Series([default]*len(df))

def find_requirement_text(df: pd.DataFrame, clause: str) -> str:
    clause_col = find_column(df,"clause")
    question_col = find_column(df,"question")
    if clause_col is None:
        return ""
    c = df[df[clause_col].astype(str).str.startswith(str(clause))]
    if not c.empty and question_col:
        return str(c.iloc[0].get(question_col,""))
    return ""

def select_relevant_rows(df: pd.DataFrame, clause: str|None, lm2500_weight: Dict[str, float]|None=None) -> pd.DataFrame:
    sel = df.copy()
    clause_col = find_column(sel,"clause")
    if clause and clause_col:
        try:
            sel = sel[sel[clause_col].astype(str).str.startswith(str(clause))]
        except Exception:
            pass
    sel = sel.copy()
    if lm2500_weight:
        title_series = col_or_default(sel,"title","")
        question_series = col_or_default(sel,"question","")
        def score(idx):
            sc = 1.0
            txt = (str(title_series.iloc[idx]) + " " + str(question_series.iloc[idx])).lower()
            for key, w in lm2500_weight.items():
                if key.lower() in txt:
                    sc += w
            return sc
        if len(sel) > 0:
            sel["score"] = [score(i) for i in range(len(sel))]
            sel = sel.sort_values("score", ascending=False)
    return sel

def build_system_prompt(context_rows: pd.DataFrame, iso_version="ISO45001:2018") -> str:
    head_df = pd.DataFrame({
        "title": col_or_default(context_rows,"title","").head(12),
        "clause": col_or_default(context_rows,"clause","").head(12),
        "question": col_or_default(context_rows,"question","").head(12),
        "evidence_type": col_or_default(context_rows,"evidence_type","").head(12),
    })
    head = head_df.to_dict(orient="records")
    return (
        f"당신은 {iso_version} 내부심사 지원 AI입니다. "
        "반드시 하나의 JSON 객체를 출력합니다. 스키마: "
        '{"findings":[{"title":"...","clause":"6.1.2","reason":"...","result":"Cat.1|Cat.2|Y|N"}]} '
        "각 항목은 조항 적합성/위험/근거를 간결하게 요약하세요. "
        f"컨텍스트 예시: {json.dumps(head, ensure_ascii=False)}"
    )

def build_user_prompt(evidence_digest: str, clause_hint: str|None) -> str:
    q = f"조항 힌트: {clause_hint}" if clause_hint else "조항 힌트 없음"
    return (
        f"{q}\n"
        f"증거 요약:\n{evidence_digest}\n"
        "위 스키마를 따라 findings를 3~6개 내로 작성."
    )

def offline_baseline(context_rows: pd.DataFrame, evidence_digest: str, clause: str|None) -> Dict[str, Any]:
    title_series = col_or_default(context_rows,"title","관리검토/운영 통제")
    clause_series = col_or_default(context_rows,"clause", clause or "N/A")
    res = []
    n = min(5, len(context_rows)) if len(context_rows) else 1
    for i in range(n):
        title = str(title_series.iloc[i]) if len(context_rows) else "관리검토/운영 통제"
        cl    = str(clause_series.iloc[i]) if len(context_rows) else (clause or "N/A")
        obs   = (evidence_digest or "").lower()
        cat   = "Y"
        if any(k in obs for k in ["미흡","부족","위반","누락","중대","사고"]):
            cat = "Cat.2"
        if any(k in obs for k in ["사망","산재","화재","폭발","중대재해"]):
            cat = "Cat.1"
        res.append(Finding(title=title or "관리검토/운영 통제", clause=cl or (clause or "N/A"),
                           reason="오프라인 규칙 기반 임시 판단", result=cat).model_dump())
    return {"findings": res}

def normalize_findings_json(text_or_dict: Any) -> Dict[str, Any]:
    if isinstance(text_or_dict, dict):
        data = text_or_dict
    else:
        raw = str(text_or_dict)
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = {"findings":[]}
        else:
            data = {"findings":[]}

    f = data.get("findings", [])
    if not isinstance(f, list):
        f = [f]

    norm = []
    for item in f:
        if not isinstance(item, dict):
            item = {"title": str(item), "clause":"N/A", "reason": str(item), "result":"Y"}
        item.setdefault("title","관찰사항")
        item.setdefault("clause","N/A")
        item.setdefault("reason","보정")
        item.setdefault("result","Y")
        try:
            norm.append(Finding(**item).model_dump())
        except ValidationError:
            norm.append({"title":str(item.get("title","관찰사항")),
                         "clause":str(item.get("clause","N/A")),
                         "reason":str(item.get("reason","보정")),
                         "result":str(item.get("result","Y"))})
    return {"findings": norm}
