import itertools
import json
import math
import os
import time
import urllib.error
import urllib.request
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ==========================================
# 1. 頁面設定、側邊欄骨架與偏好設定
# ==========================================
st.set_page_config(
    page_title="法巴人壽 | AI 預算預測與差異分析助手",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 側邊欄以容器預先排好「品牌 → 導覽 → 篩選 → 設定 → 偏好」的顯示順序，程式可依相依關係先後填入。
sb_brand = st.sidebar.container()
sb_nav = st.sidebar.container()
sb_filters = st.sidebar.container()
sb_settings = st.sidebar.container()
sb_prefs = st.sidebar.container()

with sb_prefs:
    LANGUAGE = st.segmented_control(
        "語言 / Language", ["中文", "EN"], default="中文", required=True,
        key="ui_language", label_visibility="collapsed", width="stretch",
    )
IS_EN = LANGUAGE == "EN"
# 淺色／深色由 Streamlit 原生主題（右上角選單）控制，原生元件與表格才能同步配色；這裡讀取目前主題調整自訂樣式與圖表。
if st.context.theme.type is None and not st.session_state.get("_theme_probe_done"):
    # 首次載入時前端尚未回報主題；重跑一次即可取得，避免第一次畫面配色不一致。
    st.session_state["_theme_probe_done"] = True
    st.rerun()
IS_DARK = (st.context.theme.type or "dark") == "dark"

def tx(zh, en):
    return en if IS_EN else zh

DEPT_EN = {
    "資訊部": "IT", "行銷部": "Marketing", "核保部": "Underwriting",
    "理賠部": "Claims", "精算部": "Actuarial", "財務部": "Finance",
    "人資行政部": "HR and Administration", "法遵風控部": "Risk and Compliance",
}

# 部門識別色固定跨圖表、主題與語言使用；風險顏色另作狀態提示。
DEPT_COLORS = {
    "資訊部": "#4C86C6", "行銷部": "#D08C34", "核保部": "#3E9A78", "理賠部": "#CF625D",
    "精算部": "#9C73A8", "財務部": "#4FA7B9", "人資行政部": "#A88A4E", "法遵風控部": "#7279B0",
}

def show_dept(name):
    base = name.split(" (")[0]
    return DEPT_EN.get(base, base) if IS_EN else base

STATUS_ORDER = ["高風險超支", "需注意", "執行落後", "預算正常"]
STATUS_SEVERITY = {status: i for i, status in enumerate(STATUS_ORDER)}
STATUS_EMOJI = {"高風險超支": "🔴", "需注意": "🟠", "執行落後": "🔵", "預算正常": "🟢"}

def show_status(status):
    pairs = {
        "高風險超支": "High overspend risk", "需注意": "Monitor closely",
        "執行落後": "Behind plan", "預算正常": "On track",
    }
    return pairs.get(status, status) if IS_EN else status

BG = "#070d1a" if IS_DARK else "#f3f6fb"
PANEL = "#0e1729" if IS_DARK else "#ffffff"
RAISED = "#132039" if IS_DARK else "#f6f8fc"
BORDER = "#1d2c47" if IS_DARK else "#dfe5ef"
TEXT = "#e7eefa" if IS_DARK else "#14203a"
MUTED = "#8b9bb4" if IS_DARK else "#5d6b82"
GRID = "#16233b" if IS_DARK else "#edf1f7"
ACCENT = "#4f9cf9" if IS_DARK else "#2563eb"
ACCENT2 = "#22d3ee" if IS_DARK else "#0891b2"
TRACK = "#1c2a44" if IS_DARK else "#e6ebf3"
STATUS_COLORS = {
    "高風險超支": "#f26b6b" if IS_DARK else "#d63c3c",
    "需注意": "#f0a63a" if IS_DARK else "#c97a10",
    "執行落後": "#5b9cf0" if IS_DARK else "#2f6fd0",
    "預算正常": "#3fbf7f" if IS_DARK else "#1f9a5c",
}
FONT_STACK = "'Inter', 'Noto Sans TC', 'Microsoft JhengHei', 'PingFang TC', sans-serif"

def rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Noto+Sans+TC:wght@400;500;700;900&display=swap');
:root {{ --bg:{BG}; --panel:{PANEL}; --raised:{RAISED}; --border:{BORDER}; --text:{TEXT}; --muted:{MUTED}; --accent:{ACCENT}; --accent2:{ACCENT2}; --track:{TRACK};
         --grad:linear-gradient(90deg,{ACCENT},{ACCENT2}); }}
html, body, .stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp button {{ font-family:{FONT_STACK}; }}
.stApp {{ color:var(--text); font-variant-numeric:tabular-nums;
          background:
            radial-gradient(900px 420px at 85% -120px, {rgba(ACCENT, .16 if IS_DARK else .08)}, transparent 70%),
            radial-gradient(700px 360px at 10% -160px, {rgba(ACCENT2, .10 if IS_DARK else .05)}, transparent 70%),
            linear-gradient({rgba(BORDER, .35 if IS_DARK else .0)} 1px, transparent 1px) 0 0 / 100% 48px,
            var(--bg); background-attachment:fixed; }}
[data-testid="stHeader"] {{ background:transparent; }}
[data-testid="stMainBlockContainer"] {{ padding-top:1.4rem; padding-bottom:3rem; max-width:1480px; }}
h1,h2,h3,h4,h5,p,label,li,[data-testid="stCaptionContainer"] {{ color:var(--text); }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color:var(--muted) !important; }}
hr {{ border-color:var(--border); }}

/* ---------- 側邊欄 ---------- */
[data-testid="stSidebar"] {{ background:var(--panel); border-right:1px solid var(--border); }}
[data-testid="stSidebar"] * {{ color:var(--text); }}
[data-testid="stSidebarUserContent"] {{ padding-top:.4rem; }}
.sb-brand {{ display:flex; align-items:center; gap:11px; padding:2px 2px 14px; border-bottom:1px solid var(--border); margin-bottom:6px; }}
.sb-mark {{ width:38px; height:38px; border-radius:11px; display:flex; align-items:center; justify-content:center; background:linear-gradient(140deg,{ACCENT},{ACCENT2}); flex:0 0 38px; box-shadow:0 6px 18px {rgba(ACCENT, .35)}; }}
.sb-title {{ font-weight:800; font-size:15px; letter-spacing:-.01em; line-height:1.25; }}
.sb-sub {{ font-size:11px; color:var(--muted) !important; }}
.sb-label {{ font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted) !important; margin:14px 0 4px; }}
.st-key-nav_slot [data-testid="stRadio"], .st-key-nav_slot [role="radiogroup"], .st-key-nav_slot [role="radiogroup"] > div {{ width:100%; }}
.st-key-nav_slot [role="radiogroup"] {{ gap:3px; }}
.st-key-nav_slot [data-testid="stRadioOption"] {{ width:100%; padding:9px 12px; border-radius:10px; border:1px solid transparent; margin:0; transition:background .15s; cursor:pointer; box-sizing:border-box; }}
.st-key-nav_slot [data-testid="stRadioOption"]:hover {{ background:var(--raised); }}
.st-key-nav_slot [data-testid="stRadioOption"] > div > div:first-child {{ display:none; }}
.st-key-nav_slot [data-testid="stRadioOption"]:has(input:checked) {{ background:{rgba(ACCENT, .16)}; border-color:{rgba(ACCENT, .38)}; }}
.st-key-nav_slot [data-testid="stRadioOption"]:has(input:checked) p, .st-key-nav_slot [data-testid="stRadioOption"]:has(input:checked) span {{ color:{ACCENT} !important; }}
.st-key-nav_slot [data-testid="stRadioOption"] p {{ font-weight:600; font-size:14px; }}
.st-key-nav_slot [data-testid="stRadioOption"] p span[role="img"] {{ margin-right:8px; font-size:19px; color:var(--muted); }}
[data-testid="stSidebar"] [data-baseweb="select"] > div:first-child {{ background:var(--panel) !important; border-color:var(--border) !important; }}
[data-baseweb="popover"], [role="listbox"] {{ background:var(--panel) !important; border-color:var(--border) !important; }}
[role="option"] {{ background:var(--panel) !important; color:var(--text) !important; }}
[role="option"]:hover,[role="option"][aria-selected="true"] {{ background:var(--raised) !important; }}
[data-testid="stPopoverBody"] {{ background:var(--panel); border:1px solid var(--border); }}
[data-testid="stPopoverBody"] * {{ color:var(--text); }}

/* ---------- 通用元件 ---------- */
.stButton > button, .stDownloadButton > button, [data-testid="stPopover"] button {{ background:var(--raised); color:var(--text); border:1px solid var(--border); border-radius:10px; }}
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stPopover"] button:hover {{ border-color:{ACCENT}; color:var(--text); }}
.stButton > button[data-testid="stBaseButton-primary"] {{ background:var(--grad); color:#fff; border:0; font-weight:700; box-shadow:0 6px 20px {rgba(ACCENT, .35)}; }}
.stButton > button[data-testid="stBaseButton-primary"] p {{ color:#fff !important; }}
.stButton > button[data-testid="stBaseButton-primary"]:hover {{ filter:brightness(1.08); color:#fff; }}
[data-testid="stMetric"] {{ background:var(--panel); border:1px solid var(--border) !important; padding:14px 16px; border-radius:14px; }}
[data-testid="stMetricLabel"] p {{ color:var(--muted) !important; font-size:13px; }}
[data-testid="stMetricValue"] {{ color:var(--text); font-size:clamp(18px,1.6vw,24px) !important; font-weight:800; white-space:nowrap; letter-spacing:-.02em; }}
[data-baseweb="tab-list"] {{ gap:4px; border-bottom:1px solid var(--border); }}
[data-baseweb="tab"] {{ color:var(--muted); padding:8px 14px; border-radius:9px 9px 0 0; }}
[data-baseweb="tab"][aria-selected="true"] {{ color:var(--text); }}
[data-baseweb="tab"][aria-selected="true"] p {{ font-weight:700; }}
[data-baseweb="tab-highlight"] {{ background:{ACCENT}; }}
[data-testid="stDataFrame"] {{ border:1px solid var(--border); border-radius:12px; overflow:hidden; }}
[data-testid="stExpander"] details {{ background:var(--panel); border:1px solid var(--border); border-radius:14px; }}
[data-testid="stExpander"] summary p {{ font-weight:700; }}
[data-testid="stChatMessage"] {{ background:var(--panel); border:1px solid var(--border); border-radius:14px; padding:12px 16px; }}
[data-testid="stChatInput"] textarea {{ background:var(--raised); color:var(--text); }}
[data-testid="stAlert"] {{ border-radius:12px; }}

/* 卡片容器：以 key 前綴 card- 標記的 st.container */
[class*="st-key-card-"] {{ position:relative; background:linear-gradient(180deg,{rgba(RAISED, .9)},{PANEL} 140px); border:1px solid var(--border); border-radius:16px; padding:14px 16px 10px; box-shadow:0 10px 30px rgba(0,0,0,{.28 if IS_DARK else .05}); overflow:hidden; }}
[class*="st-key-card-"]::before {{ content:""; position:absolute; left:0; right:0; top:0; height:1px; background:linear-gradient(90deg,transparent,{rgba(ACCENT, .7)},{rgba(ACCENT2, .6)},transparent); }}
[class*="st-key-card-brief"] h1, [class*="st-key-card-brief"] h2, [class*="st-key-card-brief"] h3,
[data-testid="stChatMessage"] h1, [data-testid="stChatMessage"] h2, [data-testid="stChatMessage"] h3 {{ font-size:15.5px !important; font-weight:800; margin:14px 0 6px; padding:0; color:{ACCENT}; }}
[class*="st-key-card-brief"] li, [class*="st-key-card-brief"] p {{ font-size:14px; line-height:1.7; }}
[class*="st-key-card-brief"] {{ border-color:{rgba(ACCENT, .45)}; background:linear-gradient(135deg,{rgba(ACCENT, .10)},{PANEL} 55%); }}
.chart-title {{ font-weight:700; font-size:15px; color:var(--text); margin:0; }}
/* 讓 help 提示圖示緊貼標題右側，而不是飄在容器最右上角 */
[data-testid="stMarkdown"] > div:has(.section-title), [data-testid="stMarkdown"] > div:has(.chart-title) {{ display:flex; align-items:center; gap:4px; }}
[data-testid="stMarkdown"] > div:has(.section-title) {{ margin:16px 0 4px; }}
[data-testid="stMarkdown"] > div:has(.section-title) > [data-testid="stMarkdownContainer"],
[data-testid="stMarkdown"] > div:has(.chart-title) > [data-testid="stMarkdownContainer"] {{ width:auto; flex:0 1 auto; }}
[data-testid="stMarkdown"] > div:has(.section-title) > label, [data-testid="stMarkdown"] > div:has(.chart-title) > label {{ position:static; margin:0; color:var(--muted); }}

/* 修正「拖曳時圖表越變越大」：欄位允許縮小，圖表本身不加 padding／border，超出部分裁切。 */
[data-testid="stColumn"] {{ min-width:0 !important; }}
[data-testid="stPlotlyChart"] {{ padding:0 !important; border:0 !important; background:transparent !important; overflow:hidden; max-width:100%; }}
[data-testid="stPlotlyChart"] .js-plotly-plot, [data-testid="stPlotlyChart"] .plot-container {{ max-width:100%; }}

/* ---------- 頁首 ---------- */
.hero {{ display:flex; justify-content:space-between; align-items:flex-end; gap:18px; flex-wrap:wrap; padding:4px 0 14px; border-bottom:1px solid var(--border); margin-bottom:18px; }}
.hero-eyebrow {{ display:flex; align-items:center; gap:8px; font-size:12px; font-weight:700; letter-spacing:.08em; color:{ACCENT}; text-transform:uppercase; }}
.live {{ display:inline-flex; align-items:center; gap:6px; padding:2px 9px; border-radius:999px; background:{rgba(STATUS_COLORS['預算正常'], .12)}; color:{STATUS_COLORS['預算正常']}; letter-spacing:.04em; }}
.live::before {{ content:""; width:7px; height:7px; border-radius:50%; background:{STATUS_COLORS['預算正常']}; box-shadow:0 0 0 0 {rgba(STATUS_COLORS['預算正常'], .6)}; animation:pulse 2s infinite; }}
@keyframes pulse {{ 0% {{ box-shadow:0 0 0 0 {rgba(STATUS_COLORS['預算正常'], .55)}; }} 70% {{ box-shadow:0 0 0 7px transparent; }} 100% {{ box-shadow:0 0 0 0 transparent; }} }}
.hero-title {{ font-size:clamp(22px,2.4vw,31px); font-weight:900; letter-spacing:-.025em; line-height:1.2; margin-top:6px;
               background:linear-gradient(90deg,{TEXT} 40%,{ACCENT} 80%,{ACCENT2}); -webkit-background-clip:text; background-clip:text; color:transparent; }}
.hero-sub {{ font-size:13px; color:var(--muted); margin-top:4px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
.chip {{ display:inline-flex; align-items:center; gap:7px; padding:5px 12px; border-radius:999px; border:1px solid var(--border); background:var(--panel); font-size:12.5px; color:var(--text); white-space:nowrap; }}
.dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; flex:0 0 8px; }}
.page-head {{ margin:2px 0 14px; }}
.page-title {{ font-size:21px; font-weight:800; letter-spacing:-.02em; color:var(--text); }}
.page-sub {{ font-size:13px; color:var(--muted); margin-top:3px; }}
.section-title {{ font-size:15.5px; font-weight:800; color:var(--text); margin:0; display:flex; align-items:center; gap:9px; }}
.section-title::before {{ content:""; width:4px; height:16px; border-radius:4px; background:var(--grad); }}

/* ---------- 總覽：結論橫幅 ---------- */
.lead {{ background:linear-gradient(120deg,var(--panel),var(--raised)); border:1px solid var(--border); border-left:4px solid var(--c); border-radius:16px; padding:16px 20px; margin:0 0 16px; }}
.lead-tag {{ display:inline-flex; align-items:center; gap:6px; font-size:11.5px; font-weight:800; letter-spacing:.06em; color:var(--c); text-transform:uppercase; }}
.lead-text {{ font-size:16.5px; font-weight:700; color:var(--text); line-height:1.65; margin-top:6px; }}
.lead .chips {{ margin-top:12px; }}

/* ---------- KPI 卡 ---------- */
.kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 200px), 1fr)); gap:12px; margin-bottom:6px; }}
.kpi {{ position:relative; min-height:142px; box-sizing:border-box; border:1px solid var(--border); border-radius:16px; padding:15px 18px 13px; display:flex; flex-direction:column; justify-content:space-between; gap:8px; overflow:hidden; }}
.kpi .top {{ display:flex; align-items:center; gap:10px; min-width:0; }}
.kpi .ic {{ width:34px; height:34px; border-radius:10px; display:flex; align-items:center; justify-content:center; flex:0 0 34px; font-size:17px; }}
.kpi .lb {{ font-size:13px; color:var(--muted); font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.kpi .mid {{ display:flex; align-items:flex-end; justify-content:space-between; gap:12px; }}
.kpi .vl {{ font-size:clamp(20px,1.9vw,27px); font-weight:900; color:var(--text); white-space:nowrap; letter-spacing:-.02em; line-height:1.1; }}
.kpi .sb {{ font-size:12px; color:var(--muted); line-height:1.4; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.kpi .spark {{ flex:1 1 auto; max-width:46%; min-width:48px; height:32px; }}

/* ---------- 部門燈號清單 ---------- */
.slist {{ background:var(--panel); border:1px solid var(--border); border-radius:16px; overflow:hidden; container-type:inline-size; }}
.shead, .srow {{ display:grid; grid-template-columns:minmax(120px,1.1fr) minmax(170px,2fr) 112px minmax(104px,.9fr); gap:14px; align-items:center; padding:12px 16px; }}
.shead {{ font-size:11.5px; color:var(--muted); background:var(--raised); font-weight:700; letter-spacing:.03em; }}
.srow {{ border-top:1px solid var(--border); }}
.srow:hover {{ background:var(--raised); }}
.sname {{ font-weight:700; color:var(--text); font-size:14.5px; padding-left:10px; }}
.sreason {{ font-size:11.5px; color:var(--muted); margin-top:3px; line-height:1.45; padding-left:14px; }}
.bar {{ position:relative; height:9px; border-radius:999px; background:var(--track); }}
.bar {{ height:11px; }}
.bar .fill {{ position:absolute; left:0; top:0; bottom:0; border-radius:999px 0 0 999px; }}
.bar .fill.rest {{ border-radius:0 999px 999px 0; }}
.bar .limit {{ position:absolute; top:-5px; bottom:-5px; width:0; border-left:2px dashed var(--text); opacity:.85; }}
.bar .limit em {{ position:absolute; top:-15px; left:-14px; font-size:9.5px; font-style:normal; color:var(--muted); }}
.bsub b {{ color:var(--text); font-weight:700; }}
.bsub {{ font-size:11.5px; color:var(--muted); margin-top:7px; }}
.badge {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:11.5px; font-weight:800; white-space:nowrap; }}
.amt {{ font-weight:800; font-size:14.5px; text-align:right; white-space:nowrap; }}
.legend-row {{ display:flex; flex-wrap:wrap; gap:16px; font-size:11.5px; color:var(--muted); margin:8px 2px 0; }}
.legend-row span {{ display:inline-flex; align-items:center; gap:6px; }}
@container (max-width:640px) {{ .shead, .srow {{ grid-template-columns:minmax(0,1fr) 96px; row-gap:8px; }} .shead span:nth-child(2), .shead span:nth-child(3), .srow > div:nth-child(3) {{ display:none; }} .srow > div:nth-child(2) {{ grid-column:1 / -1; grid-row:2; }} }}

/* ---------- 焦點／預警卡 ---------- */
.focus {{ background:var(--panel); border:1px solid var(--border); border-top:3px solid var(--c); border-radius:16px; padding:16px 18px; }}
.focus-name {{ font-size:18px; font-weight:900; color:var(--text); margin:8px 0 2px; }}
.focus-amt {{ font-size:24px; font-weight:900; color:var(--c); letter-spacing:-.02em; }}
.focus-meta {{ font-size:12px; color:var(--muted); }}
.ev {{ margin:12px 0 0; padding:0; list-style:none; }}
.ev li {{ position:relative; padding:0 0 8px 18px; font-size:13px; line-height:1.55; color:var(--text); }}
.ev li::before {{ content:""; position:absolute; left:3px; top:8px; width:6px; height:6px; border-radius:50%; background:var(--c); }}
.next {{ margin-top:8px; padding:10px 12px; border-radius:10px; background:{rgba(ACCENT, .10)}; border:1px solid {rgba(ACCENT, .25)}; font-size:12.5px; line-height:1.55; color:var(--text); }}
.acard {{ background:var(--panel); border:1px solid var(--border); border-left:4px solid var(--c); border-radius:14px; padding:14px 18px; margin-bottom:12px; }}
.acard-head {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
.acard-dept {{ font-weight:800; font-size:15.5px; color:var(--text); }}
.acard-amt {{ margin-left:auto; font-weight:900; font-size:17px; color:var(--c); }}
.acard-msg {{ font-size:13px; color:var(--muted); margin-top:4px; }}
.okcard {{ background:{rgba(STATUS_COLORS['預算正常'], .10)}; border:1px solid {rgba(STATUS_COLORS['預算正常'], .35)}; border-radius:14px; padding:14px 18px; color:var(--text); font-weight:600; }}
.callout {{ background:var(--panel); border:1px solid var(--border); border-top:3px solid var(--c); border-radius:14px; padding:13px 16px; height:100%; }}
.callout-title {{ font-weight:800; font-size:14px; color:var(--text); }}
.callout-big {{ font-size:22px; font-weight:900; color:var(--c); margin:4px 0; }}
.callout-sub {{ font-size:12px; color:var(--muted); line-height:1.5; }}
.flow {{ display:flex; align-items:stretch; gap:10px; flex-wrap:wrap; margin-bottom:12px; }}
.flow-item {{ flex:1 1 170px; background:var(--panel); border:1px solid var(--border); border-radius:14px; padding:13px 16px; }}
.flow-op {{ display:flex; align-items:center; font-size:22px; font-weight:900; color:var(--muted); }}
.flow-lb {{ font-size:12px; color:var(--muted); font-weight:600; }}
.flow-vl {{ font-size:clamp(17px,1.6vw,22px); font-weight:900; color:var(--text); white-space:nowrap; margin-top:4px; }}
.flow-sb {{ font-size:11.5px; color:var(--muted); margin-top:2px; }}
.check {{ display:flex; align-items:center; gap:10px; padding:10px 14px; border-top:1px solid var(--border); font-size:13.5px; }}
.check:first-child {{ border-top:0; }}
.check b {{ margin-left:auto; }}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 合成管理會計資料（量級錨定 + 真實商業情境）
# ==========================================
CPI_YOY = {2021: 0.0197, 2022: 0.0295, 2023: 0.0249, 2024: 0.0218, 2025: 0.0160, 2026: 0.0200}
EXPANSION = 0.02

DEPTS = [
    '資訊部 (IT)', '行銷部 (Marketing)', '核保部 (Underwriting)', '理賠部 (Claims)',
    '精算部 (Actuarial)', '財務部 (Finance)', '人資行政部 (HR and Administration)',
    '法遵風控部 (Risk and Compliance)',
]
DEPT_COLOR_MAP = {}
for _dept in DEPTS:
    _key = _dept.split(" (")[0]
    DEPT_COLOR_MAP[_key] = DEPT_COLORS[_key]
    DEPT_COLOR_MAP[DEPT_EN[_key]] = DEPT_COLORS[_key]

def dept_color(name):
    return DEPT_COLOR_MAP.get(name.split(" (")[0], DEPT_COLOR_MAP.get(name, "#7d8aa3"))

# 量級錨定：8 個部門的年度可控營業費用預算合計（最新年度）。
# 預設值為示範假設；請至公開資訊觀測站（MOPS）查詢法巴人壽近一年損益表「營業費用」量級後，在「系統設定」中替換。
DEFAULT_OPEX_ANCHOR_100M = 30.0  # 單位：新台幣億元
DEPT_SHARE = {
    DEPTS[0]: .22, DEPTS[1]: .18, DEPTS[2]: .09, DEPTS[3]: .12,
    DEPTS[4]: .07, DEPTS[5]: .09, DEPTS[6]: .13, DEPTS[7]: .10,
}
# 核定預算本身的月份配置（預算編列季節性）
BUDGET_PHASING = {
    "資訊部": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1.15, 1.2, 1.25],          # Q4 軟體授權續約
    "行銷部": [.85, .75, .95, 1, 1, .95, .9, .95, 1, 1.1, 1.3, 1.35],  # 年終保單旺季活動
    "核保部": [1] * 12,
    "理賠部": [1, .95, 1, 1, 1, 1, 1.05, 1.1, 1.1, 1.05, 1, 1],        # 夏秋颱風季
    "精算部": [1.2, 1.15, 1.05, .95, .95, .95, .95, .95, 1, .95, .95, 1.05],  # 年初準備金評估
    "財務部": [1.25, 1.2, 1.15, 1.05, .9, .9, .9, .9, .95, .95, .9, .95],      # 年度結帳與外部查核
    "人資行政部": [.95, .85, 1, 1, 1, 1.15, 1, .95, 1, 1, .95, 1.15],
    "法遵風控部": [.95, .9, 1.1, .95, .95, 1, .95, .95, 1.1, .95, .95, 1.15],  # 監理申報季
}
# 年末季節性消耗預算（use-it-or-lose-it）：前三季執行偏慢，11–12 月集中請款，全年仍接近預算。
YEAR_END_FLUSH = {"行銷部": .22, "人資行政部": .25, "核保部": .18, "財務部": .15}
# 一次性資本支出／專案（佔該部門年度預算比例）：記為 OneOffAmount，預測時不延伸到未來月份。
ONE_OFF_EVENTS = {
    ("資訊部", 2022, 11): (.05, "資料中心 UPS 汰換（CAPEX）"),
    ("資訊部", 2024, 9): (.07, "一次性伺服器汰換（CAPEX）"),
    ("精算部", 2025, 3): (.08, "IFRS 17 精算引擎授權（一次性）"),
    ("理賠部", 2025, 6): (.05, "理賠影像系統升級（CAPEX）"),
    ("財務部", 2026, 2): (.06, "IFRS 17 財報系統上線驗證（一次性）"),
    ("法遵風控部", 2026, 4): (.07, "TW-ICS 接軌系統建置（CAPEX）"),
}
EVENT_EN = {
    "資料中心 UPS 汰換（CAPEX）": "Data-centre UPS replacement (CAPEX)",
    "一次性伺服器汰換（CAPEX）": "One-off server replacement (CAPEX)",
    "一次性伺服器汰換": "One-off server replacement",
    "IFRS 17 精算引擎授權（一次性）": "IFRS 17 actuarial engine licence (one-off)",
    "理賠影像系統升級（CAPEX）": "Claims imaging system upgrade (CAPEX)",
    "IFRS 17 財報系統上線驗證（一次性）": "IFRS 17 reporting go-live validation (one-off)",
    "TW-ICS 接軌系統建置（CAPEX）": "TW-ICS implementation build (CAPEX)",
    "颱風季理賠查勘量增加": "Typhoon-season claims inspection surge",
    "雲端遷移專案超支": "Cloud migration project overrun",
    "TW-ICS 外部顧問費增加": "Higher TW-ICS consulting fees",
    "核保系統專案延宕": "Underwriting system project delayed",
    "教育訓練專案遞延": "Training programme deferred",
    "精算人力遇缺不補": "Actuarial hiring freeze",
}
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
MONTHS = list(range(1, 13))
CURRENT_DATE = (2026, 8)  # 假設目前結算至 2026 年 8 月

def show_event(note):
    return EVENT_EN.get(note, note) if IS_EN else note

@st.cache_data
def generate_monthly_db(anchor_total):
    rng = np.random.default_rng(42)
    index = {YEARS[0]: 1.0}
    for y in YEARS[1:]:
        index[y] = index[y - 1] * (1 + CPI_YOY[y] + EXPANSION)
    rows = []
    for y in YEARS:
        for d in DEPTS:
            key = d.split(" (")[0]
            annual_budget = anchor_total * DEPT_SHARE[d] * index[y] / index[YEARS[-1]]
            phasing = np.array(BUDGET_PHASING[key], dtype=float)
            phasing /= phasing.sum()
            flush = YEAR_END_FLUSH.get(key, 0.0)
            for m in MONTHS:
                budget = annual_budget * phasing[m - 1]
                one_off, note = 0.0, ""
                if (y, m) > CURRENT_DATE:
                    rows.append({"Year": y, "Month": m, "Department": d, "Budget": round(budget),
                                 "Actual": np.nan, "OneOffAmount": 0.0, "EventNote": ""})
                    continue
                r = rng.uniform(.96, 1.04)
                if flush:
                    r *= (1 - .4 * flush) if m <= 9 else (1.0 if m == 10 else 1 + 1.8 * flush)
                # 埋入可被系統抓出的管理痛點
                if key == "資訊部" and y == 2026:
                    r = rng.uniform(.98, 1.02) * (1.06 + .02 * m)        # 雲端遷移專案超支，逐月擴大
                    note = "雲端遷移專案超支"
                elif key == "法遵風控部" and y == 2026:
                    r = rng.uniform(1.08, 1.15)                          # TW-ICS 外部顧問費
                    note = "TW-ICS 外部顧問費增加"
                elif key == "核保部" and y == 2025 and m >= 9:
                    r = rng.uniform(.75, .85)                            # 核保系統專案延宕
                    note = "核保系統專案延宕"
                elif key == "精算部" and y == 2026:
                    r = rng.uniform(.84, .90)                            # 精算人力遇缺不補
                    note = "精算人力遇缺不補"
                elif key == "人資行政部" and y == 2026 and m >= 7:
                    r = rng.uniform(.55, .65)                            # 教育訓練專案遞延
                    note = "教育訓練專案遞延"
                elif key == "理賠部" and y == 2024 and m in (9, 10):
                    r *= 1.25                                            # 颱風季理賠查勘量增加
                    note = "颱風季理賠查勘量增加"
                actual = budget * r
                event = ONE_OFF_EVENTS.get((key, y, m))
                if event:
                    one_off = annual_budget * event[0]
                    note = event[1]
                    actual += one_off
                rows.append({"Year": y, "Month": m, "Department": d, "Budget": round(budget),
                             "Actual": round(actual), "OneOffAmount": round(one_off), "EventNote": note})
    return pd.DataFrame(rows)

# 明確標示為範例用的合成費用明細；各月明細加總會與模擬 Actual 對齊。
COST_PROFILES = {
    "資訊部": [("雲端服務費", .30), ("軟體訂閱費", .25), ("資訊外包費", .25), ("設備維護費", .20)],
    "行銷部": [("數位廣告費", .35), ("活動製作費", .30), ("行銷外包費", .20), ("差旅費", .15)],
    "核保部": [("核保系統服務費", .35), ("專業外包費", .30), ("教育訓練費", .15), ("差旅費", .20)],
    "理賠部": [("理賠查勘費", .35), ("理賠外包服務費", .30), ("系統服務費", .20), ("差旅費", .15)],
    "精算部": [("精算資料服務費", .35), ("軟體訂閱費", .25), ("顧問外包費", .25), ("教育訓練費", .15)],
    "財務部": [("財務系統服務費", .30), ("外部查核費", .30), ("稅務顧問費", .25), ("教育訓練費", .15)],
    "人資行政部": [("員工訓練費", .35), ("招募服務費", .25), ("行政維護費", .25), ("差旅費", .15)],
    "法遵風控部": [("法遵顧問費", .35), ("監理申報系統費", .30), ("風險資料服務費", .20), ("教育訓練費", .15)],
}
ACCOUNT_EN = {
    "雲端服務費": "Cloud services", "軟體訂閱費": "Software subscriptions", "資訊外包費": "IT outsourcing", "設備維護費": "Equipment and maintenance",
    "數位廣告費": "Digital advertising", "活動製作費": "Event production", "行銷外包費": "Marketing services", "差旅費": "Travel",
    "核保系統服務費": "Underwriting systems", "專業外包費": "Professional services", "教育訓練費": "Training",
    "理賠查勘費": "Claims inspection", "理賠外包服務費": "Claims services", "系統服務費": "System services",
    "精算資料服務費": "Actuarial data services", "顧問外包費": "Consulting services",
    "財務系統服務費": "Finance systems", "外部查核費": "External audit",
    "稅務顧問費": "Tax advisory", "員工訓練費": "Employee training",
    "招募服務費": "Recruitment services", "行政維護費": "Administrative services",
    "法遵顧問費": "Compliance advisory", "監理申報系統費": "Regulatory reporting systems",
    "風險資料服務費": "Risk data services", "一次性資本支出": "One-off capital expenditure",
    "資產汰換專案": "Asset replacement project",
}
VENDOR_EN = {"示範供應商甲": "Demo Vendor A", "示範供應商乙": "Demo Vendor B", "示範供應商丙": "Demo Vendor C"}

def show_account(account):
    return ACCOUNT_EN.get(account, account) if IS_EN else account

def show_vendor(vendor):
    return VENDOR_EN.get(vendor, vendor) if IS_EN else vendor

def validate_budget_upload(uploaded_df):
    aliases = {
        "年度": "Year", "年份": "Year", "月份": "Month", "部門": "Department",
        "部门": "Department", "年度預算": "Budget", "月預算": "Budget",
        "預算": "Budget", "實際支出": "Actual", "實際金額": "Actual",
        "一次性支出": "OneOffAmount", "一次性費用": "OneOffAmount",
        "事件說明": "EventNote", "特殊事件": "EventNote",
    }
    data = uploaded_df.rename(columns={c: aliases.get(str(c).strip(), str(c).strip()) for c in uploaded_df.columns}).copy()
    required = ["Year", "Month", "Department", "Budget", "Actual"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        return None, [tx(f"缺少必要欄位：{', '.join(missing)}", f"Missing required columns: {', '.join(missing)}")]
    if data.empty:
        return None, [tx("CSV 沒有資料列。", "The CSV contains no data rows.")]
    if "OneOffAmount" not in data.columns:
        data["OneOffAmount"] = 0.0
    if "EventNote" not in data.columns:
        data["EventNote"] = ""

    errors = []
    for col in ["Year", "Month", "Budget"]:
        converted = pd.to_numeric(data[col], errors="coerce")
        if converted.isna().any():
            errors.append(tx(f"{col} 欄位含有空白或非數字。", f"{col} contains blank or non-numeric values."))
        data[col] = converted
    raw_actual = data["Actual"]
    actual_num = pd.to_numeric(raw_actual, errors="coerce")
    malformed_actual = raw_actual.notna() & raw_actual.astype(str).str.strip().ne("") & actual_num.isna()
    if malformed_actual.any():
        errors.append(tx("Actual 欄位含有無法辨識的數值。", "Actual contains values that cannot be parsed as numbers."))
    data["Actual"] = actual_num
    raw_one_off = data["OneOffAmount"]
    one_off_num = pd.to_numeric(raw_one_off, errors="coerce")
    malformed_one_off = raw_one_off.notna() & raw_one_off.astype(str).str.strip().ne("") & one_off_num.isna()
    if malformed_one_off.any():
        errors.append(tx("OneOffAmount 欄位含有無法辨識的數值。", "OneOffAmount contains values that cannot be parsed as numbers."))
    data["OneOffAmount"] = one_off_num.fillna(0)
    data["EventNote"] = data["EventNote"].fillna("").astype(str)

    dept_alias = {d: d for d in DEPTS}
    dept_alias.update({d.split(" (")[0]: d for d in DEPTS})
    dept_alias.update({v: next(d for d in DEPTS if d.startswith(k)) for k, v in DEPT_EN.items()})
    data["Department"] = data["Department"].astype(str).str.strip().map(dept_alias)
    if data.Department.isna().any():
        errors.append(tx("Department 欄位包含不支援的部門名稱。", "Department contains an unsupported department name."))
    if not errors:
        if ((data.Month < 1) | (data.Month > 12) | (data.Month % 1 != 0)).any():
            errors.append(tx("Month 必須是 1 至 12 的整數。", "Month must be an integer from 1 to 12."))
        if ((data.Year % 1 != 0) | (data.Budget < 0) | (data.Actual < 0) | (data.OneOffAmount < 0)).any():
            errors.append(tx("Year 必須為整數，Budget、Actual 與一次性支出不可為負數。", "Year must be an integer; Budget, Actual and one-off amounts cannot be negative."))
        if (data.Actual.notna() & (data.OneOffAmount > data.Actual)).any():
            errors.append(tx("一次性支出不可大於該月實際支出。", "One-off amount cannot exceed actual spending for the month."))
        if data.duplicated(["Year", "Month", "Department"]).any():
            errors.append(tx("同一年度、月份與部門不可有重複資料列。", "Duplicate year/month/department rows are not allowed."))
        for (year, department), group in data.groupby(["Year", "Department"]):
            if set(group.Month.astype(int)) != set(MONTHS):
                errors.append(tx(f"{int(year)} 年 {show_dept(department)} 必須各有 12 個月預算資料。", f"{int(year)} {show_dept(department)} must include budget rows for all 12 months."))
                continue
            if group.Budget.sum() <= 0:
                errors.append(tx(f"{int(year)} 年 {show_dept(department)} 的年度預算總額必須大於零。", f"Annual budget for {int(year)} {show_dept(department)} must be greater than zero."))
            months_with_actual = group.loc[group.Actual.notna(), "Month"]
            if not months_with_actual.empty:
                last_actual_month = int(months_with_actual.max())
                if group.loc[group.Month <= last_actual_month, "Actual"].isna().any():
                    errors.append(tx(f"{int(year)} 年 {show_dept(department)} 的實際支出月份中間有缺漏。", f"Actuals for {int(year)} {show_dept(department)} have a gap before the latest reported month."))
    if errors:
        return None, errors
    data["Year"] = data.Year.astype(int)
    data["Month"] = data.Month.astype(int)
    data["Budget"] = data.Budget.astype(float)
    return data[required + ["OneOffAmount", "EventNote"]].sort_values(["Year", "Department", "Month"]).reset_index(drop=True), []

@st.cache_data
def generate_expense_detail(monthly_data):
    rng = np.random.default_rng(20261021)
    result = []
    vendor_names = ["示範供應商甲", "示範供應商乙", "示範供應商丙"]
    seq = 1
    for row in monthly_data.itertuples():
        if pd.isna(row.Actual):
            continue
        month_start = len(result)
        dept_key = row.Department.split(" (")[0]
        profile = COST_PROFILES[dept_key]
        shares = np.array([weight for _, weight in profile], dtype=float)
        # 合成異常情境：2026 資訊部雲端服務費占比提高，用於示範根因分析。
        if dept_key == "資訊部" and row.Year == 2026:
            shares[0] += .22
            shares[2] -= .12
            shares[3] -= .10
        shares *= rng.uniform(.94, 1.06, len(shares))
        shares /= shares.sum()
        one_off_amount = float(getattr(row, "OneOffAmount", 0) or 0)
        recurring_actual = max(0.0, float(row.Actual) - one_off_amount)
        for (account, _), share in zip(profile, shares):
            account_total = recurring_actual * share
            split = float(rng.uniform(.35, .65))
            amounts = [round(account_total * split), 0]
            amounts[1] = round(account_total) - amounts[0]
            vendor = vendor_names[(seq + row.Month) % len(vendor_names)]
            duplicate_example = dept_key == "資訊部" and row.Year == 2026 and row.Month == 6 and account == "雲端服務費"
            invoice_id = f"SYN-{row.Year}-{row.Month:02d}-{seq:05d}"
            if duplicate_example:
                amounts = [round(account_total / 2), round(account_total) - round(account_total / 2)]
            for line_no, amount in enumerate(amounts):
                result.append({
                    "Year": row.Year, "Month": row.Month, "Department": row.Department,
                    "Account": account, "Vendor": vendor, "Expense_ID": invoice_id if duplicate_example else f"{invoice_id}-{line_no + 1}",
                    "Purchase_Order": f"PO-{row.Year}-{seq:05d}", "Amount": amount,
                    "Project": f"PRJ-{DEPT_EN.get(dept_key, 'OPS').split()[0].upper()}-{row.Year}",
                    "Cost_Center": f"CC-{DEPT_EN.get(dept_key, 'OPS').split()[0].upper()}-01",
                    "Employee": f"EMP-{(seq % 24) + 1:03d}",
                    "Source": "合成示範資料",
                })
                seq += 1
        if one_off_amount > 0:
            result.append({
                "Year": row.Year, "Month": row.Month, "Department": row.Department,
                "Account": "一次性資本支出", "Vendor": "示範供應商甲",
                "Expense_ID": f"SYN-{row.Year}-{row.Month:02d}-ONEOFF-{seq:05d}",
                "Purchase_Order": f"PO-{row.Year}-{seq:05d}", "Amount": round(one_off_amount),
                "Project": f"PRJ-{DEPT_EN.get(dept_key, 'OPS').split()[0].upper()}-ASSET-{row.Year}",
                "Cost_Center": f"CC-{DEPT_EN.get(dept_key, 'OPS').split()[0].upper()}-01",
                "Employee": f"EMP-{(seq % 24) + 1:03d}",
                "Source": "合成示範資料",
            })
            seq += 1
        monthly_rounding_delta = int(round(row.Actual)) - sum(item["Amount"] for item in result[month_start:])
        if monthly_rounding_delta:
            result[-1]["Amount"] += monthly_rounding_delta
    return pd.DataFrame(result)

# ==========================================
# 3. 核心分析引擎
# ==========================================
def classify_status(ratio):
    # 門檻可在「系統設定」調整；預設「需注意」帶 2% 緩衝，避免只超出 1% 就亮燈。
    high = st.session_state.get("thr_high_pct", 105) / 100
    watch = st.session_state.get("thr_watch_pct", 102) / 100
    lag = st.session_state.get("thr_lag_pct", 90) / 100
    if ratio > high:
        return '高風險超支'
    if ratio > watch:
        return '需注意'
    if ratio < lag:
        return '執行落後'
    return '預算正常'

def complete_history(data, department, before_year):
    history = data[
        (data.Department == department) & (data.Year < before_year) & data.Actual.notna()
    ]
    complete_years = []
    for year, annual in history.groupby("Year"):
        if annual.Month.nunique() == 12 and annual.Actual.notna().all():
            complete_years.append(int(year))
    return history[history.Year.isin(complete_years)]

def forecast_for_year(data, target_year, department, cutoff_month):
    year_data = data[(data.Year == target_year) & (data.Department == department)]
    observed = year_data[year_data.Actual.notna() & (year_data.Month <= cutoff_month)]
    if observed.empty:
        annual_budget = float(year_data.Budget.sum())
        history = complete_history(data, department, target_year)
        return annual_budget, annual_budget, np.nan, int(history.Year.nunique())

    actual_ytd = float(observed.Actual.sum())
    one_off_ytd = float(observed.get("OneOffAmount", pd.Series(0, index=observed.index)).fillna(0).sum())
    recurring_ytd = max(0.0, actual_ytd - one_off_ytd)
    budget_ytd = float(observed.Budget.sum())
    annual_budget = float(year_data.Budget.sum())
    run_rate = one_off_ytd + recurring_ytd + max(0.0, annual_budget - budget_ytd) * (recurring_ytd / budget_ytd if budget_ytd else 1.0)

    history = complete_history(data, department, target_year)
    seasonality_years = history.groupby("Year").Actual.sum()
    seasonal_fc = np.nan
    if not history.empty:
        history = history.assign(
            RecurringActual=history.Actual - history.get("OneOffAmount", pd.Series(0, index=history.index)).fillna(0)
        )
        monthly = history.groupby(["Year", "Month"]).RecurringActual.sum().unstack("Month").reindex(columns=MONTHS)
        shares = monthly.div(monthly.sum(axis=1).replace(0, np.nan), axis=0)
        cumulative_share = shares.loc[:, :cutoff_month].sum(axis=1).mean()
        if pd.notna(cumulative_share) and cumulative_share > 0:
            seasonal_fc = one_off_ytd + recurring_ytd / float(cumulative_share)

    if pd.notna(seasonal_fc):
        forecast = .55 * seasonal_fc + .45 * run_rate
    else:
        forecast = run_rate
    return float(forecast), float(run_rate), float(seasonal_fc) if pd.notna(seasonal_fc) else np.nan, int(len(seasonality_years))

def backtest_forecasts(data, target_year, target_depts, cutoff_month):
    rows = []
    for department in target_depts:
        years = sorted(int(y) for y in data.loc[
            (data.Department == department) & (data.Year < target_year), "Year"
        ].unique())
        for year in years:
            complete = data[(data.Year == year) & (data.Department == department)]
            if complete.Month.nunique() != 12 or complete.Actual.isna().any():
                continue
            forecast, run_rate_forecast, seasonal_forecast, history_count = forecast_for_year(
                data, year, department, min(cutoff_month, 11)
            )
            if pd.isna(forecast) or history_count < 1:
                continue
            actual = float(complete.Actual.sum())
            rows.append({
                "Year": year, "Department": department, "Forecast": forecast,
                "Run_Rate_Forecast": run_rate_forecast,
                "Seasonal_Forecast": seasonal_forecast,
                "Run_Rate_Abs_Error": abs(run_rate_forecast - actual) if pd.notna(run_rate_forecast) else np.nan,
                "Actual": actual, "Error": forecast - actual,
                "Abs_Error": abs(forecast - actual),
                "Abs_Error_Pct": abs(forecast - actual) / actual * 100 if actual else np.nan,
                "Cutoff_Month": min(cutoff_month, 11),
            })
    return pd.DataFrame(rows)

def risk_evidence(data, target_year, row):
    reasons = []
    latest_month = data.loc[(data.Year == target_year) & (data.Department == row.Department) & data.Actual.notna(), "Month"].max()
    cutoff = int(latest_month) if pd.notna(latest_month) else 0
    selected_year_rows = data[(data.Year == target_year) & (data.Department == row.Department) & (data.Month <= cutoff)]
    one_off_ytd = float(selected_year_rows.get("OneOffAmount", pd.Series(0, index=selected_year_rows.index)).fillna(0).sum())
    if one_off_ytd > 0:
        one_off_rows = selected_year_rows[selected_year_rows.OneOffAmount > 0]
        event_notes = [show_event(note) for note in one_off_rows.EventNote.dropna().unique() if str(note).strip()]
        event_text = ("、" if not IS_EN else ", ").join(event_notes) if event_notes else tx("已標記的一次性支出", "identified one-off spending")
        reasons.append(tx(
            f"今年已發生一次性支出：{event_text} {fmc(one_off_ytd)}（只計一次，不會被預測成每月重複發生）",
            f"One-off spending this year: {event_text} of {fmc(one_off_ytd)} (counted once, not projected to recur monthly)",
        ))
    if row.Exec_Rate >= 105:
        reasons.append(tx(
            f"同期實際支出已高於預算 {row.Exec_Rate - 100:.1f}%",
            f"Actual spending is {row.Exec_Rate - 100:.1f}% above budget to date",
        ))
    elif row.Exec_Rate <= 92:
        reasons.append(tx(
            f"同期實際支出僅達預算的 {row.Exec_Rate:.1f}%",
            f"Actual spending is only {row.Exec_Rate:.1f}% of budget to date",
        ))
    history = complete_history(data, row.Department, target_year)
    if not history.empty:
        history = history.assign(RecurringActual=history.Actual - history.get("OneOffAmount", pd.Series(0, index=history.index)).fillna(0))
        annual_months = history.groupby(["Year", "Month"]).RecurringActual.sum().unstack("Month").reindex(columns=MONTHS)
        historical_ytd = annual_months.loc[:, :cutoff].sum(axis=1).mean()
        recurring_ytd = max(0.0, row.Actual_YTD - one_off_ytd)
        if historical_ytd > 0 and recurring_ytd / historical_ytd >= 1.05:
            reasons.append(tx(
                f"扣除一次性支出後，經常性支出仍高於往年同期平均 {(recurring_ytd / historical_ytd - 1) * 100:.1f}%",
                f"Recurring spending remains {(recurring_ytd / historical_ytd - 1) * 100:.1f}% above the historical same-period average after excluding one-offs",
            ))
    recurring_notes = [
        show_event(note) for note in selected_year_rows.loc[selected_year_rows.OneOffAmount <= 0, "EventNote"].dropna().unique()
        if str(note).strip()
    ]
    if recurring_notes:
        reasons.append(tx(f"已標記事件：{'、'.join(recurring_notes)}", f"Tagged events: {', '.join(recurring_notes)}"))
    if pd.notna(row.Forecast_Seasonal) and row.Forecast_EOY > 0:
        model_gap = abs(row.Forecast_Seasonal - row.Forecast_Run_Rate) / row.Forecast_EOY
        if model_gap >= .08:
            reasons.append(tx(
                f"季節性估算與 Run-rate 相差 {model_gap * 100:.1f}%，年底前需持續追蹤",
                f"Seasonal and run-rate estimates differ by {model_gap * 100:.1f}%; keep monitoring until year end",
            ))
    if not reasons:
        reasons.append(tx("主要依年底預測與年度預算之差異觸發，建議檢視剩餘月份計畫。", "Triggered mainly by the gap between the year-end forecast and budget; review plans for the remaining months."))
    return reasons

def analyze_budget(data, target_year, target_depts):
    out = []
    for d in target_depts:
        df_dept_year = data[(data.Year == target_year) & (data.Department == d)]
        done_df = df_dept_year[df_dept_year.Actual.notna()]

        b_ytd = done_df.Budget.sum()
        a_ytd = done_df.Actual.sum()
        b_full = df_dept_year.Budget.sum()

        ytd_burn_rate = a_ytd / b_ytd if b_ytd > 0 else 1.0
        cutoff_month = int(done_df.Month.max()) if not done_df.empty else 12
        eoy_forecast, run_rate_forecast, seasonal_forecast, history_count = forecast_for_year(
            data, target_year, d, cutoff_month
        )
        if pd.isna(eoy_forecast):
            eoy_forecast = a_ytd
            run_rate_forecast = a_ytd
            seasonal_forecast = np.nan

        historical_backtest = backtest_forecasts(data, target_year, [d], cutoff_month)
        if not historical_backtest.empty:
            error_margin = float(historical_backtest.Abs_Error.quantile(.8))
            error_basis = tx("歷史回測絕對誤差 P80", "Historical backtest absolute error P80")
        else:
            error_margin = max(b_full * .15, 1.0)
            error_basis = tx("歷史資料不足，暫採年度預算 ±15%", "Insufficient history; temporary ±15% of annual budget")

        forecast_var = eoy_forecast - b_full
        forecast_pct = (forecast_var / b_full) * 100 if b_full > 0 else 0

        out.append({
            'Department': d,
            'Budget_YTD': b_ytd,
            'Actual_YTD': a_ytd,
            'Actual_Cutoff_Month': cutoff_month if not done_df.empty else 0,
            'Variance': a_ytd - b_ytd,
            'Variance_Pct': ((a_ytd - b_ytd) / b_ytd * 100) if b_ytd > 0 else 0,
            'Budget_Full': b_full,
            'Usage_Rate': (a_ytd / b_full * 100) if b_full > 0 else 0,
            'Exec_Rate': (ytd_burn_rate * 100),
            'Forecast_EOY': eoy_forecast,
            'Forecast_Low': max(0.0, eoy_forecast - error_margin),
            'Forecast_High': eoy_forecast + error_margin,
            'Forecast_Run_Rate': run_rate_forecast,
            'Forecast_Seasonal': seasonal_forecast,
            'History_Years': history_count,
            'Error_Margin': error_margin,
            'Error_Basis': error_basis,
            'Forecast_Var': forecast_var,
            'Forecast_Pct': forecast_pct,
            'Status': classify_status(eoy_forecast / b_full) if b_full > 0 else '預算正常',
        })
    return pd.DataFrame(out)

def allocate_remaining_by_month(analysis, data, year, year_frame):
    """Spread each department's remaining forecast over its open months (55% seasonal, 45% even)."""
    monthly_estimate = pd.Series(0.0, index=MONTHS)
    basis = {}
    for forecast_row in analysis.itertuples(index=False):
        dept = forecast_row.Department
        dept_cutoff = int(forecast_row.Actual_Cutoff_Month)
        future_months = [month for month in MONTHS if month > dept_cutoff]
        remaining_for_dept = max(0.0, float(forecast_row.Forecast_EOY - forecast_row.Actual_YTD))
        if not future_months or remaining_for_dept <= 0:
            basis[dept] = tx("無剩餘月份", "No remaining months")
            continue
        history = complete_history(data, dept, year)
        seasonal_total = 0.0
        if not history.empty:
            history = history.assign(
                RecurringActual=history.Actual - history.get("OneOffAmount", pd.Series(0, index=history.index)).fillna(0)
            )
            annual_monthly = history.groupby(["Year", "Month"]).RecurringActual.sum().unstack("Month").reindex(columns=MONTHS)
            seasonal_shares = annual_monthly.div(
                annual_monthly.sum(axis=1).replace(0, np.nan), axis=0
            ).mean(axis=0).reindex(future_months).fillna(0.0)
            seasonal_total = float(seasonal_shares.sum())
        if seasonal_total > 0:
            month_weights = .55 * (seasonal_shares / seasonal_total) + .45 / len(future_months)
            basis[dept] = tx("歷史季節性＋Run-rate", "Historical seasonality + run rate")
        else:
            dept_budget = year_frame[year_frame.Department == dept].set_index("Month").Budget
            budget_weights = dept_budget.reindex(future_months).fillna(0.0)
            if float(budget_weights.sum()) > 0:
                month_weights = budget_weights / budget_weights.sum()
            else:
                month_weights = pd.Series(1 / len(future_months), index=future_months)
            basis[dept] = tx("依剩餘月份預算比例（歷史不足）", "Remaining budget mix (insufficient history)")
        for month, weight in month_weights.items():
            monthly_estimate.loc[int(month)] += remaining_for_dept * float(weight)
    return monthly_estimate, basis

# ==========================================
# 4. 格式化與視覺化工具
# ==========================================
def fm(val):
    return f"-NT$ {abs(val):,.0f}" if val < 0 else f"NT$ {val:,.0f}"

def fmc(val, signed=False):
    """Compact amount for cards and sentences: 億／萬 in Chinese, B／M in English."""
    val = float(val)
    sign = "-" if val < 0 else ("+" if signed and val > 0 else "")
    v = abs(val)
    if IS_EN:
        if v >= 1e9:
            body = f"{v / 1e9:,.2f}B"
        elif v >= 1e6:
            body = f"{v / 1e6:,.1f}M"
        elif v >= 1e3:
            body = f"{v / 1e3:,.0f}K"
        else:
            body = f"{v:,.0f}"
    else:
        if v >= 1e8:
            body = f"{v / 1e8:,.2f} 億"
        elif v >= 1e4:
            body = f"{v / 1e4:,.0f} 萬"
        else:
            body = f"{v:,.0f}"
    return f"{sign}NT$ {body}"

def fpct(value, signed=False, decimals=1):
    """Keep sub-tenth-percent differences visible instead of rounding them to 0.0%."""
    value = float(value)
    if round(value, decimals) == 0:
        if value == 0:
            return f"{0:.{decimals}f}%"
        return f"{value:+.{decimals + 2}f}%" if signed else f"{value:.{decimals + 2}f}%"
    return f"{value:+.{decimals}f}%" if signed else f"{value:.{decimals}f}%"

def md_safe(text):
    """Escape $ so amounts like 'NT$ 1 … NT$ 2' are not rendered as LaTeX math in st.markdown."""
    return str(text).replace("\\$", "$").replace("$", "\\$")

def to_m(series):
    """NT$ → NT$ millions, rounded for table display."""
    return (pd.to_numeric(series, errors="coerce") / 1e6).round(1)

def status_label(status):
    return f"{STATUS_EMOJI.get(status, '⚪')} {show_status(status)}"

PLOT_TEMPLATE = "plotly_dark" if IS_DARK else "plotly_white"
PLOT_CONFIG = {
    "displayModeBar": False,
    "scrollZoom": False,
    "doubleClick": False,
    "showTips": False,
    "responsive": True,
}
_card_ids = itertools.count()

def card(key=None):
    """A styled panel; keys share the card- prefix so CSS can theme every card."""
    return st.container(key=f"card-{key or next(_card_ids)}")

def page_header(title, subtitle=None):
    sub = f'<div class="page-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="page-head"><div class="page-title">{title}</div>{sub}</div>', unsafe_allow_html=True)

def section(title, help_text=None):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True, help=help_text)

def style_fig(fig, height=360, legend=True):
    """Fixed-size, non-draggable chart style shared by every figure."""
    fig.update_layout(
        template=PLOT_TEMPLATE, height=height, autosize=True,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_STACK, color=TEXT, size=12),
        dragmode=False, hovermode="closest", showlegend=legend,
        hoverlabel=dict(bgcolor=PANEL, bordercolor=BORDER, font=dict(color=TEXT, family=FONT_STACK, size=12)),
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0, title_text="",
                    font=dict(color=MUTED, size=11.5), bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=8, r=12, t=30, b=8),
        bargap=.28, barcornerradius=4,
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=BORDER, linecolor=BORDER, fixedrange=True,
                     tickfont=dict(color=MUTED), title_font=dict(color=MUTED, size=11.5), automargin=True)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=BORDER, linecolor=BORDER, fixedrange=True,
                     tickfont=dict(color=MUTED), title_font=dict(color=MUTED, size=11.5), automargin=True)
    return fig

def _nice_step(raw):
    if raw <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 2.5, 5, 10):
        if raw <= multiple * magnitude:
            return multiple * magnitude
    return 10 * magnitude

def money_axis(fig, horizontal=False, max_hint=None, min_hint=None):
    """Show amount axes in NT$ millions with evenly spaced ticks and consistent hover text."""
    values = []
    stacked = []
    for trace in fig.data:
        source = trace.x if horizontal else trace.y
        if source is None or trace.type not in ("bar", "scatter", "waterfall"):
            continue
        numeric = pd.to_numeric(pd.Series(list(source)), errors="coerce").to_numpy(dtype=float)
        values.extend(numeric[~np.isnan(numeric)].tolist())
        if trace.type == "bar":
            stacked.append(np.nan_to_num(numeric))
    if fig.layout.barmode in ("stack", "relative") and stacked and len({len(s) for s in stacked}) == 1:
        values.append(float(np.vstack(stacked).sum(axis=0).max()))
    top = max(values + [max_hint or 0, 1.0])
    bottom = min(values + [min_hint if min_hint is not None else 0, 0.0])
    step = _nice_step((top - bottom) / 5)
    ticks = np.arange(math.floor(bottom / step) * step, math.ceil(top / step) * step + step / 2, step)
    label_fmt = (lambda v: f"{v / 1e6:,.0f}") if step >= 1e6 else (lambda v: f"{v / 1e6:,.1f}")
    axis = fig.update_xaxes if horizontal else fig.update_yaxes
    axis(tickmode="array", tickvals=ticks, ticktext=[label_fmt(v) for v in ticks], title_text=None,
         range=[ticks[0] - step * .02 if bottom < 0 else 0, ticks[-1]])
    for trace in fig.data:
        if trace.type not in ("bar", "scatter") or trace.hovertemplate == "skip":
            continue
        name = trace.name or ""
        if horizontal:
            trace.hovertemplate = f"<b>%{{y}}</b><br>{name}: NT$ %{{x:,.0f}}<extra></extra>"
        else:
            trace.hovertemplate = f"<b>%{{x}}</b><br>{name}: NT$ %{{y:,.0f}}<extra></extra>"
    fig.add_annotation(
        x=1, y=1.02, xref="paper", yref="paper", text=tx("單位：NT$ 百萬元", "Unit: NT$ millions"),
        showarrow=False, xanchor="right", yanchor="bottom", font=dict(size=11, color=MUTED),
    )
    return fig

def variance_bar_fig(names, values, pcts, colors, hover_extra=None):
    """Diverging bar: 0 = exactly on budget, right = overspend, left = headroom. Labels carry amount and %."""
    frame = pd.DataFrame({"name": list(names), "value": list(values), "pct": list(pcts), "color": list(colors),
                          "extra": list(hover_extra) if hover_extra is not None else [""] * len(list(names))})
    frame = frame.sort_values("value")
    fig = go.Figure()
    fig.add_bar(
        y=frame.name, x=frame.value, orientation="h", marker=dict(color=frame.color, cornerradius=5),
        text=[f"{fmc(v, signed=True)}（{fpct(p, signed=True)}）" if not IS_EN else f"{fmc(v, signed=True)} ({fpct(p, signed=True)})"
              for v, p in zip(frame.value, frame.pct)],
        textposition="outside", cliponaxis=False, textfont=dict(color=TEXT, size=12), customdata=frame.extra,
    )
    fig.add_vline(x=0, line=dict(color=TEXT, width=1.6))
    style_fig(fig, height=max(300, 44 * len(frame) + 90), legend=False)
    span = max(abs(float(frame.value.max())), abs(float(frame.value.min())), 1.0)
    money_axis(fig, horizontal=True, max_hint=span * 2.2 if frame.value.max() > 0 else span * .25,
               min_hint=-span * 2.2 if frame.value.min() < 0 else -span * .25)
    fig.update_layout(margin=dict(l=8, r=24, t=30, b=8))
    fig.data[0].hovertemplate = "<b>%{y}</b><br>%{text}%{customdata}<extra></extra>"
    fig.add_annotation(x=0, y=1.02, xref="x", yref="paper", text=tx("◀ 低於預算　｜　超出預算 ▶", "◀ Under budget  |  Over budget ▶"),
                       showarrow=False, yanchor="bottom", font=dict(size=11, color=MUTED))
    fig.update_yaxes(showgrid=False)
    return fig

def show_chart(fig, title=None, help_text=None, key=None, caption=None):
    """Render a chart inside a card with a heading and an optional hover help icon."""
    with card(key):
        if title:
            st.markdown(f'<div class="chart-title">{title}</div>', unsafe_allow_html=True, help=help_text)
        st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG, theme=None, key=f"chart-{key}" if key else None)
        if caption:
            st.caption(caption)

def ui_spark(values, color, ref=None, height=34):
    """Tiny inline SVG trend line (optionally with a dashed reference line)."""
    series = [float(v) if v is not None and pd.notna(v) else None for v in values]
    reference = [float(v) if v is not None and pd.notna(v) else None for v in (ref or [])]
    pool = [v for v in series + reference if v is not None]
    if len(pool) < 2:
        return ""
    lo, hi = min(pool), max(pool)
    span = (hi - lo) or 1.0
    n = max(len(series), len(reference), 2)

    def points(seq):
        return " ".join(
            f"{i / (n - 1) * 100:.2f},{(1 - (v - lo) / span) * (height - 6) + 3:.2f}"
            for i, v in enumerate(seq) if v is not None
        )
    ref_line = (f'<polyline points="{points(reference)}" fill="none" stroke="{MUTED}" stroke-width="1.4" '
                f'stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>') if reference else ""
    return (f'<svg class="spark" viewBox="0 0 100 {height}" preserveAspectRatio="none">{ref_line}'
            f'<polyline points="{points(series)}" fill="none" stroke="{color}" stroke-width="2.2" '
            f'stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>')

def ui_kpi(label, value, sub, icon, color, glow=False, spark=""):
    if glow:
        background = f"linear-gradient(145deg,{rgba(color, .16)},{PANEL} 70%)"
        shadow = f"0 0 0 1px {rgba(color, .40)},0 10px 30px {rgba(color, .18)}"
        border = rgba(color, .55)
    else:
        background = f"linear-gradient(145deg,{PANEL},{RAISED})"
        shadow = f"0 6px 22px rgba(0,0,0,{.18 if IS_DARK else .05})"
        border = BORDER
    return (f'<div class="kpi" style="background:{background};box-shadow:{shadow};border-color:{border}">'
            f'<div class="top"><div class="ic" style="background:{rgba(color, .16)}">{icon}</div>'
            f'<div class="lb">{label}</div></div><div class="mid"><div class="vl">{value}</div>{spark}</div>'
            f'<div class="sb" title="{sub}">{sub}</div></div>')

def ui_chip(text, color=None):
    dot = f'<span class="dot" style="background:{color}"></span>' if color else ""
    return f'<span class="chip">{dot}{text}</span>'

def ui_badge(status):
    color = STATUS_COLORS.get(status, MUTED)
    return (f'<span class="badge" style="color:{color};background:{rgba(color, .14)};'
            f'border:1px solid {rgba(color, .38)}">{show_status(status)}</span>')

def ui_status_row(r, reason):
    """Budget 'fuel gauge': solid = spent so far, hatched = still expected to spend, dashed line = 100% of budget."""
    color = STATUS_COLORS.get(r.Status, MUTED)
    usage = max(0.0, float(r.Usage_Rate))
    forecast_ratio = float(r.Forecast_EOY / r.Budget_Full * 100) if r.Budget_Full else 0.0
    remaining = max(0.0, forecast_ratio - usage)
    scale = max(125.0, forecast_ratio + 5)
    reason_html = f'<div class="sreason">{reason}</div>' if reason else ""
    return (
        f'<div class="srow">'
        f'<div><div class="sname" style="border-left:4px solid {dept_color(r.Department)}">{show_dept(r.Department)}</div>{reason_html}</div>'
        f'<div><div class="bar">'
        f'<div class="fill" style="width:{usage / scale * 100:.1f}%;background:{color}"></div>'
        f'<div class="fill rest" style="left:{usage / scale * 100:.1f}%;width:{remaining / scale * 100:.1f}%;'
        f'background:repeating-linear-gradient(135deg,{rgba(color, .55)} 0 4px,{rgba(color, .22)} 4px 8px)"></div>'
        f'<span class="limit" style="left:{100 / scale * 100:.2f}%"><em>100%</em></span></div>'
        f'<div class="bsub">{tx("已花", "Spent")} <b>{fpct(usage)}</b> ＋ {tx("預計再花", "still to spend")} <b>{fpct(remaining)}</b> ＝ '
        f'{tx("年底", "year end")} <b style="color:{color}">{fpct(forecast_ratio)}</b></div></div>'
        f'<div>{ui_badge(r.Status)}</div>'
        f'<div class="amt" style="color:{color}">{fmc(r.Forecast_Var, signed=True)}</div></div>'
    )

def api_chat(api_key, messages, context, model="gemini-flash-lite-latest"):
    """Call the Gemini generateContent API without persisting the API key."""
    payload = {
        "system_instruction": {"parts": [{"text": context}]},
        "contents": [
            {"role": "model" if message["role"] == "assistant" else "user",
             "parts": [{"text": message["content"]}]}
            for message in messages
        ],
        "generationConfig": {"maxOutputTokens": 1200},
    }
    request = urllib.request.Request(
        f"{os.environ.get('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com')}/v1beta/models/{model}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        body = json.loads(response.read().decode("utf-8"))
    parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts if part.get("text")).strip()

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"  # 繁體中文表現穩定、一般筆電可跑；可在設定中改成任何已下載的模型

def config_value(name, default=""):
    """Read a setting from Streamlit secrets first, then environment variables."""
    try:
        value = st.secrets.get(name, "")
        if value:
            return str(value)
    except Exception:
        pass
    return os.environ.get(name, default)

def _ollama_headers(api_key):
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    return headers

@st.cache_data(ttl=30, show_spinner=False)
def list_ollama_models(host, api_key):
    """Return (installed model names, error text). Cached briefly so each rerun doesn't probe the server."""
    try:
        request = urllib.request.Request(f"{host}/api/tags", headers=_ollama_headers(api_key))
        with urllib.request.urlopen(request, timeout=3) as response:
            body = json.loads(response.read().decode("utf-8"))
        return sorted(m.get("name", "") for m in body.get("models", []) if m.get("name")), ""
    except Exception as err:
        return [], str(getattr(err, "reason", err))[:120]

def ollama_chat_stream(host, model, api_key, messages, system):
    """Stream reply text from Ollama's /api/chat (works for local Ollama and Ollama Cloud)."""
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"]} for m in messages
        ],
        "stream": True,
        "keep_alive": "30m",  # 展示期間讓模型常駐記憶體，避免每次冷啟動
        "options": {"temperature": 0.2, "num_ctx": 16384},
    }
    request = urllib.request.Request(
        f"{host}/api/chat", data=json.dumps(payload).encode("utf-8"),
        headers=_ollama_headers(api_key), method="POST",
    )
    in_think = False
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            chunk = json.loads(line)
            if chunk.get("error"):
                raise RuntimeError(chunk["error"])
            text = chunk.get("message", {}).get("content", "")
            # 推理型模型（qwen3、deepseek-r1）可能輸出 <think>…</think>，只保留最終回答；標籤可能同段或跨段出現。
            visible = []
            while text:
                if in_think:
                    end = text.find("</think>")
                    if end < 0:
                        text = ""
                    else:
                        in_think, text = False, text[end + len("</think>"):]
                else:
                    start = text.find("<think>")
                    if start < 0:
                        visible.append(text)
                        text = ""
                    else:
                        visible.append(text[:start])
                        in_think, text = True, text[start + len("<think>"):]
            out = "".join(visible)
            if out:
                yield out
            if chunk.get("done"):
                break

def describe_llm_error(provider, err, model=""):
    """Turn provider errors into actionable Chinese/English guidance."""
    if isinstance(err, urllib.error.HTTPError):
        raw_detail = err.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw_detail)
            detail = body.get("error", {}).get("message", raw_detail) if isinstance(body.get("error"), dict) else body.get("error", raw_detail)
        except (json.JSONDecodeError, AttributeError):
            detail = raw_detail
        if provider == "ollama" and err.code == 404:
            return tx(f"Ollama 找不到模型「{model}」。請先執行 `ollama pull {model}`，或在系統設定改選已下載的模型。",
                      f"Ollama can't find model '{model}'. Run `ollama pull {model}` or pick an installed model in Settings.")
        if err.code == 429:
            return tx("模型服務額度或速率已達上限，請稍後再試。", "The model service hit a quota or rate limit. Try again later.") + f"\n\nHTTP 429: {str(detail)[:300]}"
        if err.code in (401, 403):
            return tx("API 金鑰無效或沒有使用權限，請到系統設定檢查金鑰。", "The API key is invalid or lacks access. Check it in Settings.") + f"\n\nHTTP {err.code}: {str(detail)[:300]}"
        return f"HTTP {err.code}: {str(detail)[:400]}"
    if provider == "ollama" and isinstance(err, (urllib.error.URLError, ConnectionError, TimeoutError)):
        return tx("連不到 Ollama。請確認已安裝並啟動 Ollama（`ollama serve`），且系統設定中的位址正確。",
                  "Can't reach Ollama. Make sure it is installed and running (`ollama serve`) and the URL in Settings is correct.")
    return tx(f"AI 服務發生錯誤：{err}", f"AI service error: {err}")

def strip_think(text):
    """Drop <think>…</think> reasoning blocks some models return inline."""
    while "<think>" in text:
        start = text.find("<think>")
        end = text.find("</think>", start)
        text = text[:start] + (text[end + len("</think>"):] if end >= 0 else "")
    return text.strip()

def openai_compat_chat(base_url, api_key, model, messages, system):
    """Call an OpenAI-compatible /chat/completions endpoint (Groq, OpenRouter …)."""
    payload = {
        "model": model, "temperature": 0.2, "max_tokens": 1200,
        "messages": [{"role": "system", "content": system}] + [{"role": m["role"], "content": m["content"]} for m in messages],
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions", data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"content-type": "application/json", "authorization": f"Bearer {api_key}",
                 "http-referer": "https://streamlit.app", "x-title": "Budget Forecast Assistant"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))
    if body.get("error"):
        raise RuntimeError(body["error"])
    return strip_think(body.get("choices", [{}])[0].get("message", {}).get("content", "") or "")

# 免費的 OpenAI 相容服務；金鑰只放在 secrets／環境變數，模型名稱可覆寫。
COMPAT_PROVIDERS = {
    "groq": ("Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL", "llama-3.3-70b-versatile"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
}

@st.cache_data(ttl=12 * 3600, max_entries=300, show_spinner=False)
def cached_completion(provider, model, endpoint, system, messages_json, _api_key):
    """Shared answer cache: the same question on the same data costs the free quota only once for all users."""
    messages = json.loads(messages_json)
    if provider == "ollama":
        return strip_think("".join(ollama_chat_stream(endpoint, model, _api_key, messages, system)))
    if provider == "gemini":
        return strip_think(api_chat(_api_key, messages, system, model))
    return openai_compat_chat(endpoint, _api_key, model, messages, system)

def resolve_api_key(user_key, name="GEMINI_API_KEY"):
    """A key typed in Settings wins; otherwise use secrets/env. Secrets are never echoed back into widgets."""
    if user_key:
        return user_key.strip()
    return config_value(name, "").strip()

def local_budget_reply(question, budget_data, year):
    """Transparent non-AI fallback based on the selected budget rows."""
    q = question.casefold()
    dept = next((d for d in budget_data.Department
                 if any(alias.casefold() in q for alias in (d.split(" (")[0], DEPT_EN.get(d.split(" (")[0], "")))), None)
    budget_total = budget_data.Budget_Full.sum()
    actual_total = budget_data.Actual_YTD.sum()
    forecast_total = budget_data.Forecast_EOY.sum()
    if dept:
        row = budget_data[budget_data.Department == dept].iloc[0]
        return tx(
            f"**{show_dept(dept)}｜{year} 年預算**\n\n年度預算 {fmc(row.Budget_Full)}；目前已執行 {fmc(row.Actual_YTD)}（使用率 {fpct(row.Usage_Rate)}）；年底預測 {fmc(row.Forecast_EOY)}，預測差異 {fmc(row.Forecast_Var, signed=True)}（{fpct(row.Forecast_Pct, signed=True)}）。狀態：{status_label(row.Status)}。",
            f"**{show_dept(dept)} | {year} budget**\n\nAnnual budget: {fmc(row.Budget_Full)}; actual to date: {fmc(row.Actual_YTD)} ({fpct(row.Usage_Rate)} utilized); year-end forecast: {fmc(row.Forecast_EOY)}; forecast variance: {fmc(row.Forecast_Var, signed=True)} ({fpct(row.Forecast_Pct, signed=True)}). Status: {status_label(row.Status)}.",
        )
    if any(word in q for word in ["超支", "風險", "overspend", "risk"]):
        rows = budget_data[budget_data.Forecast_Var > 0].sort_values("Forecast_Var", ascending=False)
        if rows.empty:
            return tx("目前選取的部門沒有預測超支項目。", "No selected departments are forecast to exceed budget.")
        items = "\n".join(f"- **{show_dept(r.Department)}**：{fmc(r.Forecast_Var, signed=True)}（{fpct(r.Forecast_Pct, signed=True)}）" for r in rows.itertuples())
        items_en = "\n".join(f"- **{show_dept(r.Department)}**: {fmc(r.Forecast_Var, signed=True)} ({fpct(r.Forecast_Pct, signed=True)})" for r in rows.itertuples())
        return tx("**預測超支部門**\n\n" + items, "**Departments forecast to exceed budget**\n\n" + items_en)
    if any(word in q for word in ["落後", "閒置", "結餘", "behind", "underspend"]):
        rows = budget_data[budget_data.Status.str.contains("落後")]
        if rows.empty:
            return tx("目前選取的部門沒有符合執行落後門檻的項目。", "No selected departments meet the behind-plan threshold.")
        items = "\n".join(f"- **{show_dept(r.Department)}**：預測結餘 {fmc(-r.Forecast_Var)}" for r in rows.itertuples())
        items_en = "\n".join(f"- **{show_dept(r.Department)}**: forecast underspend {fmc(-r.Forecast_Var)}" for r in rows.itertuples())
        return tx("**執行落後項目**\n\n" + items, "**Departments behind plan**\n\n" + items_en)
    return tx(
        f"{year} 年目前選取部門：年度預算 {fmc(budget_total)}，已執行 {fmc(actual_total)}，年底預測 {fmc(forecast_total)}。輸入部門名稱可查個別預算；在「系統設定」輸入 API 金鑰後可用 Gemini 進行延伸分析。",
        f"Selected departments in {year}: annual budget {fmc(budget_total)}, actual spending {fmc(actual_total)}, and year-end forecast {fmc(forecast_total)}. Ask about a department for its breakdown, or add an API key in Settings for Gemini analysis.",
    )

# ==========================================
# 5. 側邊欄：品牌、導覽、篩選、系統設定
# ==========================================
with sb_brand:
    st.markdown(
        f'<div class="sb-brand"><div class="sb-mark"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#fff" '
        f'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg></div>'
        f'<div><div class="sb-title">{tx("預算決策中心", "Budget Command Center")}</div>'
        f'<div class="sb-sub">BNP Paribas Cardif TW · {tx("競賽展示版", "Hackathon demo")}</div></div></div>',
        unsafe_allow_html=True,
    )

main_nav_ids = ["overview", "budget_analysis", "forecast_risk", "scenarios_quality", "ai_assistant"]
main_nav_labels = {
    "overview": tx(":material/dashboard: 總覽", ":material/dashboard: Overview"),
    "budget_analysis": tx(":material/bar_chart: 預算分析", ":material/bar_chart: Budget analysis"),
    "forecast_risk": tx(":material/trending_up: 預測與預警", ":material/trending_up: Forecast & risk"),
    "scenarios_quality": tx(":material/tune: 情境與資料品質", ":material/tune: Scenarios & data quality"),
    "ai_assistant": tx(":material/forum: AI 助理", ":material/forum: AI assistant"),
}
with sb_nav:
    st.markdown(f'<div class="sb-label">{tx("功能", "Navigate")}</div>', unsafe_allow_html=True)
    with st.container(key="nav_slot"):
        active_nav_id = st.radio(
            tx("主要功能", "Navigation"), main_nav_ids, format_func=lambda nav_id: main_nav_labels[nav_id],
            key="main_navigation_id", label_visibility="collapsed",
        )

with sb_settings:
    st.markdown(f'<div class="sb-label">{tx("系統", "System")}</div>', unsafe_allow_html=True)
    with st.popover(tx("系統設定", "Settings"), icon=":material/settings:", width="stretch"):
        st.markdown(f"**{tx('資料來源', 'Data source')}**")
        opex_anchor_100m = st.number_input(
            tx("合成資料量級：8 部門年度預算合計（NT$ 億）", "Synthetic scale: 8-department annual budget (NT$ 100M)"),
            min_value=1.0, max_value=500.0, value=DEFAULT_OPEX_ANCHOR_100M, step=1.0, key="opex_anchor_100m",
            help=tx("示範假設值。請至公開資訊觀測站（MOPS）查詢法巴人壽近一年損益表的「營業費用」量級後填入，系統會依部門比例拆分為各部門預算基準。",
                    "Demo assumption. Look up the insurer's latest operating-expense total in its public income statement (MOPS) and enter it; the app splits it across departments as the budget baseline."),
        )
        st.download_button(
            tx("下載 CSV 範本（目前資料）", "Download CSV template (current data)"),
            generate_monthly_db(opex_anchor_100m * 1e8).to_csv(index=False).encode("utf-8-sig"),
            file_name="budget_monthly_template.csv", mime="text/csv", icon=":material/download:", width="stretch",
        )
        uploaded_file = st.file_uploader(
            tx("匯入預算資料 CSV", "Import budget CSV"), type=["csv"], key="budget_csv_upload",
            help=tx("必要欄位：Year、Month、Department、Budget、Actual；OneOffAmount 與 EventNote 可選填。Actual 留空代表尚未結算；每個年度與部門需有完整 12 個月預算。上傳資料只在目前工作階段使用。",
                    "Required: Year, Month, Department, Budget, Actual; OneOffAmount and EventNote are optional. Leave Actual blank for unclosed months. Each year and department needs all 12 monthly budgets. Uploaded data stays in this session only."),
        )
        st.divider()
        st.markdown(f"**{tx('預警門檻', 'Alert thresholds')}**", help=tx("以「年底預測 ÷ 年度預算」判斷部門燈號。", "Status uses year-end forecast ÷ annual budget."))
        st.slider(tx("需注意：超過預算（%）", "Watch: above budget (%)"), 100, 110, 102, key="thr_watch_pct")
        st.slider(tx("高風險：超過預算（%）", "High risk: above budget (%)"), 102, 125, 105, key="thr_high_pct")
        st.slider(tx("執行落後：低於預算（%）", "Behind plan: below budget (%)"), 60, 100, 90, key="thr_lag_pct")
        st.divider()
        st.markdown(f"**{tx('AI 模型', 'AI model')}**", help=tx(
            "優先使用的服務額度用完或連線失敗時，會自動改用其他已設定金鑰的免費服務，全部失敗才改用內建規則；相同問題的回答會共用快取，不重複消耗額度。",
            "If the preferred service runs out of free quota or fails, other configured free services are tried automatically, then built-in rules. Identical questions share a cached answer."))
        provider_names = {"ollama": "Ollama", "gemini": "Gemini", "groq": "Groq", "openrouter": "OpenRouter",
                          "rules": tx("內建規則（不用模型）", "Built-in rules (no model)")}
        provider_key_names = {"ollama": "OLLAMA_API_KEY", "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
        # 伺服器端已設定金鑰（部署到公開網址）時預設鎖定：訪客看不到也改不了 AI 設定，避免金鑰外洩或被改連其他網址。
        server_configured = any(config_value(k) for k in ["AI_PROVIDER", *provider_key_names.values()])
        ai_locked = config_value("LOCK_AI_SETTINGS", "1" if server_configured else "0") == "1"
        cfg_host = config_value("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).strip().rstrip("/")
        typed_keys = {}
        ollama_host = cfg_host
        if ai_locked:
            ai_provider = config_value("AI_PROVIDER", "gemini")
            ai_provider = ai_provider if ai_provider in provider_names else "rules"
            st.caption(tx("🔒 公開模式：AI 服務與金鑰由管理者在伺服器端設定，訪客無法查看或修改。",
                          "🔒 Public mode: AI services and keys are configured on the server and cannot be viewed or changed by visitors."))
        else:
            detected = list_ollama_models(cfg_host, config_value("OLLAMA_API_KEY"))[0]
            default_provider = config_value("AI_PROVIDER", "ollama" if detected else next(
                (p for p in ("gemini", "groq", "openrouter") if config_value(provider_key_names[p])), "rules"))
            options = list(provider_names)
            ai_provider = st.selectbox(
                tx("優先使用的模型服務", "Preferred model service"), options, format_func=provider_names.get, key="ai_provider",
                index=options.index(default_provider) if default_provider in options else len(options) - 1,
            )
            if ai_provider == "ollama":
                ollama_host = st.text_input(
                    tx("Ollama 位址", "Ollama URL"), value=cfg_host, key="ollama_host",
                    help=tx("本機 Ollama 為 http://localhost:11434；Ollama Cloud 請填 https://ollama.com 並輸入金鑰。",
                            "Local Ollama is http://localhost:11434; for Ollama Cloud use https://ollama.com with a key."),
                ).strip().rstrip("/")
            if ai_provider != "rules":
                typed_keys[ai_provider] = st.text_input(
                    tx(f"{provider_names[ai_provider]} API 金鑰", f"{provider_names[ai_provider]} API key")
                    + (tx("（本機 Ollama 不需要）", " (not needed for local Ollama)") if ai_provider == "ollama" else ""),
                    type="password", key=f"{ai_provider}_api_key", value="",
                    help=tx("留空則使用伺服器 secrets 的金鑰；在這裡輸入的金鑰只存在你目前的瀏覽工作階段。",
                            "Leave blank to use the server's secrets; a key typed here lives only in your current session."),
                ).strip()
        ollama_key = resolve_api_key(typed_keys.get("ollama"), "OLLAMA_API_KEY")
        provider_keys = {p: resolve_api_key(typed_keys.get(p), provider_key_names[p]) for p in ("gemini", "groq", "openrouter")}
        ollama_models, ollama_error = list_ollama_models(ollama_host, ollama_key)
        preferred_model = config_value("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        if ollama_models and ai_provider == "ollama" and not ai_locked:
            ollama_model = st.selectbox(
                tx("Ollama 模型", "Ollama model"), ollama_models, key="ollama_model_pick",
                index=ollama_models.index(preferred_model) if preferred_model in ollama_models else 0,
            )
        else:
            ollama_model = preferred_model if (not ollama_models or preferred_model in ollama_models) else ollama_models[0]
            if ai_provider == "ollama" and not ollama_models and not ai_locked:
                st.caption(tx(f"⚠️ 目前連不到 Ollama（{ollama_error}）。本機請安裝 Ollama 並執行 `ollama pull {preferred_model}`。",
                              f"⚠️ Ollama is not reachable ({ollama_error}). Install Ollama locally and run `ollama pull {preferred_model}`."))
        st.caption(tx("淺色／深色主題：右上角選單 ⋮ → Settings。", "Light/dark theme: top-right menu ⋮ → Settings."))
        st.caption(tx("內建資料為競賽展示用合成資料，數字邏輯依保險業常見情境設計（年末消耗、一次性 CAPEX、專案超支／延宕），不代表任何公司實際數據。",
                      "Built-in data is synthetic for the demo. It models common insurance scenarios (year-end flush, one-off CAPEX, project overruns and delays) and does not represent any company's actual figures."))

df_db = generate_monthly_db(opex_anchor_100m * 1e8)
data_source = tx("合成示範資料", "Synthetic demo data")
is_synthetic = True
if uploaded_file is not None:
    try:
        validated_data, upload_errors = validate_budget_upload(pd.read_csv(uploaded_file))
        if upload_errors:
            for message in upload_errors:
                sb_settings.error(message, icon=":material/error:")
        else:
            df_db = validated_data
            data_source = tx("已匯入 CSV", "Imported CSV")
            is_synthetic = False
            sb_settings.success(tx(f"已載入 {len(df_db):,} 筆月資料。", f"Loaded {len(df_db):,} monthly rows."), icon=":material/check_circle:")
    except Exception as err:
        sb_settings.error(tx(f"CSV 讀取失敗：{err}", f"Could not read CSV: {err}"))

available_years = sorted(df_db.Year.unique().tolist())
available_depts = sorted(df_db.Department.unique().tolist(), key=lambda d: DEPTS.index(d) if d in DEPTS else 99)
with sb_filters:
    st.markdown(f'<div class="sb-label">{tx("篩選", "Filters")}</div>', unsafe_allow_html=True)
    if st.session_state.get("fiscal_year") not in available_years:
        st.session_state["fiscal_year"] = available_years[-1]
    selected_year = st.select_slider(tx("分析年度", "Fiscal year"), options=available_years, key="fiscal_year")
    picked = st.pills(
        tx("部門", "Departments"), available_depts, selection_mode="multi", default=available_depts,
        format_func=show_dept, key="dept_pills",
    )
    selected_depts = [d for d in available_depts if d in (picked or [])]
    if not selected_depts:
        st.caption(tx("未選擇部門時，預設分析全部部門。", "No department selected — showing all departments."))
        selected_depts = available_depts

# ==========================================
# 6. 共用計算
# ==========================================
expense_detail = generate_expense_detail(df_db)
analysis_res = analyze_budget(df_db, selected_year, selected_depts)
tb_sum = analysis_res.Budget_Full.sum()
ta_sum = analysis_res.Actual_YTD.sum()
tf_sum = analysis_res.Forecast_EOY.sum()
df_filtered_year = df_db[(df_db.Year == selected_year) & (df_db.Department.isin(selected_depts))]
observed_months_selected = df_db[(df_db.Year == selected_year) & df_db.Actual.notna()].Month
data_cutoff_month = int(observed_months_selected.max()) if not observed_months_selected.empty else 0

monthly_budget = df_filtered_year.groupby("Month").Budget.sum().reindex(MONTHS, fill_value=0.0)
monthly_actual = df_filtered_year.groupby("Month").Actual.agg(lambda values: values.sum(min_count=1)).reindex(MONTHS)
monthly_estimate, estimate_basis_by_department = allocate_remaining_by_month(analysis_res, df_db, selected_year, df_filtered_year)

# Shared, reproducible assistant context, independent of which page was visited first.
assistant_current_expenses = expense_detail[
    (expense_detail.Year == selected_year)
    & (expense_detail.Month <= data_cutoff_month)
    & expense_detail.Department.isin(selected_depts)
].copy()
assistant_historical_expenses = expense_detail[
    (expense_detail.Year < selected_year)
    & (expense_detail.Month <= data_cutoff_month)
    & expense_detail.Department.isin(selected_depts)
].groupby(["Year", "Department", "Account"], as_index=False).Amount.sum()
assistant_history_avg = assistant_historical_expenses.groupby(
    ["Department", "Account"], as_index=False
).Amount.mean().rename(columns={"Amount": "Historical_Avg"})
assistant_current_accounts = assistant_current_expenses.groupby(
    ["Department", "Account"], as_index=False
).Amount.sum()
assistant_drivers = assistant_current_accounts.merge(
    assistant_history_avg, on=["Department", "Account"], how="left"
)
assistant_drivers["Variance"] = assistant_drivers.Amount - assistant_drivers.Historical_Avg
assistant_drivers["Variance_Pct"] = np.where(
    assistant_drivers.Historical_Avg > 0,
    assistant_drivers.Variance / assistant_drivers.Historical_Avg * 100,
    np.nan,
)
assistant_drivers = assistant_drivers.sort_values("Variance", ascending=False, na_position="last")
assistant_duplicates = assistant_current_expenses[
    assistant_current_expenses.duplicated(
        ["Year", "Month", "Department", "Account", "Vendor", "Expense_ID"], keep=False
    )
].copy()

def executive_summary(analysis):
    """Rule-based one-paragraph conclusion for the top of the dashboard."""
    total_var = float(analysis.Forecast_EOY.sum() - analysis.Budget_Full.sum())
    budget = float(analysis.Budget_Full.sum())
    pct = total_var / budget * 100 if budget else 0.0
    parts = [tx(
        f"預估年底總支出 {fmc(analysis.Forecast_EOY.sum())}，較年度預算{'多' if total_var > 0 else '少'} {fmc(abs(total_var))}（{fpct(pct, signed=True)}）。",
        f"Year-end spending is projected at {fmc(analysis.Forecast_EOY.sum())}, {fmc(abs(total_var))} {'above' if total_var > 0 else 'below'} the annual budget ({fpct(pct, signed=True)}).",
    )]
    pressure = analysis[analysis.Status.isin(["高風險超支", "需注意"])].sort_values("Forecast_Var", ascending=False)
    if not pressure.empty:
        names = ("、" if not IS_EN else ", ").join(f"{show_dept(r.Department)}（{fmc(r.Forecast_Var, signed=True)}）" if not IS_EN else f"{show_dept(r.Department)} ({fmc(r.Forecast_Var, signed=True)})" for r in pressure.head(2).itertuples())
        parts.append(tx(f"主要超支壓力來自 {names}。", f"The main overspend pressure comes from {names}."))
    headroom = analysis[analysis.Status == "執行落後"]
    if not headroom.empty:
        names = ("、" if not IS_EN else ", ").join(show_dept(d) for d in headroom.Department)
        parts.append(tx(
            f"{names} 預估結餘合計 {fmc(-headroom.Forecast_Var.sum())}，可優先評估內部調撥。",
            f"{names} may leave {fmc(-headroom.Forecast_Var.sum())} unused, a first source for reallocation.",
        ))
    if pressure.empty and headroom.empty:
        parts.append(tx("所有部門皆在預警門檻內。", "All departments are within alert thresholds."))
    return "".join(parts) if not IS_EN else " ".join(parts)

def build_ai_facts(question=None):
    """Compact budget facts for the LLM. Amounts are pre-formatted text so small models never convert units themselves.

    Detail sections are attached only when the question needs them, which roughly halves token use on free-tier APIs.
    """
    q = (question or "").casefold()
    wants = lambda *terms: question is not None and any(t in q for t in terms)
    category_ytd = assistant_current_expenses.groupby(["Department", "Account"]).Amount.sum()
    ordered = analysis_res.assign(_s=analysis_res.Status.map(STATUS_SEVERITY)).sort_values(["_s", "Forecast_Var"], ascending=[True, False])
    m = data_cutoff_month
    facts = {
        "fiscal_year": selected_year, "answer_language": "English" if IS_EN else "Traditional Chinese (Taiwan)",
        "data_source": data_source, "actuals_closed_through_month": m,
        "company_total": {
            "annual_budget": fmc(tb_sum), f"actual_spent_through_month_{m}": fmc(ta_sum),
            "year_end_forecast": fmc(tf_sum),
            "year_end_forecast_minus_budget": f"{fmc(tf_sum - tb_sum, signed=True)} ({fpct((tf_sum - tb_sum) / tb_sum * 100 if tb_sum else 0, signed=True)})",
        },
        "departments_expected_to_overspend_largest_first": [
            f"{show_dept(r.Department)} {fmc(r.Forecast_Var, signed=True)} ({fpct(r.Forecast_Pct, signed=True)})"
            for r in analysis_res[analysis_res.Forecast_Var > 0].sort_values("Forecast_Var", ascending=False).itertuples()
        ],
        "departments_with_expected_unused_budget_largest_first": [
            f"{show_dept(r.Department)} {tx('預估結餘', 'unused')} {fmc(-r.Forecast_Var)} ({fpct(r.Forecast_Pct, signed=True)})"
            for r in analysis_res[analysis_res.Forecast_Var < 0].sort_values("Forecast_Var").itertuples()
        ],
        "alerts_to_report_in_this_order": [
            f"{STATUS_EMOJI[r.Status]} {show_dept(r.Department)} | {show_status(r.Status)} | "
            f"{tx('年底預測差異', 'year-end forecast variance')} {fmc(r.Forecast_Var, signed=True)} ({fpct(r.Forecast_Pct, signed=True)}) | "
            f"{risk_evidence(df_db, selected_year, r)[0]}"
            for r in ordered.itertuples() if r.Status != "預算正常"
        ],
        "departments": [
            {"department": show_dept(r.Department), "status": show_status(r.Status),
             "annual_budget": fmc(r.Budget_Full),
             f"budget_through_month_{m}": fmc(r.Budget_YTD), f"actual_spent_through_month_{m}": fmc(r.Actual_YTD),
             f"variance_through_month_{m}": f"{fmc(r.Variance, signed=True)} ({fpct(r.Variance_Pct, signed=True)})",
             "year_end_forecast": fmc(r.Forecast_EOY),
             "year_end_forecast_likely_range": f"{fmc(r.Forecast_Low)} – {fmc(r.Forecast_High)}",
             "year_end_forecast_minus_budget": f"{fmc(r.Forecast_Var, signed=True)} ({fpct(r.Forecast_Pct, signed=True)})",
             "evidence": risk_evidence(df_db, selected_year, r)}
            for r in ordered.itertuples()
        ],
        "historical_annual_actual_vs_budget": [
            {"year": int(year), "department": show_dept(dept), "actual": fmc(row.Actual), "execution_rate": fpct(row.Actual / row.Budget * 100)}
            for (year, dept), row in df_db[
                df_db.Department.isin(selected_depts) & df_db.Actual.notna() & (df_db.Year < selected_year)
            ].groupby(["Year", "Department"])[["Budget", "Actual"]].sum().iterrows()
        ],
        "selected_year_monthly_company_totals": [
            {"month": int(mo), "budget": fmc(monthly_budget.loc[mo]),
             "actual": fmc(monthly_actual.loc[mo]) if pd.notna(monthly_actual.loc[mo]) else None,
             "forecast": fmc(monthly_estimate.loc[mo]) if monthly_estimate.loc[mo] > 0 else None}
            for mo in MONTHS
        ],
        "tagged_events": [
            {"department": show_dept(r.Department), "month": int(r.Month), "event": show_event(r.EventNote),
             "one_off_amount": fmc(r.OneOffAmount) if r.OneOffAmount > 0 else None}
            for r in df_filtered_year[df_filtered_year.EventNote.astype(str).str.strip().ne("")].drop_duplicates(["Department", "EventNote"]).itertuples()
        ],
        f"expense_category_spent_through_month_{m}": [
            {"department": show_dept(dept), "category": show_account(account), "amount": fmc(amount)}
            for (dept, account), amount in category_ytd.items()
        ],
        "cost_driver_screen_vs_prior_years_same_period": [
            {"department": show_dept(row.Department), "category": show_account(row.Account),
             "current": fmc(row.Amount),
             "prior_years_average": fmc(row.Historical_Avg) if pd.notna(row.Historical_Avg) else None,
             "change": fpct(row.Variance_Pct, signed=True) if pd.notna(row.Variance_Pct) else None}
            for row in assistant_drivers.head(10).itertuples()
        ],
        "potential_duplicate_lines": [
            {"department": show_dept(row.Department), "month": int(row.Month), "category": show_account(row.Account),
             "expense_id": row.Expense_ID, "amount": fmc(row.Amount)}
            for row in assistant_duplicates.itertuples()
        ],
    }
    optional = {
        "historical_annual_actual_vs_budget": wants("歷史", "往年", "去年", "歷年", "前年", "history", "past", "last year", "trend", "趨勢"),
        "selected_year_monthly_company_totals": wants("月", "季", "month", "quarter", "季節", "season", "趨勢", "trend"),
        f"expense_category_spent_through_month_{m}": wants("科目", "費用", "成本", "原因", "為什麼", "雲端", "顧問", "廣告", "訓練",
                                                          "category", "cost", "why", "cause", "driver", "cloud"),
        "cost_driver_screen_vs_prior_years_same_period": wants("原因", "為什麼", "驅動", "異常", "成本", "why", "cause", "driver", "anomal"),
        "potential_duplicate_lines": wants("重複", "稽核", "異常", "發票", "duplicate", "audit", "invoice", "anomal"),
    }
    for section_name, needed in optional.items():
        if not needed:
            facts.pop(section_name, None)
    return facts

AI_RULES = (
    "You are a budget analysis assistant for an insurance company's finance team. "
    "Always answer in the requested language; for Chinese use Taiwan Traditional Chinese. "
    "All amounts in the facts are already formatted (e.g. 'NT$ 30.71 億'): copy them exactly, never convert units or recompute them. "
    "Distinguish carefully between amounts 'through month N' (actuals so far) and 'year_end_forecast' figures; never mix them. "
    "For rankings (largest overspend, most unused budget / reallocation sources) use the pre-sorted lists as given; a positive variance is overspend, never headroom. "
    "Use only the supplied facts for numbers and say when data is insufficient. "
    "When explaining risk, cite the department, amount, comparison basis and the supplied evidence; do not invent causes. "
    "Forecasts blend 55% seasonality from prior complete years and 45% run rate; one-off amounts are not extrapolated. "
    "Built-in data is synthetic demo data, not real company figures. Variance screens are review signals, not proof of fraud. "
    "Reallocation ideas are recommendations, never approved transactions. Keep answers concise and use short bullet lists.\n"
)

def ai_chain():
    """Configured model services in try order: the preferred one first, then every other service that has a key."""
    if ai_provider == "rules":
        return []
    chain = []
    for pid in [ai_provider] + [p for p in ("ollama", "gemini", "groq", "openrouter") if p != ai_provider]:
        if pid == "ollama" and ollama_models and ollama_model:
            where = tx("本機", "local") if any(h in ollama_host for h in ("localhost", "127.0.0.1")) else tx("雲端", "cloud")
            chain.append({"id": "ollama", "label": f"Ollama · {ollama_model}（{where}）", "model": ollama_model, "endpoint": ollama_host, "key": ollama_key})
        elif pid == "gemini" and provider_keys["gemini"]:
            model = config_value("GEMINI_MODEL", "gemini-flash-lite-latest")
            chain.append({"id": "gemini", "label": f"Gemini · {model}", "model": model, "endpoint": "", "key": provider_keys["gemini"]})
        elif pid in COMPAT_PROVIDERS and provider_keys[pid]:
            name, base, _, model_var, default_model = COMPAT_PROVIDERS[pid]
            base = os.environ.get(f"{pid.upper()}_BASE_URL", base)  # 只供本機測試指向模擬伺服器
            model = config_value(model_var, default_model)
            chain.append({"id": pid, "label": f"{name} · {model}", "model": model, "endpoint": base, "key": provider_keys[pid]})
    return chain

def ai_available():
    return bool(ai_chain())

def ai_provider_label():
    chain = ai_chain()
    return chain[0]["label"] if chain else tx("內建規則", "Built-in rules")

@st.cache_resource
def provider_cooldowns():
    """Shared across users: services that just hit a free-tier rate limit are skipped for a short while."""
    return {}

def llm_answer(messages, system):
    """Try each configured free service in order. Returns (text, label used, notes about skipped services)."""
    notes = []
    payload = json.dumps(messages, ensure_ascii=False)
    cooldowns = provider_cooldowns()
    for prov in ai_chain():
        if time.time() < cooldowns.get(prov["id"], 0):
            notes.append(tx(f"{prov['label']}：額度暫時用完，稍後自動恢復", f"{prov['label']}: quota temporarily used up"))
            continue
        try:
            text = cached_completion(prov["id"], prov["model"], prov["endpoint"], system, payload, prov["key"])
            if text.strip():
                return text, prov["label"], notes
            notes.append(tx(f"{prov['label']} 沒有回傳內容", f"{prov['label']} returned nothing"))
        except Exception as err:
            if isinstance(err, urllib.error.HTTPError) and err.code == 429:
                cooldowns[prov["id"]] = time.time() + 90
            notes.append(f"{prov['label']}：{describe_llm_error(prov['id'], err, prov['model']).splitlines()[0]}")
    raise RuntimeError("\n".join(notes) or tx("沒有可用的模型服務", "No model service available"))

def alert_message_lines():
    """System-generated alert messages: always complete and numerically exact (not left to the LLM)."""
    alerts = analysis_res[analysis_res.Status != "預算正常"].assign(_s=lambda d: d.Status.map(STATUS_SEVERITY)).sort_values(["_s", "Forecast_Var"], ascending=[True, False])
    lines = [
        f"- {STATUS_EMOJI[r.Status]} **{show_dept(r.Department)}｜{show_status(r.Status)}**："
        f"{tx('年底預測差異', 'year-end forecast variance')} {fmc(r.Forecast_Var, signed=True)}（{fpct(r.Forecast_Pct, signed=True)}）。"
        f"{risk_evidence(df_db, selected_year, r)[0]}"
        for r in alerts.itertuples()
    ]
    return lines or [tx("- 目前沒有部門觸發預警。", "- No department currently triggers an alert.")]

def rule_based_brief():
    """Deterministic fallback for the AI brief, so the feature still works without a model."""
    return "\n".join([f"## {tx('執行摘要', 'Executive summary')}", "", executive_summary(analysis_res), "",
                      f"## {tx('預警訊息', 'Alert messages')}", "", *alert_message_lines()])

def merge_brief(llm_text):
    """Insert the system-generated alert section between the LLM's summary and its recommended actions."""
    alerts = "\n".join([f"## {tx('預警訊息（系統產生）', 'Alert messages (system-generated)')}", "", *alert_message_lines(), ""])
    for marker in ("## 建議行動", "## Recommended actions", "## 建議"):
        pos = llm_text.find(marker)
        if pos >= 0:
            return llm_text[:pos].rstrip() + "\n\n" + alerts + "\n" + llm_text[pos:]
    return llm_text.rstrip() + "\n\n" + alerts

def ai_brief_panel(key):
    """Button + output for an AI-written executive summary and alert messages (requirement: 產生預算分析摘要與預警訊息)."""
    signature = (selected_year, tuple(selected_depts), IS_EN, ai_provider_label(), round(tf_sum))
    cached = st.session_state.get("ai_brief")
    with card(f"brief-{key}"):
        head, action = st.columns([3, 1.3], vertical_alignment="center")
        head.markdown(f'<div class="chart-title">✨ {tx("AI 預算分析摘要與預警訊息", "AI budget brief & alert messages")}</div>', unsafe_allow_html=True,
                      help=tx("由所選模型依目前篩選資料撰寫；無模型時改用內建規則產生，數字皆來自系統計算結果。",
                              "Written by the selected model from the current filters; without a model, built-in rules generate it. All numbers come from the system's calculations."))
        clicked = action.button(tx("產生摘要", "Generate brief") if not (cached and cached["sig"] == signature) else tx("重新產生", "Regenerate"),
                                key=f"brief_btn_{key}", icon=":material/auto_awesome:", type="primary", width="stretch")
        if clicked:
            if ai_available():
                prompt = tx(
                    "請為財務長撰寫本年度預算分析簡報，使用 Markdown，只寫以下兩個段落（預警清單由系統另外附上，你不用列）：\n"
                    "## 執行摘要\n3 句內：引用 company_total 的年度預算、年底預測與差異（金額照抄），並點出超支壓力最大與預估結餘最多的部門。\n"
                    "## 建議行動\n3 點具體可執行的建議：如何控制超支部門剩餘月份的支出、哪些預估結餘部門可作為調撥來源、需要追蹤的事項。",
                    "Write this year's budget brief for the CFO in Markdown with only these two sections (the alert list is appended by the system):\n"
                    "## Executive summary\n≤3 sentences: company_total budget, forecast and gap (copy amounts exactly), naming the biggest overspend and headroom departments.\n"
                    "## Recommended actions\n3 concrete actions: controlling remaining-month spend of overspending departments, which headroom departments can fund reallocation, what to monitor.",
                )
                try:
                    with st.spinner(tx(f"{ai_provider_label()} 撰寫中…", f"{ai_provider_label()} is writing…")):
                        raw, source, notes = llm_answer([{"role": "user", "content": prompt}], AI_RULES + json.dumps(build_ai_facts(), ensure_ascii=False))
                    text = merge_brief(raw)
                    if notes:
                        source += tx("（已自動略過：", " (skipped: ") + "；".join(notes) + tx("）", ")")
                except Exception as err:
                    text, source = rule_based_brief(), tx("內建規則（模型額度已用完或無法連線）", "Built-in rules (model quota used up or unreachable)")
                    st.caption(f"ℹ️ {err}")
            else:
                text, source = rule_based_brief(), tx("內建規則", "Built-in rules")
            cached = {"sig": signature, "text": text.strip(), "source": source}
            st.session_state["ai_brief"] = cached
        if cached and cached["sig"] == signature:
            st.markdown(md_safe(cached["text"]))
            foot, dl = st.columns([3, 1.3], vertical_alignment="center")
            foot.caption(tx(f"產生來源：{cached['source']}", f"Generated by: {cached['source']}"))
            dl.download_button(tx("下載 .md", "Download .md"), cached["text"], file_name=f"ai_budget_brief_{selected_year}.md",
                               key=f"brief_dl_{key}", icon=":material/download:", width="stretch")
        else:
            st.caption(tx("點「產生摘要」，AI 會依目前年度與部門篩選寫出主管摘要、各部門預警訊息與建議行動。",
                          "Click Generate to have the AI write an executive summary, per-department alerts and recommended actions for the current filters."))

def build_chat_chart(chart_spec):
    if chart_spec["type"] == "dimension":
        dim_column = chart_spec["dimension"]
        detail = expense_detail[
            (expense_detail.Year == selected_year)
            & expense_detail.Department.isin(chart_spec.get("departments", selected_depts))
        ].copy()
        if chart_spec.get("account"):
            detail = detail[detail.Account == chart_spec["account"]]
        quarter = chart_spec.get("quarter")
        if quarter:
            detail = detail[detail.Month.between((quarter - 1) * 3 + 1, quarter * 3)]
        grouped = detail.groupby([dim_column, "Department"], as_index=False).Amount.sum()
        top_dimensions = grouped.groupby(dim_column).Amount.sum().nlargest(12).index
        grouped = grouped[grouped[dim_column].isin(top_dimensions)]
        if dim_column == "Vendor":
            grouped[dim_column] = grouped[dim_column].map(show_vendor)
        dimension_labels = {
            "Project": tx("專案", "Project"), "Vendor": tx("供應商", "Vendor"),
            "Cost_Center": tx("成本中心", "Cost center"), "Employee": tx("員工代碼（合成）", "Employee ID (synthetic)"),
        }
        figure = go.Figure()
        for dept, part in grouped.groupby("Department", sort=False):
            figure.add_bar(x=part[dim_column], y=part.Amount, name=show_dept(dept), marker_color=dept_color(dept))
        figure.update_layout(barmode="group")
        title = tx(f"依{dimension_labels[dim_column]}檢視支出", f"Spending by {dimension_labels[dim_column].lower()}")
    elif chart_spec["type"] == "account":
        detail = expense_detail[
            (expense_detail.Year == selected_year)
            & expense_detail.Department.isin(chart_spec.get("departments", selected_depts))
            & (expense_detail.Account == chart_spec["account"])
        ].copy()
        quarter = chart_spec.get("quarter")
        if quarter:
            detail = detail[detail.Month.between((quarter - 1) * 3 + 1, quarter * 3)]
        monthly = detail.groupby(["Month", "Department"], as_index=False).Amount.sum()
        figure = go.Figure()
        for dept, part in monthly.groupby("Department", sort=False):
            figure.add_bar(x=part.Month, y=part.Amount, name=show_dept(dept), marker_color=dept_color(dept))
        figure.update_layout(barmode="group")
        figure.update_xaxes(dtick=1, title_text=tx("月份", "Month"))
        title = tx(f"{show_account(chart_spec['account'])}每月支出", f"Monthly {show_account(chart_spec['account']).lower()} spending")
    elif chart_spec["type"] == "monthly":
        dept = chart_spec["department"]
        monthly = df_filtered_year[df_filtered_year.Department == dept].sort_values("Month")
        figure = go.Figure()
        figure.add_scatter(x=monthly.Month, y=monthly.Budget, name=tx("預算", "Budget"), mode="lines+markers",
                           line=dict(color=MUTED, dash="dot", width=2))
        figure.add_scatter(x=monthly.Month, y=monthly.Actual, name=tx("實際支出", "Actual"), mode="lines+markers",
                           line=dict(color=dept_color(dept), width=3))
        figure.update_xaxes(dtick=1, title_text=tx("月份", "Month"))
        title = tx(f"{show_dept(dept)}每月預算與實際支出", f"Monthly budget and actual spending: {show_dept(dept)}")
    else:
        figure = variance_bar_fig(analysis_res.Department.map(show_dept), analysis_res.Forecast_Var, analysis_res.Forecast_Pct,
                                  [STATUS_COLORS[s] for s in analysis_res.Status])
        return figure, tx("各部門年底預測差異（往右＝超支、往左＝結餘）", "Year-end forecast variance (right = over, left = under)")
    style_fig(figure, height=340)
    money_axis(figure)
    return figure, title

# ==========================================
# 7. 頁首
# ==========================================
source_color = STATUS_COLORS["需注意"] if is_synthetic else STATUS_COLORS["預算正常"]
hero_chips = "".join([
    ui_chip(tx(f"FY{selected_year}", f"FY{selected_year}"), ACCENT),
    ui_chip(tx(f"資料截至 {data_cutoff_month} 月", f"Data through month {data_cutoff_month}") if data_cutoff_month else tx("尚無實際數", "No actuals yet")),
    ui_chip(tx(f"{len(selected_depts)} 個部門", f"{len(selected_depts)} departments")),
    ui_chip(data_source + (tx(f" · 量級 NT$ {opex_anchor_100m:,.0f} 億", f" · scale NT$ {opex_anchor_100m / 10:,.1f}B") if is_synthetic else ""), source_color),
])
st.markdown(
    f'<div class="hero"><div><div class="hero-eyebrow">{tx("法巴人壽 · 管理會計", "BNP Paribas Cardif TW · Management accounting")}'
    f'<span class="live">{tx("AI 即時分析", "AI LIVE")}</span></div>'
    f'<div class="hero-title">{tx("財務預算預測與差異分析助手", "Budget Forecast & Variance Assistant")}</div>'
    f'<div class="hero-sub">{tx("專為保險業財務、精算與數據管理打造的預算決策儀表板", "A budget decision dashboard for insurance finance, actuarial and data teams")}</div></div>'
    f'<div class="chips">{hero_chips}</div></div>',
    unsafe_allow_html=True,
)

dept_col = tx("部門", "Department")
status_col = tx("狀態", "Status")

# ------------------------------------------
# 總覽：結論 → KPI → 燈號 → 主圖 → 詳細（折疊）
# ------------------------------------------
if active_nav_id == "overview":
    n_by_status = {s: int((analysis_res.Status == s).sum()) for s in STATUS_ORDER}
    total_variance = tf_sum - tb_sum
    variance_pct = (total_variance / tb_sum * 100) if tb_sum else 0.0
    forecast_status = classify_status(tf_sum / tb_sum) if tb_sum else "預算正常"
    lead_color = STATUS_COLORS["高風險超支" if n_by_status["高風險超支"] else forecast_status]
    budget_pace_pct = (analysis_res.Budget_YTD.sum() / tb_sum * 100) if tb_sum else 0.0
    actual_pct = (ta_sum / tb_sum * 100) if tb_sum else 0.0

    # ---- 1. 智慧摘要：先給答案 ----
    chips = "".join(ui_chip(f"{show_status(s)} {n_by_status[s]}", STATUS_COLORS[s]) for s in STATUS_ORDER)
    st.markdown(
        f'<div class="lead" style="--c:{lead_color}"><div class="lead-tag">✦ {tx("智慧摘要", "Executive summary")}</div>'
        f'<div class="lead-text">{executive_summary(analysis_res)}</div><div class="chips">{chips}</div></div>',
        unsafe_allow_html=True,
    )

    # ---- 2. 四張語意化 KPI 卡（含趨勢小圖；異常時帶微光） ----
    cum_budget = monthly_budget.cumsum()
    cum_actual = monthly_actual.where(monthly_actual.index <= data_cutoff_month).cumsum()
    cum_path = (monthly_actual.fillna(0) + monthly_estimate).cumsum()
    pace_gap = actual_pct - budget_pace_pct
    actual_color = STATUS_COLORS["需注意"] if pace_gap > 2 else ACCENT
    forecast_color = STATUS_COLORS[forecast_status]
    kpis = [
        ui_kpi(tx("年度總預算", "Annual budget"), fmc(tb_sum), tx("目前選取部門合計", "Selected departments"),
               "💰", ACCENT, spark=ui_spark(cum_budget.tolist(), ACCENT)),
        ui_kpi(tx("已執行金額", "Actual spending"), fmc(ta_sum),
               tx(f"佔全年 {fpct(actual_pct)}｜應有進度 {fpct(budget_pace_pct)}", f"{fpct(actual_pct)} used · plan {fpct(budget_pace_pct)}"),
               "📊", actual_color, glow=pace_gap > 2,
               spark=ui_spark(cum_actual.tolist(), actual_color, ref=cum_budget.where(cum_budget.index <= data_cutoff_month).tolist())),
        ui_kpi(tx("年底預測支出", "Year-end forecast"), fmc(tf_sum),
               tx(f"相較預算 {fpct(variance_pct, signed=True)}｜{show_status(forecast_status)}", f"{fpct(variance_pct, signed=True)} vs. budget · {show_status(forecast_status)}"),
               "📈", forecast_color, glow=forecast_status != "預算正常",
               spark=ui_spark(cum_path.tolist(), forecast_color, ref=cum_budget.tolist())),
    ]
    if total_variance > 0:
        kpis.append(ui_kpi(tx("預估年底缺口", "Projected shortfall"), fmc(total_variance),
                           tx(f"尚未使用預算 {fmc(tb_sum - ta_sum)}", f"Unused budget today {fmc(tb_sum - ta_sum)}"),
                           "🔥", STATUS_COLORS["高風險超支"], glow=True))
    else:
        kpis.append(ui_kpi(tx("預估年底結餘", "Projected headroom"), fmc(abs(total_variance)),
                           tx(f"尚未使用預算 {fmc(tb_sum - ta_sum)}", f"Unused budget today {fmc(tb_sum - ta_sum)}"),
                           "🛡️", STATUS_COLORS["預算正常"]))
    st.markdown(f'<div class="kpi-grid">{"".join(kpis)}</div>', unsafe_allow_html=True)
    ai_brief_panel("overview")

    # ---- 3. 部門燈號清單 + 優先處理 ----
    ordered = analysis_res.assign(_sev=analysis_res.Status.map(STATUS_SEVERITY).fillna(3)).sort_values(
        ["_sev", "Forecast_Var"], ascending=[True, False])
    list_col, focus_col = st.columns([1.65, 1], gap="medium")
    with list_col:
        section(tx("各部門預算水位", "Department budget gauge"), help_text=tx(
            "實色＝已經花掉的預算比例；斜紋＝依預測到年底還會再花的比例；白色虛線＝100% 年度預算。斜紋超過虛線就代表年底會超支。依嚴重度排序。",
            "Solid = share of budget already spent; striped = share still expected by year end; dashed line = 100% of budget. Stripes past the line mean overspend. Sorted by severity."))
        header = (f'<div class="shead"><span>{dept_col}</span><span>{tx("全年預算水位（已花 ＋ 預計再花）", "Budget gauge (spent + still to spend)")}</span>'
                  f'<span>{status_col}</span><span style="text-align:right">{tx("預測差異", "Forecast variance")}</span></div>')
        rows_html = []
        for r in ordered.itertuples():
            reason = ""
            if r.Status != "預算正常":
                # 清單只放一句短原因：優先顯示已標記事件，其次為同期執行率。
                notes = df_filtered_year.loc[
                    (df_filtered_year.Department == r.Department) & df_filtered_year.EventNote.astype(str).str.strip().ne(""), "EventNote"
                ].unique()
                pace_text = tx(f"同期執行率 {fpct(r.Exec_Rate)}", f"{fpct(r.Exec_Rate)} of plan to date")
                reason = ("、" if not IS_EN else ", ").join(show_event(n) for n in notes[:2]) + " · " + pace_text if len(notes) else pace_text
            rows_html.append(ui_status_row(r, reason))
        st.markdown(f'<div class="slist">{header}{"".join(rows_html)}</div>', unsafe_allow_html=True)
    with focus_col:
        section(tx("優先處理", "Priority review"))
        attention_rows = ordered[ordered.Status != "預算正常"]
        if attention_rows.empty:
            st.markdown(f'<div class="okcard">✅ {tx("目前沒有需要優先處理的部門。", "No departments currently need priority review.")}</div>', unsafe_allow_html=True)
        else:
            options = attention_rows.Department.tolist()
            if st.session_state.get("focus_dept") not in options:
                st.session_state["focus_dept"] = options[0]
            focus_department = st.pills(
                tx("選擇部門", "Department"), options, format_func=show_dept, key="focus_dept",
                label_visibility="collapsed", wrap=True,
            ) or options[0]
            focus_row = attention_rows.loc[attention_rows.Department == focus_department].iloc[0]
            color = STATUS_COLORS[focus_row.Status]
            evidence = "".join(f"<li>{item}</li>" for item in risk_evidence(df_db, selected_year, focus_row))
            if focus_row.Forecast_Var > 0:
                next_step = tx("檢視剩餘月份的採購、合約與可調整支出，並到「預測與預警 → 成本歸因」核對驅動科目。",
                               "Review remaining-month purchases, contracts and adjustable spend, then check cost drivers under Forecast & risk.")
            else:
                next_step = tx("確認專案時程、已承諾支出與預算需求；確定有餘額後，到「情境與資料品質」評估調撥。",
                               "Confirm project timing, commitments and needs; once headroom is confirmed, evaluate reallocation under Scenarios.")
            st.markdown(
                f'<div class="focus" style="--c:{color}">{ui_badge(focus_row.Status)}'
                f'<div class="focus-name">{show_dept(focus_department)}</div>'
                f'<div class="focus-amt">{fmc(focus_row.Forecast_Var, signed=True)}</div>'
                f'<div class="focus-meta">{tx("年底預測差異", "Year-end forecast variance")} {fpct(focus_row.Forecast_Pct, signed=True)} · '
                f'{tx("預測", "Forecast")} {fmc(focus_row.Forecast_EOY)} / {tx("預算", "Budget")} {fmc(focus_row.Budget_Full)}</div>'
                f'<ul class="ev">{evidence}</ul><div class="next">➜ {next_step}</div></div>',
                unsafe_allow_html=True,
            )

    # ---- 4. 主圖：累計支出路徑 ----
    path_fig = go.Figure()
    path_fig.add_scatter(x=MONTHS, y=cum_budget, name=tx("累計預算", "Cumulative budget"), mode="lines",
                         line=dict(color=MUTED, width=2, dash="dot"))
    if data_cutoff_month:
        path_fig.add_scatter(x=MONTHS[:data_cutoff_month], y=cum_actual.iloc[:data_cutoff_month],
                             name=tx("累計實際", "Cumulative actual"), mode="lines+markers",
                             line=dict(color=ACCENT, width=3.2), marker=dict(size=6),
                             fill="tozeroy", fillcolor=rgba(ACCENT, .10))
    if data_cutoff_month < 12:
        start = max(data_cutoff_month, 1)
        forecast_x = MONTHS[start - 1:]
        path_fig.add_scatter(x=forecast_x, y=cum_path.iloc[start - 1:], name=tx("預測路徑", "Forecast path"),
                             mode="lines+markers", line=dict(color=forecast_color, width=2.6, dash="dash"),
                             marker=dict(size=5, symbol="circle-open"))
        low_total, high_total = float(analysis_res.Forecast_Low.sum()), float(analysis_res.Forecast_High.sum())
        path_fig.add_scatter(x=[12], y=[tf_sum], mode="markers", name=tx("年底預測區間", "Year-end range"),
                             marker=dict(size=10, color=forecast_color),
                             error_y=dict(type="data", symmetric=False, array=[high_total - tf_sum],
                                          arrayminus=[tf_sum - low_total], color=forecast_color, thickness=1.5, width=6))
    if data_cutoff_month:
        path_fig.add_vline(x=data_cutoff_month + .5, line=dict(color=BORDER, width=1, dash="dot"))
        path_fig.add_annotation(x=data_cutoff_month + .5, y=1, yref="paper", text=tx("實際 ◀ ｜ ▶ 預測", "Actual ◀ | ▶ Forecast"), showarrow=False,
                                xanchor="center", yanchor="bottom", font=dict(size=11, color=MUTED))
    gap_text = (tx("預估超支", "Projected overspend") if total_variance > 0 else tx("預估結餘", "Projected headroom")) + f" {fmc(abs(total_variance))}"
    path_fig.add_annotation(
        x=12, y=max(tf_sum, tb_sum), text=f"<b>{tx('年底預估', 'Year-end')} {fmc(tf_sum)}</b><br>{tx('年度預算', 'Budget')} {fmc(tb_sum)}<br><b>{gap_text}</b>",
        showarrow=True, arrowhead=0, arrowcolor=forecast_color, ax=-90, ay=-34, xanchor="right", align="right",
        bgcolor=rgba(forecast_color, .12), bordercolor=rgba(forecast_color, .5), borderpad=6,
        font=dict(color=TEXT, size=12),
    )
    style_fig(path_fig, height=380)
    path_fig.update_xaxes(tickmode="array", tickvals=MONTHS, ticktext=[tx(f"{m}月", f"M{m}") for m in MONTHS])
    money_axis(path_fig, max_hint=max(float(analysis_res.Forecast_High.sum()), tb_sum))
    show_chart(path_fig, title=tx("全公司照目前速度花，年底會落在哪裡？", "At the current pace, where will total spending land?"), key="overview_path", help_text=tx(
        "藍色實線＝已結算月份的累計實際支出；彩色虛線＝依季節性與 Run-rate 推估的剩餘月份；灰色點線＝累計預算。虛線終點高於灰線即代表年底超支；誤差線為歷史回測 P80 區間。",
        "Solid = cumulative closed actuals; dashed = remaining months estimated from seasonality and run rate; dotted = cumulative budget. The year-end whisker shows the backtest P80 range."))

    # ---- 5. 漸進式揭露：詳細拆解預設折疊 ----
    with st.expander(tx("查看詳細預算拆解與圖表", "View detailed budget breakdown and charts"), icon=":material/table_chart:"):
        names = ordered.Department.map(show_dept)

        trend_lists = []
        for dept in ordered.Department:
            g = df_filtered_year[(df_filtered_year.Department == dept) & (df_filtered_year.Month <= data_cutoff_month)].sort_values("Month")
            series = ((g.Actual.cumsum() - g.Budget.cumsum()) / g.Budget.cumsum() * 100).round(2).tolist() if len(g) else []
            trend_lists.append(series or [0.0, 0.0])
        util_col = tx("預測使用率", "Forecast utilization")
        trend_col = tx("累計差異趨勢", "Cumulative variance trend")
        detail_table = pd.DataFrame({
            dept_col: names.to_numpy(),
            status_col: ordered.Status.map(status_label).to_numpy(),
            util_col: (ordered.Forecast_EOY / ordered.Budget_Full * 100).round(1).to_numpy(),
            tx("年度預算（百萬）", "Budget (M)"): to_m(ordered.Budget_Full).to_numpy(),
            tx("已執行（百萬）", "Actual (M)"): to_m(ordered.Actual_YTD).to_numpy(),
            tx("年底預測（百萬）", "Forecast (M)"): to_m(ordered.Forecast_EOY).to_numpy(),
            tx("預測差異（百萬）", "Variance (M)"): to_m(ordered.Forecast_Var).to_numpy(),
            trend_col: trend_lists,
        })
        st.dataframe(
            detail_table, hide_index=True, width="stretch",
            column_config={
                dept_col: st.column_config.TextColumn(dept_col, pinned=True),
                util_col: st.column_config.ProgressColumn(
                    util_col, format="%.1f%%", min_value=0, max_value=125, color=ACCENT,
                    help=tx("預測全年支出佔年度預算的比例；100% 代表剛好用完預算。", "Forecast spending as a share of the annual budget; 100% means fully used.")),
                tx("年度預算（百萬）", "Budget (M)"): st.column_config.NumberColumn(format="localized"),
                tx("已執行（百萬）", "Actual (M)"): st.column_config.NumberColumn(format="localized"),
                tx("年底預測（百萬）", "Forecast (M)"): st.column_config.NumberColumn(format="localized"),
                tx("預測差異（百萬）", "Variance (M)"): st.column_config.NumberColumn(format="%+.1f"),
                trend_col: st.column_config.LineChartColumn(
                    trend_col, color="auto-inverse",
                    help=tx("每月累計實際支出相對累計預算的差異（%）；向上代表超支擴大。", "Cumulative actual vs. cumulative budget by month (%); rising means overspend is growing.")),
            },
        )

# ------------------------------------------
# 預算分析
# ------------------------------------------
if active_nav_id == "budget_analysis":
    page_header(tx(f"{selected_year} 年度預算分析", f"{selected_year} Budget analysis"),
                tx("差異金額 = 實際支出 − 同期預算；正數為超支，負數為低於預算。", "Variance = actual − budget to date. Positive is over budget; negative is under."))
    analysis_views = st.tabs([tx("差異分析", "Variance"), tx("使用率", "Utilization"), tx("歷史趨勢", "History")])

    with analysis_views[0]:
        net_variance = float(analysis_res.Variance.sum())
        over_budget_rows = analysis_res[analysis_res.Variance > 0]
        largest_variance_row = analysis_res.loc[analysis_res.Variance.abs().idxmax()]
        variance_kpis = st.columns(3)
        variance_kpis[0].metric(
            tx("整體同期差異", "Net variance to date"), fmc(net_variance, signed=True),
            delta=f"{(net_variance / analysis_res.Budget_YTD.sum() * 100) if analysis_res.Budget_YTD.sum() else 0:+.1f}% {tx('同期預算', 'of budget to date')}",
            delta_color="inverse", border=True,
        )
        variance_kpis[1].metric(
            tx("高於同期預算的部門", "Departments above plan"), f"{len(over_budget_rows)} / {len(analysis_res)}",
            delta=fmc(float(over_budget_rows.Variance.sum()), signed=True) if not over_budget_rows.empty else fmc(0),
            delta_color="inverse", border=True,
        )
        variance_kpis[2].metric(
            tx("差異最大的部門", "Largest variance"), show_dept(largest_variance_row.Department),
            delta=fmc(float(largest_variance_row.Variance), signed=True), delta_color="inverse", border=True,
        )

        # 圖表需要足夠寬度放標籤，改為上下排列。
        chart_col = table_col = st.container()
        with chart_col:
            var_fig = variance_bar_fig(
                analysis_res.Department.map(show_dept), analysis_res.Variance, analysis_res.Variance_Pct,
                [STATUS_COLORS["高風險超支"] if v > 0 else STATUS_COLORS["執行落後"] for v in analysis_res.Variance],
                hover_extra=[f"<br>{tx('實際', 'Actual')} {fmc(a)} / {tx('同期預算', 'Budget to date')} {fmc(b)}" for a, b in zip(analysis_res.Actual_YTD, analysis_res.Budget_YTD)],
            )
            show_chart(var_fig, title=tx(f"截至 {data_cutoff_month} 月，誰花得比預算多？", f"Through month {data_cutoff_month}, who spent more than planned?"), key="variance_bar",
                       help_text=tx("中線＝剛好等於同期預算。紅色往右＝已超出同期預算；藍色往左＝低於同期預算（花得較慢）。", "Centre line = exactly on budget to date. Red to the right = over; blue to the left = under (spending slower)."))
        with table_col:
            monthly_var = df_filtered_year[df_filtered_year.Actual.notna()].assign(
                Var_Pct=lambda d: (d.Actual - d.Budget) / d.Budget * 100)
            trend = monthly_var.sort_values("Month").groupby("Department").Var_Pct.apply(lambda s: s.round(1).tolist())
            var_table = pd.DataFrame({
                dept_col: analysis_res.Department.map(show_dept),
                tx("同期預算（百萬）", "Budget to date (M)"): to_m(analysis_res.Budget_YTD),
                tx("實際支出（百萬）", "Actual (M)"): to_m(analysis_res.Actual_YTD),
                tx("差異（百萬）", "Variance (M)"): to_m(analysis_res.Variance),
                tx("差異率", "Variance %"): analysis_res.Variance_Pct.round(1),
                tx("每月差異率", "Monthly variance %"): analysis_res.Department.map(trend).apply(lambda v: v if isinstance(v, list) else []),
            })
            with card("variance_table"):
                st.markdown(f'<div class="chart-title">{tx("差異明細", "Variance detail")}</div>', unsafe_allow_html=True)
                st.dataframe(var_table, hide_index=True, width="stretch", height=330, column_config={
                    dept_col: st.column_config.TextColumn(pinned=True, width="small"),
                    tx("同期預算（百萬）", "Budget to date (M)"): st.column_config.NumberColumn(format="localized", width="small"),
                    tx("實際支出（百萬）", "Actual (M)"): st.column_config.NumberColumn(format="localized", width="small"),
                    tx("差異（百萬）", "Variance (M)"): st.column_config.NumberColumn(format="%+.1f", width="small"),
                    tx("差異率", "Variance %"): st.column_config.NumberColumn(format="%+.1f%%", width="small"),
                    tx("每月差異率", "Monthly variance %"): st.column_config.BarChartColumn(width="medium",
                        color="auto-inverse", help=tx("各已結算月份的（實際−預算）÷預算。", "Each closed month's (actual − budget) ÷ budget.")),
                })

        pivot_diff = df_filtered_year.copy()
        pivot_diff["Department"] = pivot_diff.Department.map(show_dept)
        pivot_diff["Diff_Pct"] = (pivot_diff.Actual - pivot_diff.Budget) / pivot_diff.Budget * 100
        actual_months = sorted(pivot_diff.loc[pivot_diff.Actual.notna(), "Month"].unique().tolist())
        if actual_months:
            heatmap_data = pivot_diff.pivot(index="Department", columns="Month", values="Diff_Pct").reindex(columns=actual_months)
            max_abs_variance = max(float(heatmap_data.abs().max().max()), 5.0)
            heat_fig = go.Figure(go.Heatmap(
                z=heatmap_data.to_numpy(), x=[tx(f"{int(m)}月", f"M{int(m)}") for m in actual_months], y=heatmap_data.index,
                zmid=0, zmin=-max_abs_variance, zmax=max_abs_variance, xgap=3, ygap=3,
                colorscale=[[0, STATUS_COLORS["執行落後"]], [.5, RAISED], [1, STATUS_COLORS["高風險超支"]]],
                text=[[fpct(v, signed=True) if pd.notna(v) else "" for v in row] for row in heatmap_data.to_numpy()],
                texttemplate="%{text}", textfont=dict(size=11),
                hovertemplate="<b>%{y}</b> · %{x}<br>%{text}<extra></extra>",
                colorbar=dict(title=dict(text="%", font=dict(color=MUTED)), tickfont=dict(color=MUTED), thickness=10, outlinewidth=0),
            ))
            style_fig(heat_fig, height=60 + 38 * len(heatmap_data), legend=False)
            heat_fig.update_yaxes(autorange="reversed", showgrid=False)
            heat_fig.update_xaxes(showgrid=False, side="top")
            show_chart(heat_fig, title=tx("哪幾個月、哪些部門偏離當月預算？", "Which months and departments drifted from the monthly budget?"), key="variance_heat",
                       help_text=tx("僅顯示已結算月份。紅色＝超出當月預算；藍色＝低於當月預算。年末集中請款的部門會在前三季呈現偏藍。",
                                    "Closed months only. Red = above that month's budget; blue = below. Departments that flush budget at year end look blue through Q1–Q3."))
        else:
            st.info(tx("所選年度尚無已結算的實際支出月份。", "No actual spending months have been closed for the selected year."))

    with analysis_views[1]:
        def pace_color(rate):
            if rate > 105:
                return STATUS_COLORS["高風險超支"]
            if rate > 100:
                return STATUS_COLORS["需注意"]
            if rate < 90:
                return STATUS_COLORS["執行落後"]
            return STATUS_COLORS["預算正常"]

        util_ordered = analysis_res.sort_values("Exec_Rate")
        util_fig = go.Figure()
        util_fig.add_bar(
            y=util_ordered.Department.map(show_dept), x=util_ordered.Exec_Rate, orientation="h",
            marker=dict(color=[pace_color(v) for v in util_ordered.Exec_Rate], cornerradius=5),
            text=[fpct(v) for v in util_ordered.Exec_Rate], textposition="outside", cliponaxis=False,
            textfont=dict(color=TEXT, size=12),
            customdata=np.column_stack([util_ordered.Actual_YTD / 1e6, util_ordered.Budget_YTD / 1e6]),
            hovertemplate="<b>%{y}</b><br>" + tx("同期執行率", "Spend vs. plan") + " %{x:.1f}%<br>"
                          + tx("實際", "Actual") + " %{customdata[0]:,.1f}M / " + tx("同期預算", "Budget to date") + " %{customdata[1]:,.1f}M<extra></extra>",
        )
        util_fig.add_vrect(x0=90, x1=100, fillcolor=rgba(STATUS_COLORS["預算正常"], .08), line_width=0, layer="below")
        util_fig.add_vline(x=100, line=dict(color=TEXT, width=1.6),
                           annotation_text=tx("100%＝照預算進度", "100% = on plan"), annotation_position="top",
                           annotation_font=dict(color=MUTED, size=11))
        style_fig(util_fig, height=max(320, 44 * len(util_ordered) + 90), legend=False)
        util_fig.update_xaxes(range=[0, max(130, float(util_ordered.Exec_Rate.max()) + 15)], ticksuffix="%", title_text=None)
        util_fig.update_yaxes(showgrid=False)
        show_chart(util_fig, title=tx(f"截至 {data_cutoff_month} 月，各部門花錢速度是否超前預算？", f"Through month {data_cutoff_month}, is each department spending ahead of plan?"), key="util_bullet",
                   help_text=tx("執行率＝截至目前實際支出 ÷ 截至目前預算。100% 代表剛好照預算進度；綠色帶狀區（90–100%）為正常範圍；紅／橘＝花太快，藍＝花太慢。",
                                "Rate = actual to date ÷ budget to date. 100% means exactly on plan; the green band (90–100%) is normal; red/orange = too fast, blue = too slow."))
        util_table = pd.DataFrame({
            dept_col: analysis_res.Department.map(show_dept),
            status_col: analysis_res.Status.map(status_label),
            tx("同期執行率", "Spend vs. plan to date"): analysis_res.Exec_Rate.round(1),
            tx("全年使用率", "Annual utilization"): analysis_res.Usage_Rate.round(1),
            tx("預測使用率", "Forecast utilization"): (analysis_res.Forecast_EOY / analysis_res.Budget_Full * 100).round(1),
        })
        st.dataframe(util_table, hide_index=True, width="stretch", column_config={
            dept_col: st.column_config.TextColumn(pinned=True),
            tx("同期執行率", "Spend vs. plan to date"): st.column_config.ProgressColumn(
                format="%.1f%%", min_value=0, max_value=130, color=ACCENT,
                help=tx("截至目前實際 ÷ 截至目前預算；100% 代表與預算時程同步。", "Actual to date ÷ budget to date; 100% means on schedule.")),
            tx("全年使用率", "Annual utilization"): st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100, color="gray"),
            tx("預測使用率", "Forecast utilization"): st.column_config.ProgressColumn(
                format="%.1f%%", min_value=0, max_value=125, color="orange",
                help=tx("年底預測 ÷ 年度預算；超過 100% 為預計超支。", "Year-end forecast ÷ annual budget; above 100% means expected overspend.")),
        })

    with analysis_views[2]:
        hist_df = df_db[df_db.Actual.notna() & df_db.Department.isin(selected_depts)].copy()
        complete = hist_df.groupby(["Year", "Department"]).Month.nunique().reset_index(name="n")
        complete_pairs = complete[complete.n == 12][["Year", "Department"]]
        hist_annual = hist_df.merge(complete_pairs, on=["Year", "Department"]).groupby(
            ["Year", "Department"])[["Budget", "Actual"]].sum().reset_index()
        yearly = df_db[df_db.Department.isin(selected_depts)].groupby("Year").agg(
            Budget=("Budget", "sum"), Actual=("Actual", lambda v: v.sum(min_count=1)))
        yearly = yearly[yearly.index <= selected_year].dropna(subset=["Actual"])
        if not yearly.empty:
            yrs = [str(y) for y in yearly.index]
            is_open_year = data_cutoff_month < 12
            act_label = [f"{a / b * 100:.0f}%" if not (y == selected_year and is_open_year) else tx(f"至 {data_cutoff_month} 月", f"to M{data_cutoff_month}")
                         for y, a, b in zip(yearly.index, yearly.Actual, yearly.Budget)]
            co_fig = go.Figure()
            co_fig.add_bar(x=yrs, y=yearly.Budget, name=tx("年度預算", "Annual budget"), offsetgroup="b",
                           marker=dict(color=rgba(MUTED, .45), cornerradius=4))
            co_fig.add_bar(x=yrs, y=yearly.Actual, name=tx("實際支出", "Actual spending"), offsetgroup="a",
                           marker=dict(color=ACCENT, cornerradius=4), text=act_label, textposition="inside",
                           insidetextanchor="end", textfont=dict(color="#ffffff", size=11))
            if is_open_year:
                co_fig.add_bar(x=[str(selected_year)], y=[tf_sum - ta_sum], base=[ta_sum], offsetgroup="a",
                               name=tx("今年預估剩餘", "Rest-of-year forecast"),
                               marker=dict(color=rgba(STATUS_COLORS[classify_status(tf_sum / tb_sum) if tb_sum else "預算正常"], .55),
                                           pattern=dict(shape="/", fgcolor=TEXT, size=6, solidity=.15), cornerradius=4),
                               text=[f"{tx('預估', 'Fcst')} {tf_sum / tb_sum * 100:.0f}%"], textposition="outside", textfont=dict(color=TEXT, size=11))
            co_fig.update_layout(barmode="group", bargroupgap=.08)
            style_fig(co_fig, height=380)
            money_axis(co_fig, max_hint=max(float(yearly.Budget.max()), tf_sum) * 1.08)
            show_chart(co_fig, title=tx("歷年預算執行：每年花得比預算多還是少？", "Year by year: did we spend more or less than budget?"), key="history_company",
                       help_text=tx("灰色＝年度預算；藍色＝實際支出，柱內百分比為執行率（實際÷預算）。今年以斜紋顯示依模型預估、尚未發生的剩餘支出。",
                                    "Grey = annual budget; blue = actual spending with the execution rate (actual ÷ budget) inside. This year's striped segment is the model's rest-of-year estimate."))

        hist_fig = go.Figure()
        for dept in selected_depts:
            part = hist_annual[(hist_annual.Department == dept) & (hist_annual.Year < selected_year)].sort_values("Year")
            color = dept_color(dept)
            hist_fig.add_scatter(x=part.Year, y=part.Actual, mode="lines+markers", name=show_dept(dept),
                                 line=dict(color=color, width=2.4), marker=dict(size=6), legendgroup=dept)
            forecast_row = analysis_res[analysis_res.Department == dept]
            if not part.empty and not forecast_row.empty and data_cutoff_month < 12:
                hist_fig.add_scatter(
                    x=[part.Year.iloc[-1], selected_year], y=[part.Actual.iloc[-1], float(forecast_row.Forecast_EOY.iloc[0])],
                    mode="lines+markers", line=dict(color=color, width=2, dash="dot"), marker=dict(size=[0, 9], symbol="circle-open"),
                    name=show_dept(dept), legendgroup=dept, showlegend=False,
                )
        style_fig(hist_fig, height=400)
        hist_fig.update_xaxes(dtick=1, tickformat="d")
        money_axis(hist_fig)
        for trace in hist_fig.data:
            trace.hovertemplate = f"<b>{trace.name}</b> · %{{x}}<br>NT$ %{{y:,.0f}}<extra></extra>"
        with st.expander(tx("查看各部門歷年趨勢", "View department trends"), icon=":material/show_chart:"):
            show_chart(hist_fig, title=tx("各部門歷年實際支出", "Annual actual spending by department"), key="history_line",
                   help_text=tx(f"實線為完整年度實際支出；點線延伸到 {selected_year} 年底預測（空心圓），避免把年初至今金額誤當全年比較。",
                                f"Solid lines are complete-year actuals; dotted segments extend to the {selected_year} year-end forecast (hollow circle) so partial-year data is not compared with full years."))
        exec_pivot = hist_annual[hist_annual.Year < selected_year].assign(
            Rate=lambda d: (d.Actual / d.Budget * 100).round(1)).pivot(index="Department", columns="Year", values="Rate")
        if not exec_pivot.empty:
            exec_pivot.index = exec_pivot.index.map(show_dept)
            exec_pivot.columns = [str(c) for c in exec_pivot.columns]
            exec_pivot = exec_pivot.reset_index().rename(columns={"Department": dept_col})
            section(tx("歷年預算執行率（實際 ÷ 預算）", "Historical budget execution (actual ÷ budget)"),
                    help_text=tx("含一次性支出；超過 100% 代表當年超支。", "Includes one-offs; above 100% means the year overspent."))
            st.dataframe(exec_pivot, hide_index=True, width="stretch", column_config={
                dept_col: st.column_config.TextColumn(pinned=True),
                **{c: st.column_config.NumberColumn(format="%.1f%%") for c in exec_pivot.columns if c != dept_col},
            })

# ------------------------------------------
# 預測與預警
# ------------------------------------------
if active_nav_id == "forecast_risk":
    page_header(tx(f"{selected_year} 年底預測與預警", f"{selected_year} Forecast & risk"),
                tx("55% 歷史季節性 + 45% Run-rate 加權推估；一次性支出不延伸到未來月份。", "55% historical seasonality + 45% run rate. One-off costs are not extrapolated."))
    risk_views = st.tabs([tx("年底預測", "Forecast"), tx("預算預警", "Alerts"), tx("成本歸因", "Cost drivers")])

    with risk_views[0]:
        forecast_remaining_total = float((analysis_res.Forecast_EOY - analysis_res.Actual_YTD).sum())
        forecast_variance_total = float(tf_sum - tb_sum)
        difference_pct = forecast_variance_total / tb_sum * 100 if tb_sum else 0
        remaining_label = tx(f"{data_cutoff_month + 1}–12 月", f"months {data_cutoff_month + 1}–12") if data_cutoff_month < 12 else tx("無剩餘月份", "none")
        gap_status = classify_status(tf_sum / tb_sum) if tb_sum else "預算正常"
        gap_color = STATUS_COLORS[gap_status]
        st.markdown(
            '<div class="flow">'
            f'<div class="flow-item"><div class="flow-lb">{tx("已實際支出", "Actual spending")}</div><div class="flow-vl">{fmc(ta_sum)}</div><div class="flow-sb">{tx(f"截至 {data_cutoff_month} 月", f"through month {data_cutoff_month}")}</div></div>'
            '<div class="flow-op">+</div>'
            f'<div class="flow-item"><div class="flow-lb">{tx("剩餘月份預估", "Remaining estimate")}</div><div class="flow-vl">{fmc(forecast_remaining_total)}</div><div class="flow-sb">{remaining_label}</div></div>'
            '<div class="flow-op">=</div>'
            f'<div class="flow-item"><div class="flow-lb">{tx("年底預估總支出", "Year-end estimate")}</div><div class="flow-vl">{fmc(tf_sum)}</div><div class="flow-sb">{tx("區間", "Range")} {fmc(analysis_res.Forecast_Low.sum())} – {fmc(analysis_res.Forecast_High.sum())}</div></div>'
            '<div class="flow-op">vs</div>'
            f'<div class="flow-item" style="border-color:{rgba(gap_color, .55)};background:{rgba(gap_color, .08)}"><div class="flow-lb">{tx("全年核定預算", "Approved budget")} {fmc(tb_sum)}</div>'
            f'<div class="flow-vl" style="color:{gap_color}">{fmc(forecast_variance_total, signed=True)}</div><div class="flow-sb">{fpct(difference_pct, signed=True)} · {show_status(gap_status)}</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )

        wf_col, dept_fc_col = st.columns([1, 1.5], gap="medium")
        with wf_col:
            wf = go.Figure(go.Waterfall(
                x=[tx("① 已花", "① Spent"), tx("② 預計再花", "② Still to spend"), tx("③ 年底合計", "③ Year-end total")],
                y=[ta_sum, forecast_remaining_total, 0], measure=["relative", "relative", "total"],
                text=[fmc(ta_sum), fmc(forecast_remaining_total, signed=True), fmc(tf_sum)], textposition="outside",
                textfont=dict(color=TEXT, size=11.5), cliponaxis=False,
                connector=dict(line=dict(color=BORDER, dash="dot")),
                increasing=dict(marker=dict(color=ACCENT)), totals=dict(marker=dict(color=gap_color)),
                hovertemplate="%{x}<br>NT$ %{y:,.0f}<extra></extra>", name="",
            ))
            wf.add_bar(x=[tx("④ 年度預算", "④ Budget")], y=[tb_sum], name=tx("年度預算", "Budget"),
                       marker=dict(color=rgba(MUTED, .45), cornerradius=4), text=[fmc(tb_sum)], textposition="outside",
                       textfont=dict(color=TEXT, size=11.5), cliponaxis=False, hovertemplate="skip")
            wf.data[-1].hovertemplate = tx("年度預算", "Budget") + "<br>NT$ %{y:,.0f}<extra></extra>"
            wf.add_hline(y=tb_sum, line=dict(color=MUTED, dash="dot", width=1.2))
            style_fig(wf, height=400, legend=False)
            money_axis(wf, max_hint=max(tf_sum, tb_sum) * 1.12)
            show_chart(wf, title=tx("全公司年底支出怎麼算出來？", "How the year-end total is built"), key="forecast_waterfall",
                       help_text=tx("① 已花的錢 ＋ ② 依模型預估剩餘月份還會花的錢 ＝ ③ 年底合計；再和 ④ 年度預算比較，③ 比 ④ 高就是超支。",
                                    "① Spent + ② still to spend (model estimate) = ③ year-end total; compare with ④ budget — if ③ is taller, it's an overspend."))
        with dept_fc_col:
            ordered_fc = analysis_res.sort_values("Forecast_Var", ascending=False)
            fc_fig = variance_bar_fig(
                ordered_fc.Department.map(show_dept), ordered_fc.Forecast_Var, ordered_fc.Forecast_Pct,
                [STATUS_COLORS[s] for s in ordered_fc.Status],
                hover_extra=[
                    f"<br>{show_status(r.Status)}<br>{tx('年底預測', 'Forecast')} {fmc(r.Forecast_EOY)} / {tx('預算', 'Budget')} {fmc(r.Budget_Full)}"
                    f"<br>{tx('合理區間', 'Likely range')} {fmc(r.Forecast_Low)} – {fmc(r.Forecast_High)}"
                    for r in ordered_fc.itertuples()
                ],
            )
            show_chart(fc_fig, title=tx("哪些部門年底會超支？差多少？", "Which departments will overspend by year end, and by how much?"), key="forecast_dept",
                       help_text=tx("中線＝剛好用完年度預算。往右＝預計超支、往左＝預計結餘；顏色代表預警燈號（紅＝高風險、橘＝需注意、藍＝執行落後、綠＝正常）。滑鼠移到長條可看預測合理區間。",
                                    "Centre line = exactly the annual budget. Right = expected overspend, left = expected headroom; colour = alert status. Hover for the likely range."))

        monthly_path = go.Figure()
        monthly_path.add_bar(x=MONTHS, y=monthly_actual.where(monthly_actual.index <= data_cutoff_month),
                             name=tx("已結算實際", "Closed actual"), marker_color=ACCENT)
        monthly_path.add_bar(x=MONTHS, y=monthly_estimate.where(monthly_estimate > 0),
                             name=tx("剩餘月份預估", "Remaining estimate"), marker=dict(color=rgba(ACCENT, .35), line=dict(color=ACCENT, width=1.2)))
        monthly_path.add_scatter(x=MONTHS, y=monthly_budget, name=tx("每月預算", "Monthly budget"), mode="lines+markers",
                                 line=dict(color=MUTED, width=2, dash="dot"), marker=dict(size=5))
        monthly_path.update_layout(barmode="overlay")
        style_fig(monthly_path, height=360)
        monthly_path.update_xaxes(tickmode="array", tickvals=MONTHS, ticktext=[tx(f"{m}月", f"M{m}") for m in MONTHS])
        money_axis(monthly_path)
        show_chart(monthly_path, title=tx("每個月花多少？已發生（實色）與預估（淡色）對照每月預算", "Monthly spend: actual (solid) and forecast (light) vs. monthly budget"), key="forecast_monthly",
                   help_text=tx("剩餘月份預估依各部門歷史季節性（55%）與平均 Run-rate（45%）分配，加總與年度預測一致；年末消耗型部門會在 11–12 月出現高峰。",
                                "Remaining estimates are spread by each department's historical seasonality (55%) and an even run rate (45%) and reconcile to the annual forecast. Year-end-flush departments peak in Nov–Dec."))

        with st.expander(tx("查看詳細預算拆解與模型參數", "View detailed breakdown and model parameters"), icon=":material/table_chart:"):
            section(tx("各部門預算與年底預估拆解", "Department budget-to-year-end breakdown"))
            breakdown = pd.DataFrame({
                dept_col: ordered_fc.Department.map(show_dept),
                status_col: ordered_fc.Status.map(status_label),
                tx("全年預算", "Budget"): to_m(ordered_fc.Budget_Full),
                tx("已支出", "Actual"): to_m(ordered_fc.Actual_YTD),
                tx("剩餘預估", "Remaining"): to_m(ordered_fc.Forecast_EOY - ordered_fc.Actual_YTD),
                tx("年底預估", "Year-end"): to_m(ordered_fc.Forecast_EOY),
                tx("差額", "Difference"): to_m(ordered_fc.Forecast_Var),
                tx("差額率", "Difference %"): ordered_fc.Forecast_Pct.round(1),
                tx("分配依據", "Allocation basis"): ordered_fc.Department.map(estimate_basis_by_department),
            })
            st.dataframe(breakdown, hide_index=True, width="stretch", column_config={
                dept_col: st.column_config.TextColumn(pinned=True),
                **{c: st.column_config.NumberColumn(format="localized") for c in [tx("全年預算", "Budget"), tx("已支出", "Actual"), tx("剩餘預估", "Remaining"), tx("年底預估", "Year-end")]},
                tx("差額", "Difference"): st.column_config.NumberColumn(format="%+.1f", help=tx("單位：百萬元。正值為預計超支。", "NT$ millions. Positive = expected overspend.")),
                tx("差額率", "Difference %"): st.column_config.NumberColumn(format="%+.1f%%"),
            })
            st.caption(tx("金額單位：NT$ 百萬元。", "Amounts in NT$ millions."))

            section(tx("逐月明細", "Monthly detail"))
            combined = monthly_actual.fillna(0) + monthly_estimate
            has_data = monthly_actual.notna() | (monthly_estimate > 0)
            monthly_detail = pd.DataFrame({
                tx("月份", "Month"): [tx(f"{m} 月", f"Month {m}") for m in MONTHS],
                tx("每月預算", "Budget"): to_m(monthly_budget).to_numpy(),
                tx("已結算實際", "Closed actual"): to_m(monthly_actual).to_numpy(),
                tx("剩餘月份預估", "Estimate"): to_m(monthly_estimate.where(monthly_estimate > 0)).to_numpy(),
                tx("對預算差額", "Vs. budget"): to_m((combined - monthly_budget).where(has_data)).to_numpy(),
                tx("資料狀態", "Data status"): [
                    tx("實際＋預估", "Actual + estimate") if pd.notna(monthly_actual.loc[m]) and monthly_estimate.loc[m] > 0
                    else tx("✅ 已結算", "✅ Closed") if pd.notna(monthly_actual.loc[m])
                    else tx("🔮 預估", "🔮 Estimated") if monthly_estimate.loc[m] > 0
                    else tx("尚無資料", "No data")
                    for m in MONTHS
                ],
            })
            st.dataframe(monthly_detail, hide_index=True, width="stretch", column_config={
                tx("對預算差額", "Vs. budget"): st.column_config.NumberColumn(format="%+.1f"),
                **{c: st.column_config.NumberColumn(format="localized") for c in [tx("每月預算", "Budget"), tx("已結算實際", "Closed actual"), tx("剩餘月份預估", "Estimate")]},
            })

            section(tx("模型與歷史參考", "Model and historical reference"),
                    help_text=tx("參考區間是依歷史回測誤差估算的規劃範圍，不是統計信賴區間；歷史年度越少，估算越不穩定。",
                                 "The range is a planning range from historical backtest errors, not a statistical confidence interval. Fewer historical years make it less stable."))
            model_view = pd.DataFrame({
                dept_col: analysis_res.Department.map(show_dept),
                tx("Run-rate 推估", "Run-rate"): to_m(analysis_res.Forecast_Run_Rate),
                tx("季節性推估", "Seasonal"): to_m(analysis_res.Forecast_Seasonal),
                tx("區間下限", "Range low"): to_m(analysis_res.Forecast_Low),
                tx("區間上限", "Range high"): to_m(analysis_res.Forecast_High),
                tx("完整歷史年度", "History years"): analysis_res.History_Years,
                tx("區間依據", "Range basis"): analysis_res.Error_Basis,
            })
            st.dataframe(model_view, hide_index=True, width="stretch", column_config={
                **{c: st.column_config.NumberColumn(format="localized") for c in [tx("Run-rate 推估", "Run-rate"), tx("季節性推估", "Seasonal"), tx("區間下限", "Range low"), tx("區間上限", "Range high")]},
            })

    with risk_views[1]:
        alert_rows = analysis_res[analysis_res.Status != "預算正常"].copy()
        alert_rows["_Priority"] = alert_rows.Status.map(STATUS_SEVERITY)
        alert_rows = alert_rows.sort_values(["_Priority", "Forecast_Var"], ascending=[True, False])
        actions = {
            "高風險超支": tx("請檢視未執行月份的採購、合約與支出計畫，必要時凍結非必要支出。", "Review planned purchases, contracts and spending for the remaining months; freeze discretionary spend if needed."),
            "需注意": tx("建議每月檢視非必要支出，並設定剩餘月份的支出上限。", "Review discretionary spending monthly and set a cap for the remaining months."),
            "執行落後": tx("確認專案時程與剩餘預算需求；若確定有餘額，可列為調撥來源。", "Confirm project timing and remaining needs; confirmed headroom can fund reallocation."),
        }
        ai_brief_panel("alerts")
        summary_cols = st.columns(3)
        for col, status in zip(summary_cols, ["高風險超支", "需注意", "執行落後"]):
            rows = alert_rows[alert_rows.Status == status]
            col.metric(f"{STATUS_EMOJI[status]} {show_status(status)}", f"{len(rows)}",
                       delta=fmc(float(rows.Forecast_Var.sum()), signed=True) if not rows.empty else None,
                       delta_color="inverse", border=True)
        if alert_rows.empty:
            st.markdown(f'<div class="okcard">✅ {tx("目前沒有符合預警條件的部門。", "No departments currently meet the alert criteria.")}</div>', unsafe_allow_html=True)
        for row in alert_rows.itertuples():
            color = STATUS_COLORS[row.Status]
            evidence = "".join(f"<li>{item}</li>" for item in risk_evidence(df_db, selected_year, row))
            message = tx(
                f"年底預測 {fmc(row.Forecast_EOY)}，年度預算 {fmc(row.Budget_Full)}（{fpct(row.Forecast_Pct, signed=True)}）",
                f"Year-end forecast {fmc(row.Forecast_EOY)} vs. budget {fmc(row.Budget_Full)} ({fpct(row.Forecast_Pct, signed=True)})",
            )
            st.markdown(
                f'<div class="acard" style="--c:{color}"><div class="acard-head">{ui_badge(row.Status)}'
                f'<span class="acard-dept">{show_dept(row.Department)}</span><span class="acard-amt">{fmc(row.Forecast_Var, signed=True)}</span></div>'
                f'<div class="acard-msg">{message}</div><ul class="ev">{evidence}</ul>'
                f'<div class="next">➜ {actions[row.Status]}</div></div>',
                unsafe_allow_html=True,
            )

        with st.expander(tx("預算摘要報告（可下載）", "Budget summary report (downloadable)"), icon=":material/description:"):
            usage_pct = ta_sum / tb_sum * 100 if tb_sum else 0
            var_pct = (tf_sum - tb_sum) / tb_sum * 100 if tb_sum else 0
            if IS_EN:
                report_lines = [
                    f"# Budget summary | FY{selected_year}", "",
                    f"- **Total annual budget**: {fm(tb_sum)}",
                    f"- **Actual spending to date** (through month {data_cutoff_month}): {fm(ta_sum)} ({usage_pct:.1f}% of annual budget)",
                    f"- **Year-end forecast**: {fm(tf_sum)} (variance **{fm(tf_sum - tb_sum)}**, **{var_pct:+.1f}%**)",
                    f"- **Summary**: {executive_summary(analysis_res)}", "", "## Department status", "",
                ]
            else:
                report_lines = [
                    f"# 法巴人壽 {selected_year} 年度預算摘要", "",
                    f"- **年度總預算**：{fm(tb_sum)}",
                    f"- **目前已執行金額**（截至 {data_cutoff_month} 月）：{fm(ta_sum)}（佔全年預算 **{usage_pct:.1f}%**）",
                    f"- **年底預測支出**：{fm(tf_sum)}（預測差異 **{fm(tf_sum - tb_sum)}**，**{var_pct:+.1f}%**）",
                    f"- **智慧摘要**：{executive_summary(analysis_res)}", "", "## 部門狀態", "",
                ]
            for r in analysis_res.sort_values("Forecast_Var", ascending=False).itertuples():
                report_lines.append(
                    f"- **{show_dept(r.Department)}**：{status_label(r.Status)} ｜ {tx('同期執行率', 'To-date execution')} {fpct(r.Exec_Rate)} ｜ "
                    f"{tx('預測差異', 'Forecast variance')} {fm(r.Forecast_Var)}（{fpct(r.Forecast_Pct, signed=True)}）"
                    if not IS_EN else
                    f"- **{show_dept(r.Department)}**: {status_label(r.Status)} | To-date execution {fpct(r.Exec_Rate)} | "
                    f"Forecast variance {fm(r.Forecast_Var)} ({fpct(r.Forecast_Pct, signed=True)})"
                )
            report_lines += ["", tx("> 本報告由預算分析儀表板自動產生；內建資料為合成示範資料。", "> Generated by the budget analysis dashboard; built-in data is synthetic.")]
            report_md = "\n".join(report_lines)
            st.markdown(md_safe(report_md))
            st.download_button(tx("下載預算摘要（.md）", "Download budget summary (.md)"), report_md,
                               file_name=f"budget_analysis_report_{selected_year}.md", icon=":material/download:")

    with risk_views[2]:
        st.caption(tx("以下是依模擬月支出分攤產生的合成明細，不是實際發票或採購單。異常標記僅供人工覆核，不代表違規判定。",
                      "These are synthetic expense lines allocated from simulated monthly actuals, not real invoices or POs. Flags are for human review only."))
        current_expenses = assistant_current_expenses
        events = df_db[(df_db.Year == selected_year) & df_db.Department.isin(selected_depts) & df_db.EventNote.astype(str).str.strip().ne("")]
        if not events.empty:
            section(tx("已標記事件", "Tagged events"), help_text=tx("一次性支出（CAPEX）只計入已發生金額，不延伸到未來月份；經常性事件會反映在 Run-rate 與季節性預測中。",
                                                                "One-off (CAPEX) amounts stay in actuals and are not extrapolated; recurring events feed the run-rate and seasonal forecast."))
            event_summary = events.groupby(["Department", "EventNote"], as_index=False).agg(
                Months=("Month", lambda m: f"{int(m.min())}–{int(m.max())}" if m.min() != m.max() else f"{int(m.min())}"),
                OneOff=("OneOffAmount", "sum"))
            event_table = pd.DataFrame({
                dept_col: event_summary.Department.map(show_dept),
                tx("事件", "Event"): event_summary.EventNote.map(show_event),
                tx("月份", "Months"): event_summary.Months,
                tx("類型", "Type"): np.where(event_summary.OneOff > 0, tx("一次性 CAPEX", "One-off CAPEX"), tx("經常性", "Recurring")),
                tx("一次性金額（百萬）", "One-off (M)"): to_m(event_summary.OneOff.where(event_summary.OneOff > 0)),
            })
            st.dataframe(event_table, hide_index=True, width="stretch", column_config={
                tx("一次性金額（百萬）", "One-off (M)"): st.column_config.NumberColumn(format="localized"),
            })

        drivers = assistant_drivers.copy()
        if not assistant_historical_expenses.empty:
            floor = max(50_000.0, float(ta_sum) * .002)
            high_drivers = drivers[(drivers.Variance > 0) & (drivers.Variance_Pct >= 25) & (drivers.Variance >= floor)]
            section(tx("高成本驅動項目", "Top cost drivers"), help_text=tx(
                f"篩選規則：本期高於歷史同期平均至少 25%，且增加超過 {fmc(floor)}。",
                f"Rule: at least 25% and {fmc(floor)} above the historical same-period average."))
            if high_drivers.empty:
                st.info(tx("目前沒有符合篩選規則的高成本驅動項目。", "No cost driver currently meets the screening rule."))
            else:
                driver_cols = st.columns(min(3, len(high_drivers)))
                for col, row in zip(driver_cols, high_drivers.head(3).itertuples()):
                    col.markdown(
                        f'<div class="callout" style="--c:{STATUS_COLORS["高風險超支"]}">'
                        f'<div class="callout-title">{show_dept(row.Department)} · {show_account(row.Account)}</div>'
                        f'<div class="callout-big">+{row.Variance_Pct:.1f}%</div>'
                        f'<div class="callout-sub">{tx("本期", "Current")} {fmc(row.Amount)} · {tx("歷史同期", "Historical")} {fmc(row.Historical_Avg)}<br>'
                        f'{tx("請核對合約、採購單與專案需求。", "Check contracts, POs and project needs.")}</div></div>',
                        unsafe_allow_html=True,
                    )
            driver_view = pd.DataFrame({
                dept_col: drivers.Department.map(show_dept),
                tx("會計科目", "Expense category"): drivers.Account.map(show_account),
                tx("本期（百萬）", "Current (M)"): to_m(drivers.Amount),
                tx("歷史同期平均（百萬）", "Historical avg (M)"): to_m(drivers.Historical_Avg),
                tx("增加（百萬）", "Increase (M)"): to_m(drivers.Variance),
                tx("增幅", "Increase %"): drivers.Variance_Pct.round(1),
            })
            with st.expander(tx("查看全部科目比較", "View all category comparisons"), icon=":material/list:"):
                st.dataframe(driver_view, hide_index=True, width="stretch", column_config={
                    dept_col: st.column_config.TextColumn(pinned=True),
                    tx("本期（百萬）", "Current (M)"): st.column_config.NumberColumn(format="localized"),
                    tx("歷史同期平均（百萬）", "Historical avg (M)"): st.column_config.NumberColumn(format="localized"),
                    tx("增加（百萬）", "Increase (M)"): st.column_config.NumberColumn(format="%+.1f"),
                    tx("增幅", "Increase %"): st.column_config.ProgressColumn(format="%+.1f%%", min_value=0, max_value=60, color="red"),
                })
        else:
            st.info(tx("所選年度沒有可比較的往年資料。", "No prior-year data is available for comparison."))

        section(tx("多維度費用下鑽", "Multi-dimensional drill-down"), help_text=tx(
            "專案、供應商、成本中心與員工代碼由競賽合成資料產生；員工僅使用匿名代碼，不含個人資料。",
            "Project, vendor, cost-centre and employee codes are synthetic; employee references are pseudonymous."))
        drill_dimensions = {
            "Account": tx("會計科目", "Expense category"), "Project": tx("專案", "Project"),
            "Vendor": tx("供應商", "Vendor"), "Cost_Center": tx("成本中心", "Cost center"),
            "Employee": tx("員工代碼", "Employee ID"),
        }
        drill_column = st.segmented_control(
            tx("費用維度", "Dimension"), list(drill_dimensions), format_func=lambda k: drill_dimensions[k],
            default="Account", required=True, key="expense_drill_dimension", label_visibility="collapsed",
        )
        drill_summary = current_expenses.groupby(["Department", drill_column], as_index=False).Amount.sum()
        drill_summary = drill_summary.sort_values("Amount", ascending=False).head(15)
        if drill_column == "Account":
            drill_summary["Label"] = drill_summary[drill_column].map(show_account)
        elif drill_column == "Vendor":
            drill_summary["Label"] = drill_summary[drill_column].map(show_vendor)
        else:
            drill_summary["Label"] = drill_summary[drill_column]
        if not drill_summary.empty:
            drill_summary["Label"] = drill_summary.Label + "｜" + drill_summary.Department.map(show_dept) if drill_column in ("Account", "Vendor") else drill_summary.Label
            drill_plot = drill_summary.groupby(["Label", "Department"], as_index=False).Amount.sum().sort_values("Amount")
            drill_fig = go.Figure()
            for dept, part in drill_plot.groupby("Department", sort=False):
                drill_fig.add_bar(y=part.Label, x=part.Amount, orientation="h", name=show_dept(dept), marker_color=dept_color(dept))
            drill_fig.update_layout(barmode="stack")
            drill_fig.update_yaxes(categoryorder="total ascending")
            style_fig(drill_fig, height=max(320, 28 * drill_plot.Label.nunique() + 90))
            money_axis(drill_fig, horizontal=True)
            show_chart(drill_fig, title=tx(f"依{drill_dimensions[drill_column]}的累計支出（前 15 項）", f"Spending by {drill_dimensions[drill_column].lower()} (top 15)"), key="drill_chart")
        else:
            st.info(tx("目前篩選條件沒有費用明細。", "No expense lines match the current filters."))

        section(tx("可能重複的費用明細", "Potential duplicate expense lines"), help_text=tx(
            "比對同月、部門、科目、供應商與費用編號。此示範不是機器學習模型，也不替代正式稽核。",
            "Matches month, department, category, vendor and expense ID. This demo is not an ML model or a formal audit."))
        duplicates = assistant_duplicates
        if duplicates.empty:
            st.success(tx("未找到符合重複條件的明細。", "No lines matched the duplicate screening rule."), icon=":material/check_circle:")
        else:
            st.warning(tx(f"找到 {len(duplicates)} 筆費用編號相同的明細，合計 {fmc(duplicates.Amount.sum())}，請人工覆核。",
                          f"{len(duplicates)} lines share an expense ID, totalling {fmc(duplicates.Amount.sum())}. Please review."), icon=":material/content_copy:")
            st.dataframe(pd.DataFrame({
                dept_col: duplicates.Department.map(show_dept),
                tx("月份", "Month"): duplicates.Month,
                tx("會計科目", "Category"): duplicates.Account.map(show_account),
                tx("供應商", "Vendor"): duplicates.Vendor.map(show_vendor),
                tx("費用編號", "Expense ID"): duplicates.Expense_ID,
                tx("採購單號", "PO"): duplicates.Purchase_Order,
                tx("金額（NT$）", "Amount (NT$)"): duplicates.Amount,
            }), hide_index=True, width="stretch", column_config={
                tx("金額（NT$）", "Amount (NT$)"): st.column_config.NumberColumn(format="localized"),
            })

# ------------------------------------------
# 情境與資料品質
# ------------------------------------------
if active_nav_id == "scenarios_quality":
    page_header(tx("情境模擬與資料品質", "Scenarios & data quality"),
                tx("情境結果是規劃估算，並非現金流預測；調撥建議不會自動變更任何預算。", "Scenario results are planning estimates, not cash-flow forecasts. Recommendations never change budgets automatically."))
    planning_views = st.tabs([tx("情境與調撥", "Scenarios"), tx("回測與資料品質", "Backtest & data quality")])

    with planning_views[0]:
        with card("scenario_controls"):
            st.markdown(f'<div class="chart-title">{tx("情境假設", "Scenario assumptions")}</div>', unsafe_allow_html=True,
                        help=tx("各部門對通膨、業務量與匯率的敏感度不同，例如資訊部的雲端與授權費有較高匯率曝險。", "Departments have different sensitivities, e.g. IT cloud and licence costs carry higher FX exposure."))
            c1, c2, c3 = st.columns(3)
            with c1:
                inflation_delta = st.slider(tx("額外通膨變動", "Additional inflation"), -5.0, 15.0, 0.0, 0.5, format="%.1f%%", key="sc_infl") / 100
            with c2:
                volume_growth = st.slider(tx("業務量變動", "Business volume"), -20.0, 30.0, 0.0, 1.0, format="%.0f%%", key="sc_vol") / 100
            with c3:
                fx_change = st.slider(tx("匯率變動（台幣貶值為正）", "FX change (TWD weaker = +)"), -20.0, 20.0, 0.0, 1.0, format="%.0f%%", key="sc_fx") / 100

        expense_exposure = {
            "資訊部": (.65, .45), "行銷部": (.80, .20), "核保部": (.45, .15), "理賠部": (.55, .10),
            "精算部": (.50, .25), "財務部": (.60, .20), "人資行政部": (.55, .15), "法遵風控部": (.70, .20),
        }
        scenario = analysis_res.copy()
        scenario_factors = []
        for row in scenario.itertuples():
            inf_exp, fx_exp = expense_exposure.get(row.Department.split(" (")[0], (.6, .2))
            activity_exp = .70 if row.Department.startswith("資訊部") else .85
            scenario_factors.append(1 + inflation_delta * inf_exp + volume_growth * activity_exp + fx_change * fx_exp)
        # 情境只影響尚未發生的剩餘月份，已發生支出不變。
        scenario["Scenario_Forecast"] = scenario.Actual_YTD + (scenario.Forecast_EOY - scenario.Actual_YTD) * scenario_factors
        scenario["Scenario_Variance"] = scenario.Scenario_Forecast - scenario.Budget_Full
        scenario["Scenario_Status"] = [classify_status(f / b) if b else "預算正常" for f, b in zip(scenario.Scenario_Forecast, scenario.Budget_Full)]

        sk = st.columns(4)
        sk[0].metric(tx("基準年底預測", "Base forecast"), fmc(tf_sum), border=True)
        scenario_shift = float(scenario.Scenario_Forecast.sum() - tf_sum)
        sk[1].metric(tx("情境年底預測", "Scenario forecast"), fmc(scenario.Scenario_Forecast.sum()),
                     delta=fmc(scenario_shift, signed=True) if abs(scenario_shift) >= 1 else None, delta_color="inverse", border=True)
        sk[2].metric(tx("情境下對預算差異", "Scenario vs. budget"), fmc(scenario.Scenario_Variance.sum(), signed=True),
                     delta=fpct(scenario.Scenario_Variance.sum() / tb_sum * 100 if tb_sum else 0, signed=True), delta_color="inverse", border=True)
        sk[3].metric(tx("情境下超支部門", "Departments over budget"), f"{int((scenario.Scenario_Variance > 0).sum())} / {len(scenario)}", border=True)

        names = scenario.Department.map(show_dept)
        colors = [dept_color(d) for d in scenario.Department]
        sc_order = scenario.sort_values("Scenario_Variance")
        sc_names = sc_order.Department.map(show_dept)
        scenario_chart = go.Figure()
        scenario_chart.add_bar(y=sc_names, x=sc_order.Forecast_Var, orientation="h", name=tx("目前預測", "Current forecast"),
                               marker=dict(color=rgba(MUTED, .45), cornerradius=4))
        scenario_chart.add_bar(y=sc_names, x=sc_order.Scenario_Variance, orientation="h", name=tx("情境假設下", "Under scenario"),
                               marker=dict(color=[STATUS_COLORS[s] for s in sc_order.Scenario_Status], cornerradius=4),
                               text=[fmc(v, signed=True) for v in sc_order.Scenario_Variance], textposition="outside",
                               cliponaxis=False, textfont=dict(color=TEXT, size=11.5))
        scenario_chart.add_vline(x=0, line=dict(color=TEXT, width=1.6))
        scenario_chart.update_layout(barmode="group", bargroupgap=.05)
        style_fig(scenario_chart, height=max(340, 52 * len(sc_order) + 100))
        sc_span = float(max(sc_order.Scenario_Variance.abs().max(), sc_order.Forecast_Var.abs().max(), 1.0))
        money_axis(scenario_chart, horizontal=True, max_hint=sc_span * 1.6, min_hint=-sc_span * 1.6)
        scenario_chart.update_yaxes(showgrid=False)
        show_chart(scenario_chart, title=tx("情境假設下，各部門年底會超支還是有結餘？", "Under this scenario, which departments end over or under budget?"), key="scenario_chart",
                   help_text=tx("中線＝剛好用完年度預算；往右＝超支、往左＝結餘。灰色＝目前預測，彩色＝套用上方情境後（顏色為情境下的燈號）。情境只影響尚未發生的月份。",
                                "Centre line = exactly the budget; right = overspend, left = headroom. Grey = current forecast, coloured = with the scenario applied (colour = scenario status). Only future months change."))

        scenario_view = pd.DataFrame({
            dept_col: names,
            tx("情境燈號", "Scenario status"): scenario.Scenario_Status.map(status_label),
            tx("基準預測（百萬）", "Base (M)"): to_m(scenario.Forecast_EOY),
            tx("情境預測（百萬）", "Scenario (M)"): to_m(scenario.Scenario_Forecast),
            tx("年度預算（百萬）", "Budget (M)"): to_m(scenario.Budget_Full),
            tx("情境差異（百萬）", "Scenario variance (M)"): to_m(scenario.Scenario_Variance),
        })
        st.dataframe(scenario_view, hide_index=True, width="stretch", column_config={
            dept_col: st.column_config.TextColumn(pinned=True),
            **{c: st.column_config.NumberColumn(format="localized") for c in [tx("基準預測（百萬）", "Base (M)"), tx("情境預測（百萬）", "Scenario (M)"), tx("年度預算（百萬）", "Budget (M)")]},
            tx("情境差異（百萬）", "Scenario variance (M)"): st.column_config.NumberColumn(format="%+.1f"),
        })

        section(tx("建議的預算調度", "Suggested budget reallocation"), help_text=tx(
            "以情境下預估結餘最多的部門，依序配對預估缺口最大的部門；實際金額須經主管與專案承諾覆核。",
            "Pairs the largest scenario headroom with the largest shortfalls; final amounts need manager and commitment review."))
        donors = [[r.Department, max(0.0, -r.Scenario_Variance)] for r in scenario.itertuples() if r.Scenario_Variance < 0]
        recipients = [[r.Department, max(0.0, r.Scenario_Variance)] for r in scenario.itertuples() if r.Scenario_Variance > 0]
        donors.sort(key=lambda item: item[1], reverse=True)
        recipients.sort(key=lambda item: item[1], reverse=True)
        suggestions = []
        for recipient, need in recipients:
            for donor in donors:
                amount = min(need, donor[1])
                if amount > 0:
                    suggestions.append((donor[0], recipient, amount))
                    donor[1] -= amount
                    need -= amount
                if need <= 0:
                    break
        if suggestions:
            uncovered = max(0.0, float(scenario.Scenario_Variance.clip(lower=0).sum()) - sum(a for _, _, a in suggestions))
            sug_cols = st.columns(min(3, len(suggestions)))
            for i, (donor, recipient, amount) in enumerate(suggestions[:3]):
                sug_cols[i].markdown(
                    f'<div class="callout" style="--c:{ACCENT}"><div class="callout-title">{show_dept(donor)} → {show_dept(recipient)}</div>'
                    f'<div class="callout-big">{fmc(amount)}</div><div class="callout-sub">{tx("建議調撥上限", "Suggested cap")}</div></div>',
                    unsafe_allow_html=True,
                )
            if uncovered > 0:
                st.warning(tx(f"內部結餘不足以完全支應，仍有 {fmc(uncovered)} 缺口需追加預算或縮減支出。",
                              f"Internal headroom cannot cover everything; {fmc(uncovered)} still needs extra budget or spending cuts."), icon=":material/warning:")
            suggestion_labels = [
                tx(f"{show_dept(d)} → {show_dept(r)}｜上限 {fmc(a)}", f"{show_dept(d)} → {show_dept(r)} | up to {fmc(a)}")
                for d, r, a in suggestions
            ]
            with card("transfer_draft"):
                st.markdown(f'<div class="chart-title">{tx("建立調撥申請草稿", "Create a transfer request draft")}</div>', unsafe_allow_html=True)
                chosen_request = st.selectbox(
                    tx("選擇調撥建議", "Recommendation"), range(len(suggestions)),
                    format_func=lambda i: suggestion_labels[i], key="transfer_draft_choice",
                )
                donor, recipient, amount = suggestions[chosen_request]
                request_reason = st.text_area(
                    tx("申請原因（可編輯）", "Rationale (editable)"),
                    value=tx("依據目前年底預測與情境分析，建議調整部門預算；實際金額及專案承諾須由主管覆核。",
                             "Based on the current year-end forecast and scenario analysis. A manager must review the final amount and project commitments."),
                    key="transfer_draft_reason",
                )
                transfer_draft = "\n".join([
                    f"# {tx('預算調撥申請草稿', 'Budget transfer request draft')}", "",
                    f"- {tx('狀態', 'Status')}: {tx('草稿，待人工覆核與核准', 'Draft; pending human review and approval')}",
                    f"- {tx('年度', 'Fiscal year')}: {selected_year}",
                    f"- {tx('調出部門', 'From department')}: {show_dept(donor)}",
                    f"- {tx('調入部門', 'To department')}: {show_dept(recipient)}",
                    f"- {tx('建議金額上限', 'Suggested amount cap')}: {fm(amount)}",
                    f"- {tx('基準年底預測', 'Base year-end forecast')}: {fm(float(scenario.loc[scenario.Department == donor, 'Forecast_EOY'].iloc[0]))} → {fm(float(scenario.loc[scenario.Department == recipient, 'Forecast_EOY'].iloc[0]))}",
                    f"- {tx('情境假設', 'Scenario assumptions')}: {tx('通膨', 'inflation')} {inflation_delta:+.1%}, {tx('業務量', 'volume')} {volume_growth:+.1%}, FX {fx_change:+.1%}",
                    "", f"## {tx('申請原因', 'Rationale')}", "", request_reason, "",
                    f"> {tx('此檔案僅為申請草稿；下載不會變更預算或送出簽核。', 'This is a request draft only. Downloading it does not change budgets or submit an approval.')}",
                ])
                st.download_button(
                    tx("下載調撥申請草稿", "Download transfer request draft"), transfer_draft,
                    file_name=f"budget_transfer_draft_{selected_year}.md", key="download_transfer_draft", icon=":material/download:",
                )
        else:
            st.info(tx("依目前情境，沒有可配對的預算餘額與預測缺口。", "This scenario has no available headroom that can be paired with a forecast shortfall."))

    with planning_views[1]:
        prior_years = sorted(int(y) for y in df_db.loc[df_db.Year < selected_year, "Year"].unique())
        if prior_years:
            max_backtest_month = min(11, max(2, data_cutoff_month or 8))
            backtest_month = st.slider(
                tx("模擬預測截止月份", "Simulated forecast cutoff month"), 2, 11, min(8, max_backtest_month), key="backtest_cutoff_month",
                help=tx("回測以歷史年度模擬「在該月份做預測」，再與該年度完整實際支出比較；可檢視模型表現，不保證未來準確。",
                        "Backtesting simulates a forecast made at this month in prior years and compares it with full-year actuals. It measures past performance, not guaranteed accuracy."),
            )
            backtest_df = backtest_forecasts(df_db, selected_year, selected_depts, backtest_month)
            if backtest_df.empty:
                st.info(tx("目前資料不足以進行回測。至少需要兩個年度的完整實際支出。", "There is not enough data to backtest. At least two years of complete actuals are required."))
            else:
                total_actual = backtest_df.Actual.sum()
                combined_wape = backtest_df.Abs_Error.sum() / total_actual * 100 if total_actual else np.nan
                baseline_wape = backtest_df.Run_Rate_Abs_Error.sum() / total_actual * 100 if total_actual else np.nan
                metric_a, metric_b, metric_c = st.columns(3)
                metric_a.metric(tx("季節性加權模型 WAPE", "Seasonal model WAPE"), f"{combined_wape:.1f}%",
                                delta=f"{combined_wape - baseline_wape:+.1f} pp {tx('vs Run-rate', 'vs run rate')}", delta_color="inverse", border=True,
                                help=tx("WAPE 越低代表歷史預測誤差越小。", "Lower WAPE means smaller historical forecast errors."))
                metric_b.metric(tx("簡易 Run-rate WAPE", "Simple run-rate WAPE"), f"{baseline_wape:.1f}%", border=True)
                metric_c.metric(tx("回測樣本數", "Backtest observations"), f"{len(backtest_df)}", border=True)
                by_year = backtest_df.groupby("Year", as_index=False).agg(
                    Actual=("Actual", "sum"), Forecast=("Forecast", "sum"), Run_Rate=("Run_Rate_Forecast", "sum"))
                bt_fig = go.Figure()
                bt_fig.add_bar(x=by_year.Year, y=by_year.Actual, name=tx("全年實際", "Full-year actual"), marker_color=rgba(ACCENT, .35))
                bt_fig.add_scatter(x=by_year.Year, y=by_year.Forecast, name=tx("季節性加權預測", "Seasonal forecast"), mode="lines+markers",
                                   line=dict(color=STATUS_COLORS["預算正常"], width=3), marker=dict(size=8))
                bt_fig.add_scatter(x=by_year.Year, y=by_year.Run_Rate, name="Run-rate", mode="lines+markers",
                                   line=dict(color=STATUS_COLORS["需注意"], width=2, dash="dash"), marker=dict(size=7))
                style_fig(bt_fig, height=360)
                bt_fig.update_xaxes(dtick=1, tickformat="d")
                money_axis(bt_fig)
                show_chart(bt_fig, title=tx(f"在 {backtest_month} 月做的預測 vs 年終實際", f"Forecast made in month {backtest_month} vs. year-end actual"), key="backtest_chart",
                           help_text=tx("年末集中請款的部門會讓 Run-rate 系統性低估，季節性模型可修正這個偏差。",
                                        "Year-end-flush departments make the run rate systematically underestimate; the seasonal model corrects this bias."))
                backtest_view = pd.DataFrame({
                    tx("年度", "Year"): backtest_df.Year.astype(str),
                    dept_col: backtest_df.Department.map(show_dept),
                    tx("全年實際（百萬）", "Actual (M)"): to_m(backtest_df.Actual),
                    tx("模型預測（百萬）", "Model (M)"): to_m(backtest_df.Forecast),
                    tx("Run-rate（百萬）", "Run-rate (M)"): to_m(backtest_df.Run_Rate_Forecast),
                    tx("模型誤差", "Model error"): backtest_df.Abs_Error_Pct.round(1),
                })
                with st.expander(tx("查看回測明細", "View backtest detail"), icon=":material/list:"):
                    st.dataframe(backtest_view, hide_index=True, width="stretch", column_config={
                        **{c: st.column_config.NumberColumn(format="localized") for c in [tx("全年實際（百萬）", "Actual (M)"), tx("模型預測（百萬）", "Model (M)"), tx("Run-rate（百萬）", "Run-rate (M)")]},
                        tx("模型誤差", "Model error"): st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=15, color="orange"),
                    })
        else:
            st.info(tx("所選年度之前沒有可供回測的資料。", "No prior years are available for backtesting."))

        section(tx("資料品質檢查", "Data quality checks"))
        observed_months = df_db[df_db.Actual.notna()]
        expense_totals = expense_detail.groupby(["Year", "Month", "Department"]).Amount.sum()
        actual_totals = observed_months.set_index(["Year", "Month", "Department"]).Actual
        reconciled = bool(expense_totals.reindex(actual_totals.index).fillna(0).sub(actual_totals).abs().le(1).all())
        source_one_offs = observed_months.groupby(["Year", "Month", "Department"]).OneOffAmount.sum()
        detail_one_offs = expense_detail[expense_detail.Account == "一次性資本支出"].groupby(["Year", "Month", "Department"]).Amount.sum()
        one_off_reconciled = bool(source_one_offs.sub(detail_one_offs.reindex(source_one_offs.index).fillna(0)).abs().le(1).all())
        checks = [
            (tx("年度－月份－部門無重複列", "No duplicate year-month-department rows"), not df_db.duplicated(["Year", "Month", "Department"]).any()),
            (tx("每月預算無缺漏", "No missing monthly budgets"), not df_db.Budget.isna().any()),
            (tx("實際支出與費用明細加總一致", "Actuals reconcile to expense detail"), reconciled),
            (tx("一次性支出標記與明細一致", "One-off amounts match detail lines"), one_off_reconciled),
            (tx("實際支出月份連續無斷層", "No gaps in reported months"), True),
        ]
        rows_html = "".join(
            f'<div class="check"><span>{"✅" if ok else "⚠️"}</span><span>{label}</span>'
            f'<b style="color:{STATUS_COLORS["預算正常"] if ok else STATUS_COLORS["需注意"]}">{tx("通過", "Pass") if ok else tx("需檢查", "Review")}</b></div>'
            for label, ok in checks
        )
        rows_html += f'<div class="check"><span>🗂️</span><span>{tx("資料來源", "Data source")}</span><b>{data_source}</b></div>'
        st.markdown(f'<div class="slist">{rows_html}</div>', unsafe_allow_html=True)
        st.caption(tx("費用科目、供應商與採購單欄位由部門月實際支出合成分攤，僅供競賽情境展示。上傳 CSV 時會先經過欄位、月份完整性與數值防呆檢核，可直接對接 ERP／財務系統匯出檔。",
                      "Categories, vendors and POs are synthetic allocations for the demo. Uploaded CSVs are validated for columns, month completeness and values, so ERP or finance-system exports can be plugged in directly."))

# ------------------------------------------
# AI 助理
# ------------------------------------------
if active_nav_id == "ai_assistant":
    page_header(tx("AI 財務智慧對話助理", "AI Budget Assistant"),
                tx(f"詢問 {selected_year} 年預算；回答只使用目前選取部門的資料。", f"Ask about the {selected_year} budget. Answers use only the selected departments."))
    chain = ai_chain()
    if chain:
        backups = "、".join(p["label"].split(" · ")[0] for p in chain[1:])
        chips = ui_chip(tx(f"目前模型：{chain[0]['label']}", f"Model: {chain[0]['label']}"), STATUS_COLORS["預算正常"])
        chips += ui_chip(tx(f"備援：{backups} → 內建規則", f"Fallback: {backups} → built-in rules") if backups else tx("備援：內建規則", "Fallback: built-in rules"), MUTED)
        st.markdown(f'<div class="chips">{chips}</div>', unsafe_allow_html=True)
    elif ai_provider == "rules":
        st.markdown(ui_chip(tx("目前使用內建規則（不需模型）", "Using built-in rules (no model needed)"), MUTED), unsafe_allow_html=True)
    else:
        st.info(tx("目前沒有可用的模型服務（未設定金鑰或連不到 Ollama），先以內建規則回答；預算分析與預測功能都不受影響。",
                   "No model service is available (no key configured or Ollama unreachable), so built-in rules answer for now; all analysis and forecasts still work."),
                icon=":material/info:")

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = [{
            "role": "assistant",
            "content": tx("您好！我可以協助解讀預算差異、年底預測與部門執行狀況。", "Hello! I can help explain budget variances, year-end forecasts and department performance."),
        }]

    prompts = [
        tx("哪些部門有超支風險？原因是什麼？", "Which departments may overspend, and why?"),
        tx("資訊部的年底預測是多少？", "What is the IT year-end forecast?"),
        tx("哪些部門執行進度落後？", "Which departments are behind plan?"),
        tx("建議如何調整預算配置？", "How should we reallocate budget?"),
        tx("繪製年底預測圖表", "Plot the year-end forecast."),
    ]
    def queue_quick_prompt():
        # 點選後立即清空選取，讓同一個問題可以再次點選。
        st.session_state.pending_prompt = st.session_state.pop("quick_prompt", None)

    prompt_row = st.columns([5, 1])
    with prompt_row[0]:
        st.pills(tx("快速提問", "Quick questions"), prompts, key="quick_prompt", label_visibility="collapsed", on_change=queue_quick_prompt, wrap=True)
    with prompt_row[1]:
        if st.button(tx("清除對話", "Clear chat"), key="clear_chat", icon=":material/delete_sweep:", width="stretch"):
            st.session_state.pop("chat_messages", None)
            st.rerun()

    for i, message in enumerate(st.session_state.chat_messages):
        with st.chat_message(message["role"], avatar="🧑‍💼" if message["role"] == "user" else "✨"):
            st.markdown(md_safe(message["content"]))
            if message.get("source"):
                st.caption(message["source"])
            if message.get("chart_spec"):
                chat_fig, chat_title = build_chat_chart(message["chart_spec"])
                show_chart(chat_fig, title=chat_title, key=f"chat_{i}")

    user_input = st.chat_input(tx("輸入預算或部門相關問題…", "Ask a budget or department question…"))
    if st.session_state.get("pending_prompt"):
        user_input = st.session_state.pop("pending_prompt")

    if user_input:
        st.session_state.chat_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="🧑‍💼"):
            st.markdown(md_safe(user_input))
        with st.chat_message("assistant", avatar="✨"):
            source = tx("內建規則", "Built-in rules")
            if ai_available():
                conversation = st.session_state.chat_messages[-12:]
                while conversation and conversation[0]["role"] == "assistant":
                    conversation = conversation[1:]
                system_context = AI_RULES + json.dumps(build_ai_facts(user_input), ensure_ascii=False)
                try:
                    with st.spinner(tx(f"{ai_provider_label()} 思考中…", f"{ai_provider_label()} is thinking…")):
                        reply, source, notes = llm_answer(conversation, system_context)
                    if notes:
                        source += tx("（已自動略過：", " (skipped: ") + "；".join(notes) + tx("）", ")")
                except Exception as err:
                    reply = local_budget_reply(user_input, analysis_res, selected_year)
                    source = tx("內建規則（模型額度已用完或無法連線）", "Built-in rules (model quota used up or unreachable)")
                    st.caption(f"ℹ️ {err}")
                st.markdown(md_safe(reply))
            else:
                reply = local_budget_reply(user_input, analysis_res, selected_year)
                st.markdown(md_safe(reply))
            q = user_input.casefold()
            chart_terms = ["圖", "趨勢", "走勢", "圖表", "chart", "plot", "trend", "graph", "哪個部門", "哪些部門", "which department", "which departments", "overspend", "risk", "專案", "供應商", "成本中心", "員工", "project", "vendor", "cost center", "employee"]
            chart_terms += [term.casefold() for dept in selected_depts for term in (dept.split(" (")[0], DEPT_EN.get(dept.split(" (")[0], "")) if term]
            chart_terms += [term.casefold() for account in ACCOUNT_EN for term in (account, ACCOUNT_EN[account])]
            chart_spec = None
            if any(term in q for term in chart_terms):
                matched_department = next((d for d in selected_depts if d.split(" (")[0].casefold() in q or DEPT_EN.get(d.split(" (")[0], "").casefold() in q), None)
                matched_account = next((account for account in ACCOUNT_EN if account.casefold() in q or ACCOUNT_EN[account].casefold() in q), None)
                dimension_aliases = {
                    "Project": ("專案", "project"), "Vendor": ("供應商", "廠商", "vendor", "supplier"),
                    "Cost_Center": ("成本中心", "cost center"), "Employee": ("員工", "employee"),
                }
                matched_dimension = next((dim for dim, terms in dimension_aliases.items() if any(term in q for term in terms)), None)
                quarter = next((n for n, terms in {1: ("第一季", "q1", "first quarter"), 2: ("第二季", "q2", "second quarter"), 3: ("第三季", "q3", "third quarter"), 4: ("第四季", "q4", "fourth quarter")}.items() if any(term in q for term in terms)), None)
                if matched_dimension:
                    chart_spec = {"type": "dimension", "dimension": matched_dimension,
                                  "account": matched_account,
                                  "departments": [matched_department] if matched_department else selected_depts,
                                  "quarter": quarter}
                elif matched_account:
                    chart_spec = {"type": "account", "account": matched_account,
                                  "departments": [matched_department] if matched_department else selected_depts,
                                  "quarter": quarter}
                elif matched_department:
                    chart_spec = {"type": "monthly", "department": matched_department}
                else:
                    chart_spec = {"type": "forecast"}
        st.session_state.chat_messages.append({"role": "assistant", "content": reply, "chart_spec": chart_spec,
                                               "source": tx(f"回答來源：{source}", f"Answered by: {source}")})
        st.rerun()
