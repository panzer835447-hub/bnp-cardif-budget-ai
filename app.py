import html
import itertools
import json
import math
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from fpdf import FPDF
from fpdf.enums import MethodReturnValue, WrapMode

# ==========================================
# 1. 頁面設定、側邊欄骨架與偏好設定
# ==========================================
st.set_page_config(
    page_title="法巴人壽 | AI 預算預測與差異分析助手",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 側邊欄以容器預先排好「品牌 → 導覽 → 篩選 → 身分 → 資料狀態 → 系統 → 偏好」的顯示順序，程式可依相依關係先後填入。
sb_brand = st.sidebar.container()
sb_nav = st.sidebar.container()
sb_filters = st.sidebar.container(key="sb_filters")
sb_role = st.sidebar.container(key="sb_role")
sb_status = st.sidebar.container()
sb_settings = st.sidebar.container()
sb_prefs = st.sidebar.container(key="sb_prefs")
pref_lang, pref_theme = sb_prefs.columns(2, gap="small")  # 語言與主題並排，省一整列

with pref_lang:
    # 語言、頁面、年度綁定在網址參數上：切換主題需要重新載入頁面，綁定後重新載入仍停在原本的畫面。
    LANGUAGE = st.segmented_control(
        "語言 / Language", ["中文", "EN"], default="中文", required=True,
        key="ui_language", label_visibility="collapsed", width="stretch", bind="query-params",
    )
IS_EN = LANGUAGE == "EN"
# 淺色／深色使用 Streamlit 原生主題，原生元件與表格才能同步配色；這裡讀取目前主題調整自訂樣式與圖表。
if st.context.theme.type is None and not st.session_state.get("_theme_probe_done"):
    # 首次載入時前端尚未回報主題；重跑一次即可取得，避免第一次畫面配色不一致。
    st.session_state["_theme_probe_done"] = True
    st.rerun()
IS_DARK = (st.context.theme.type or "dark") == "dark"

with pref_theme:
    # Streamlit 的右上角選單已隱藏，主題改由這裡切換：寫入 Streamlit 自己的主題設定後重新載入，原生元件也會一起換色。
    theme_choice = st.segmented_control(
        "主題 / Theme", ["light", "dark"], default="dark" if IS_DARK else "light", required=True,
        format_func=lambda t: ":material/light_mode:" if t == "light" else ":material/dark_mode:",
        key="ui_theme", label_visibility="collapsed", width="stretch",
        help="Light / Dark" if IS_EN else "淺色／深色主題",
    )
    if theme_choice != ("dark" if IS_DARK else "light"):
        st.html(f"""<script>
localStorage.setItem("stActiveTheme-" + window.location.pathname + "-v2", JSON.stringify("{'Dark' if theme_choice == 'dark' else 'Light'}"));
window.location.reload();
</script>""", unsafe_allow_javascript=True)

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

def show_status(status):
    pairs = {
        "高風險超支": "High overspend risk", "需注意": "Monitor closely",
        "執行落後": "Behind plan", "預算正常": "On track",
    }
    return pairs.get(status, status) if IS_EN else status

# 色彩系統：中性石墨底 + 靛紫品牌色。品牌色刻意避開四種燈號色（紅／琥珀／青／綠），顏色只用來表達狀態。
BG = "#0b0d12" if IS_DARK else "#f4f5f8"
PANEL = "#12151c" if IS_DARK else "#ffffff"
RAISED = "#181c25" if IS_DARK else "#f8f9fb"
BORDER = "#252a36" if IS_DARK else "#e2e5eb"
TEXT = "#eceef3" if IS_DARK else "#111827"
MUTED = "#8e96a6" if IS_DARK else "#5a6272"
GRID = "#1c2029" if IS_DARK else "#eef0f4"
ACCENT = "#8b8df9" if IS_DARK else "#4f46e5"
ACCENT2 = "#b48cf6" if IS_DARK else "#7c3aed"
TRACK = "#232835" if IS_DARK else "#e8eaef"
STATUS_COLORS = {
    "高風險超支": "#f0616d" if IS_DARK else "#d6334a",
    "需注意": "#f3a83b" if IS_DARK else "#b76a00",
    "執行落後": "#3cbfe0" if IS_DARK else "#0479a8",
    "預算正常": "#36c48f" if IS_DARK else "#118a58",
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
            radial-gradient(1100px 380px at 78% -140px, {rgba(ACCENT, .13 if IS_DARK else .07)}, transparent 70%),
            radial-gradient(800px 320px at 18% -180px, {rgba(ACCENT2, .08 if IS_DARK else .04)}, transparent 70%),
            var(--bg); background-attachment:fixed; }}
[data-testid="stHeader"] {{ background:transparent; }}
/* 給組員與評審看的展示版：隱藏所有 Streamlit 自帶的介面（右上角選單、Deploy、頂部彩條、執行中圖示、頁尾）。
   側邊欄展開／收合按鈕保留，因為那是導覽的一部分。執行狀態圖示只做隱藏（仍留在 DOM），下方的進度光條靠它判斷。 */
[data-testid="stToolbar"], [data-testid="stMainMenu"], [data-testid="stAppDeployButton"], .stAppDeployButton,
[data-testid="stDecoration"], footer, #MainMenu {{ display:none !important; }}
[data-testid="stStatusWidget"] {{ visibility:hidden !important; }}
/* 重跑期間不要把整頁淡化成半透明（切頁、切語言、切主題時的「卡頓感」主要來自這個閃爍） */
[data-stale="true"], .stale-element {{ opacity:1 !important; transition:none !important; }}
/* 取而代之：執行中在頁面頂端顯示一條細的進度光條，讓使用者知道正在更新 */
body:has([data-testid="stStatusWidget"]) .stApp::before {{ content:""; position:fixed; top:0; left:0; height:3px; width:40%; z-index:999991;
    background:var(--grad); border-radius:0 3px 3px 0; animation:loadbar 1s ease-in-out infinite; }}
@keyframes loadbar {{ 0% {{ transform:translateX(-100%); }} 100% {{ transform:translateX(260%); }} }}
[data-testid="stMainBlockContainer"] {{ padding-top:1.4rem; padding-bottom:3rem; max-width:1480px; }}
h1,h2,h3,h4,h5,p,label,li,[data-testid="stCaptionContainer"] {{ color:var(--text); }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color:var(--muted) !important; }}
hr {{ border-color:var(--border); }}

/* ---------- 側邊欄 ---------- */
[data-testid="stSidebar"] {{ background:{"linear-gradient(180deg,#10131a,#0c0e13)" if IS_DARK else "#ffffff"}; border-right:1px solid var(--border); }}
[data-testid="stSidebar"] * {{ color:var(--text); }}
[data-testid="stSidebarUserContent"] {{ padding-top:.2rem; }}
.st-key-theme_sync_slot {{ display:none !important; }}
.sb-brand {{ display:flex; align-items:center; gap:12px; padding:2px 4px 14px; margin-bottom:2px; border-bottom:1px solid var(--border); }}
.sb-mark {{ width:40px; height:40px; border-radius:12px; display:flex; align-items:center; justify-content:center; background:linear-gradient(140deg,{ACCENT},{ACCENT2}); flex:0 0 40px; box-shadow:0 8px 22px {rgba(ACCENT, .38)}, inset 0 1px 0 rgba(255,255,255,.25); }}
.sb-title {{ font-weight:800; font-size:15px; letter-spacing:-.01em; line-height:1.25; }}
.sb-sub {{ font-size:11px; color:var(--muted) !important; margin-top:2px; }}
.sb-label {{ font-size:10.5px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:var(--muted) !important; margin:14px 4px 6px; opacity:.85; }}
/* 側邊欄元件間距收緊（原生預設 1rem 太鬆，造成擁擠又冗長的感覺） */
[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {{ gap:.45rem; }}
[data-testid="stSidebarUserContent"] [data-testid="stHorizontalBlock"] {{ gap:.4rem; }}
.sb-hint {{ display:inline-flex; align-items:center; gap:5px; font-size:11.5px; color:var(--muted) !important; margin:0 4px; }}
.st-key-sb_prefs {{ margin-top:4px; }}
/* 導覽：圖示放進圓角方塊，選中項目左側亮條 + 漸層底；分組標題由 CSS 插入 */
.st-key-nav_slot [data-testid="stRadio"], .st-key-nav_slot [role="radiogroup"], .st-key-nav_slot [role="radiogroup"] > div {{ width:100%; }}
.st-key-nav_slot [role="radiogroup"] {{ gap:2px; }}
.st-key-nav_slot [data-testid="stRadioOption"] {{ position:relative; width:100%; padding:5px 8px; border-radius:10px; border:1px solid transparent; margin:0; transition:background .15s, border-color .15s; cursor:pointer; box-sizing:border-box; }}
.st-key-nav_slot [data-testid="stRadioOption"]:hover {{ background:{rgba(TEXT, .05)}; }}
.st-key-nav_slot [data-testid="stRadioOption"] > div > div:first-child {{ display:none; }}
.st-key-nav_slot [data-testid="stRadioOption"]:has(input:checked) {{ background:linear-gradient(90deg,{rgba(ACCENT, .20)},{rgba(ACCENT, .04)}); border-color:{rgba(ACCENT, .28)}; }}
.st-key-nav_slot [data-testid="stRadioOption"]:has(input:checked)::after {{ content:""; position:absolute; left:-1px; top:9px; bottom:9px; width:3px; border-radius:0 3px 3px 0; background:var(--grad); }}
.st-key-nav_slot [data-testid="stRadioOption"] p {{ font-weight:600; font-size:14px; display:flex; align-items:center; width:100%; }}
.st-key-nav_slot [data-testid="stRadioOption"]:has(input:checked) p {{ color:var(--text) !important; font-weight:700; }}
.st-key-nav_slot [data-testid="stRadioOption"] p span[role="img"] {{ margin-right:10px; font-size:17px; width:28px; height:28px; border-radius:8px; display:inline-flex; align-items:center; justify-content:center;
    background:{rgba(TEXT, .05)}; border:1px solid var(--border); color:var(--muted) !important; flex:0 0 32px; }}
.st-key-nav_slot [data-testid="stRadioOption"]:has(input:checked) p span[role="img"] {{ background:var(--grad); border-color:transparent; color:#fff !important; box-shadow:0 6px 16px {rgba(ACCENT, .35)}; }}
.st-key-nav_slot [data-testid="stRadioOption"] p span[data-testid="stMarkdownBadge"], .st-key-nav_slot [data-testid="stRadioOption"] p span[class*="badge"] {{ margin-left:auto; }}
.sb-status {{ margin:2px 0 0; padding:10px 12px; border-radius:14px; border:1px solid var(--border); background:{rgba(TEXT, .03)}; }}
.sb-status-row {{ display:flex; justify-content:space-between; align-items:center; font-size:12px; color:var(--muted) !important; }}
.sb-status-row b {{ color:var(--text); font-weight:700; }}
.sb-progress {{ height:5px; border-radius:999px; background:var(--track); margin:7px 0 6px; overflow:hidden; }}
.sb-progress i {{ display:block; height:100%; border-radius:999px; background:var(--grad); }}
.sb-src {{ display:flex; align-items:center; gap:7px; font-size:11.5px; color:var(--muted) !important; }}
.sb-src::before {{ content:""; width:7px; height:7px; border-radius:50%; background:var(--c); box-shadow:0 0 0 3px {rgba(TEXT, .06)}; }}
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
[data-testid="stMetricValue"] {{ color:var(--text); font-size:clamp(17px,1.5vw,24px) !important; font-weight:800; letter-spacing:-.02em; }}
/* 窄欄時金額換行而不是被截成「NT$ 85...」 */
[data-testid="stMetricValue"] > div, [data-testid="stMetricDelta"] > div, [data-testid="stMetricLabel"] p {{ white-space:normal !important; overflow:visible !important; text-overflow:clip !important; }}
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
.chart-hint {{ display:flex; align-items:flex-start; gap:6px; font-size:12.5px; color:var(--muted); line-height:1.55; margin:2px 0 4px; }}
.chart-hint .ico {{ color:{ACCENT}; margin-top:.25em; }}
/* 「這頁在看什麼」說明卡：步驟式，讓第一次看的人知道怎麼讀 */
.explain {{ background:linear-gradient(120deg,{rgba(ACCENT, .10)},var(--panel) 60%); border:1px solid {rgba(ACCENT, .30)}; border-radius:16px; padding:14px 18px; margin:4px 0 14px; }}
.explain-title {{ font-weight:800; font-size:14.5px; color:var(--text); display:flex; align-items:center; gap:7px; }}
.explain-steps {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:10px; margin-top:10px; }}
.explain-step {{ display:flex; gap:9px; align-items:flex-start; font-size:12.8px; color:var(--text); line-height:1.55; }}
.explain-step b {{ flex:0 0 22px; height:22px; border-radius:50%; background:var(--grad); color:#fff; display:inline-flex; align-items:center; justify-content:center; font-size:12px; }}
/* 讓 help 提示圖示緊貼標題右側，而不是飄在容器最右上角 */
[data-testid="stMarkdown"] > div:has(.section-title), [data-testid="stMarkdown"] > div:has(.chart-title), [data-testid="stMarkdown"] > div:has(.sb-hint) {{ display:flex; align-items:center; gap:4px; }}
[data-testid="stMarkdown"] > div:has(.section-title) {{ margin:16px 0 4px; }}
[data-testid="stMarkdown"] > div:has(.section-title) > [data-testid="stMarkdownContainer"],
[data-testid="stMarkdown"] > div:has(.chart-title) > [data-testid="stMarkdownContainer"] {{ width:auto; flex:0 1 auto; }}
[data-testid="stMarkdown"] > div:has(.section-title) > label, [data-testid="stMarkdown"] > div:has(.chart-title) > label, [data-testid="stMarkdown"] > div:has(.sb-hint) > label {{ position:static; margin:0; color:var(--muted); }}
[data-testid="stMarkdown"] > div:has(.sb-hint) > [data-testid="stMarkdownContainer"] {{ width:auto; flex:0 1 auto; }}

/* 修正「拖曳時圖表越變越大」：欄位允許縮小，圖表本身不加 padding／border，超出部分裁切。 */
[data-testid="stColumn"] {{ min-width:0 !important; }}
/* 版面列：寬度不夠時自動換行（Streamlit 原生要 640px 以下才堆疊，筆電＋側欄時會擠壓圖表）。
   固定的 min-width 不依內容計算，不會重現「拖曳時圖表變大」的問題。 */
[data-testid="stMain"] [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap; row-gap:1rem; }}
[data-testid="stMain"] [data-testid="stColumn"] {{ min-width:min(100%, 200px) !important; }}
.st-key-nowrap-prompt [data-testid="stHorizontalBlock"] {{ flex-wrap:nowrap; }}
.st-key-nowrap-prompt [data-testid="stColumn"] {{ min-width:0 !important; }}
.st-key-nowrap-prompt [data-testid="stColumn"]:nth-child(2) {{ flex:0 0 auto !important; width:auto !important; min-width:120px !important; }}
.st-key-wrap-hero [data-testid="stHorizontalBlock"], .st-key-wrap-list [data-testid="stHorizontalBlock"],
.st-key-card-overview_heat [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap; row-gap:1rem; }}
.st-key-wrap-hero [data-testid="stColumn"]:nth-child(1) {{ flex:2.15 1 440px !important; }}
.st-key-wrap-hero [data-testid="stColumn"]:nth-child(2) {{ flex:1 1 280px !important; }}
.st-key-wrap-list [data-testid="stColumn"]:nth-child(1) {{ flex:1.65 1 440px !important; }}
.st-key-wrap-list [data-testid="stColumn"]:nth-child(2) {{ flex:1 1 280px !important; }}
.st-key-card-overview_heat [data-testid="stColumn"]:nth-child(1) {{ flex:3 1 280px !important; }}
.st-key-card-overview_heat [data-testid="stColumn"]:nth-child(2) {{ flex:1 1 200px !important; }}
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
/* 4 → 2 → 1 欄，避免 auto-fit 排出 3+1 的孤兒卡 */
.kpi-wrap {{ container-type:inline-size; }}
.kpi-grid {{ display:grid; grid-template-columns:repeat(var(--cols, 4), minmax(0, 1fr)); gap:14px; margin-bottom:14px; }}
@container (max-width:900px) {{ .kpi-grid.c4 {{ grid-template-columns:repeat(2, minmax(0, 1fr)); }} }}
@container (max-width:620px) {{ .kpi-grid.c3, .kpi-grid.c2 {{ grid-template-columns:minmax(0, 1fr); }} }}
@container (max-width:440px) {{ .kpi-grid {{ grid-template-columns:minmax(0, 1fr); }} }}
/* 全站唯一的數字卡樣式：compact 為沒有迷你圖的版本，高度由同一列最高的卡決定 */
.kpi.compact {{ min-height:0; padding-bottom:16px; }}
.kpi .lb {{ display:flex; align-items:center; gap:6px; }}
.tip {{ position:relative; display:inline-flex; align-items:center; justify-content:center; width:15px; height:15px; border-radius:50%;
       border:1px solid var(--border); color:var(--muted); font-size:10px; font-weight:700; cursor:help; flex:0 0 15px; }}
.tip:hover::after {{ content:attr(data-tip); position:absolute; left:50%; top:22px; transform:translateX(-50%); z-index:20; width:max-content; max-width:260px;
       white-space:normal; padding:8px 10px; border-radius:9px; background:var(--panel); border:1px solid var(--border); box-shadow:0 10px 28px rgba(0,0,0,.25);
       color:var(--text); font-size:12px; font-weight:500; line-height:1.55; }}
.kpi {{ overflow:visible; }}
.kpi .viz {{ overflow:hidden; border-radius:0 0 18px 18px; }}
.kpi {{ position:relative; min-height:196px; box-sizing:border-box; border:1px solid var(--border); border-radius:18px; padding:16px 18px 0; display:flex; flex-direction:column; gap:6px; overflow:hidden; }}
.kpi .top {{ display:flex; align-items:center; gap:10px; min-width:0; }}
.kpi .ic {{ width:32px; height:32px; border-radius:10px; display:flex; align-items:center; justify-content:center; flex:0 0 32px; font-size:16px; }}
.kpi .lb {{ font-size:13.5px; color:var(--muted); font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.kpi .vl {{ font-size:clamp(22px,2.1vw,30px); font-weight:900; color:var(--text); white-space:nowrap; letter-spacing:-.025em; line-height:1.15; margin-top:4px; }}
.kpi .meta {{ display:flex; align-items:center; gap:8px; min-width:0; }}
.kpi .sb {{ font-size:12px; color:var(--muted); line-height:1.4; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; min-width:0; }}
.delta {{ display:inline-flex; align-items:center; gap:3px; padding:2px 8px; border-radius:999px; font-size:11.5px; font-weight:800; white-space:nowrap; flex:0 0 auto; }}
/* 卡片底部滿版的迷你圖：四張卡各用不同圖形（長條／面積／環形／正負長條） */
.kpi .viz {{ margin:auto -18px 0; height:64px; display:flex; align-items:flex-end; }}
.kpi .viz svg {{ width:100%; height:100%; display:block; }}
.rg {{ width:100%; padding:0 18px 16px; box-sizing:border-box; }}
.rg-track {{ position:relative; height:12px; border-radius:999px; background:var(--track); }}
.rg-band {{ position:absolute; top:0; bottom:0; border-radius:999px; }}
.rg-limit {{ position:absolute; top:-6px; bottom:-6px; width:0; border-left:2px dashed var(--text); opacity:.7; }}
.rg-mark {{ position:absolute; top:50%; width:14px; height:14px; border-radius:50%; transform:translate(-50%,-50%); box-shadow:0 0 0 3px var(--panel); }}
.rg-lb {{ display:flex; justify-content:space-between; gap:8px; margin-top:9px; font-size:11px; color:var(--muted); white-space:nowrap; }}

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
.donut {{ width:min(210px, 70%); aspect-ratio:1; border-radius:50%; margin:18px auto 20px; display:flex; align-items:center; justify-content:center; }}
.donut-hole {{ width:72%; height:72%; border-radius:50%; background:var(--panel); display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; padding:0 10px; box-sizing:border-box; }}
.donut-hole b {{ font-size:30px; font-weight:900; color:var(--text); letter-spacing:-.02em; line-height:1.1; }}
.donut-hole span {{ font-size:11.5px; color:var(--muted); margin-top:4px; line-height:1.4; }}
.dlist {{ display:flex; flex-direction:column; gap:2px; margin:0 0 6px; }}
.dl-row {{ display:grid; grid-template-columns:10px minmax(0,1fr) auto auto 40px; align-items:center; gap:10px; padding:7px 4px; border-top:1px solid var(--border); font-size:12.5px; }}
.dl-row:first-child {{ border-top:0; }}
.dl-name {{ color:var(--text); font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.dl-n, .dl-amt {{ color:var(--muted); white-space:nowrap; }}
.dl-row b {{ text-align:right; color:var(--text); }}
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
/* 預算水位條（預測頁） */
.gauge {{ padding:34px 4px 6px; }}
.g-bar {{ position:relative; display:flex; height:46px; border-radius:12px; background:var(--track); }}
.g-seg {{ height:100%; display:flex; align-items:center; overflow:hidden; }}
.g-seg:first-child {{ border-radius:12px 0 0 12px; }}
.g-seg span {{ padding:0 12px; font-size:12.5px; font-weight:700; color:#fff; white-space:nowrap; text-shadow:0 1px 2px rgba(0,0,0,.35); }}
.g-hatch {{ background:repeating-linear-gradient(135deg, var(--c) 0 7px, {rgba(PANEL, .0)} 7px 12px), {rgba(TEXT, .04)}; box-shadow:inset 0 0 0 1.5px var(--c); }}
.g-hatch span {{ color:var(--text); text-shadow:none; background:var(--panel); padding:2px 8px; margin-left:8px; border-radius:6px; }}
.g-limit {{ position:absolute; top:-10px; bottom:-10px; width:0; border-left:2px dashed var(--text); }}
.g-limit em {{ position:absolute; bottom:calc(100% + 4px); left:0; font-style:normal; font-size:11.5px; color:var(--muted); white-space:nowrap; }}
.g-legend {{ display:flex; flex-wrap:wrap; gap:8px 22px; margin-top:16px; font-size:12.5px; color:var(--muted); }}
.g-legend span {{ display:inline-flex; align-items:center; gap:7px; }}
.g-legend b {{ color:var(--text); }}
.g-legend i {{ width:14px; height:14px; border-radius:4px; display:inline-block; }}
.okcard, .next {{ display:flex; align-items:flex-start; gap:8px; }}
.okcard .ico, .next .ico {{ margin-top:.2em; }}
.okcard .ico {{ color:{STATUS_COLORS['預算正常']}; }}
.next .ico {{ color:{ACCENT}; }}
.lead-tag .ico {{ vertical-align:-2px; }}
.check span {{ display:inline-flex; align-items:center; }}
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
    "精算部職缺招募延後": "Actuarial vacancies filled later than planned",
    "精算人力遇缺不補": "Actuarial vacancies filled later than planned",  # 舊版 CSV 相容
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
                    r = rng.uniform(.84, .90)                            # 精算部職缺招募延後
                    note = "精算部職缺招募延後"
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
# ---- 費用明細主檔（全部為虛構的合成資料，名稱僅求貼近真實作業樣貌）----
# 會計科目代碼：營業費用 61xx；一次性資本支出列在設備類 15xx。
GL_CODES = {
    "差旅費": "6121", "教育訓練費": "6131", "員工訓練費": "6132", "招募服務費": "6133",
    "雲端服務費": "6141", "軟體訂閱費": "6142", "資訊外包費": "6143", "設備維護費": "6144", "系統服務費": "6145",
    "核保系統服務費": "6146", "財務系統服務費": "6147", "監理申報系統費": "6148",
    "數位廣告費": "6151", "活動製作費": "6152", "行銷外包費": "6153", "行政維護費": "6161",
    "專業外包費": "6171", "顧問外包費": "6172", "外部查核費": "6173", "稅務顧問費": "6174", "法遵顧問費": "6175",
    "理賠查勘費": "6181", "理賠外包服務費": "6182", "精算資料服務費": "6191", "風險資料服務費": "6192",
    "一次性資本支出": "1561",
}
# 供應商（虛構）：(中文名稱, 英文名稱)
_V = {
    "cloud1": ("雲翔數位科技股份有限公司", "Cloudsoar Digital Technology"), "cloud2": ("澄峰雲端服務股份有限公司", "Clearpeak Cloud Services"),
    "sw1": ("恆碩軟體股份有限公司", "Hengshuo Software"), "sw2": ("聚擎資訊股份有限公司", "Juqing Information"),
    "si1": ("立衡系統整合股份有限公司", "Liheng Systems Integration"), "si2": ("宇晟資訊服務股份有限公司", "Yusheng IT Services"),
    "hw": ("晶宇電腦設備股份有限公司", "Jingyu Computer Equipment"),
    "ad1": ("星耀數位行銷股份有限公司", "Starlit Digital Marketing"), "ad2": ("曜境媒體股份有限公司", "Yaojing Media"),
    "event": ("匯展活動整合股份有限公司", "Huizhan Event Services"), "brand": ("青禾品牌顧問有限公司", "Qinghe Brand Consulting"),
    "travel": ("旅程通旅行社股份有限公司", "Tripway Travel Agency"), "claim": ("員工差旅報支", "Employee expense claims"),
    "uwtech": ("安碩保險科技股份有限公司", "Anshuo InsurTech"), "pro": ("景信專業服務股份有限公司", "Jingxin Professional Services"),
    "train1": ("知行企業管理顧問有限公司", "Zhixing Management Consulting"), "train2": ("博識學苑股份有限公司", "Boshi Academy"),
    "adj1": ("全誠保險公證人有限公司", "Quancheng Loss Adjusters"), "adj2": ("正衡保險公證人有限公司", "Zhengheng Loss Adjusters"),
    "claimsvc": ("迅達理賠服務股份有限公司", "Xunda Claims Services"),
    "actdata": ("衡量精算資料股份有限公司", "Hengliang Actuarial Data"), "actcon": ("鼎睿精算顧問有限公司", "Dingrui Actuarial Consulting"),
    "fintech": ("匯算財務科技股份有限公司", "Huisuan FinTech"), "cpa": ("誠正聯合會計師事務所", "Chengzheng & Partners CPAs"),
    "tax": ("宏律稅務顧問有限公司", "Honglu Tax Advisory"), "hr": ("才聚人力資源顧問股份有限公司", "Caiju HR Consulting"),
    "fm1": ("安居物業管理股份有限公司", "Anju Property Management"), "fm2": ("清樂環境清潔有限公司", "Qingle Cleaning Services"),
    "law": ("理信法律事務所", "Lixin Law Offices"), "reg": ("合規通科技股份有限公司", "RegLink Technology"),
    "risk": ("衡風風險資料股份有限公司", "Hengfeng Risk Data"),
}
ACCOUNT_VENDORS = {
    "雲端服務費": ["cloud1", "cloud2"], "軟體訂閱費": ["sw1", "sw2"], "資訊外包費": ["si1", "si2"], "設備維護費": ["hw", "si2"],
    "數位廣告費": ["ad1", "ad2"], "活動製作費": ["event"], "行銷外包費": ["brand", "ad2"], "差旅費": ["travel", "claim"],
    "核保系統服務費": ["uwtech"], "專業外包費": ["pro"], "教育訓練費": ["train1", "train2"], "員工訓練費": ["train2", "train1"],
    "理賠查勘費": ["adj1", "adj2"], "理賠外包服務費": ["claimsvc"], "系統服務費": ["si1", "sw2"],
    "精算資料服務費": ["actdata"], "顧問外包費": ["actcon", "pro"], "財務系統服務費": ["fintech"], "外部查核費": ["cpa"],
    "稅務顧問費": ["tax"], "招募服務費": ["hr"], "行政維護費": ["fm1", "fm2"],
    "法遵顧問費": ["law", "pro"], "監理申報系統費": ["reg"], "風險資料服務費": ["risk"], "一次性資本支出": ["hw", "si1"],
}
VENDOR_EN = {zh: en for zh, en in _V.values()}
COST_CENTERS = {
    "資訊部": ["IT110 基礎架構", "IT120 應用開發", "IT130 資訊安全"], "行銷部": ["MK210 數位行銷", "MK220 品牌活動"],
    "核保部": ["UW310 個人核保", "UW320 團體核保"], "理賠部": ["CL410 理賠審核", "CL420 理賠查勘"],
    "精算部": ["AC510 商品精算", "AC520 評價精算"], "財務部": ["FN610 會計", "FN620 財務規劃"],
    "人資行政部": ["HR710 人才發展", "HR720 總務行政"], "法遵風控部": ["RC810 法令遵循", "RC820 風險管理"],
}
# 專案：(部門, 年度) → (代碼名稱, 歸屬到此專案的科目)；其餘費用歸「日常營運」
DEPT_PROJECTS = {
    ("資訊部", 2026): ("PRJ-IT26-01 雲端遷移計畫", {"雲端服務費", "資訊外包費"}),
    ("資訊部", 2024): ("PRJ-IT24-03 伺服器汰換", {"一次性資本支出", "設備維護費"}),
    ("資訊部", 2022): ("PRJ-IT22-02 資料中心 UPS 汰換", {"一次性資本支出"}),
    ("法遵風控部", 2026): ("PRJ-RC26-01 TW-ICS 接軌", {"法遵顧問費", "監理申報系統費", "一次性資本支出"}),
    ("財務部", 2026): ("PRJ-FN26-01 IFRS 17 財報上線", {"財務系統服務費", "一次性資本支出"}),
    ("精算部", 2025): ("PRJ-AC25-01 IFRS 17 精算引擎", {"軟體訂閱費", "一次性資本支出"}),
    ("核保部", 2025): ("PRJ-UW25-01 核保系統升級", {"核保系統服務費"}),
    ("理賠部", 2025): ("PRJ-CL25-01 理賠影像系統升級", {"系統服務費", "一次性資本支出"}),
    ("人資行政部", 2026): ("PRJ-HR26-01 數位學習平台", {"員工訓練費"}),
}
OPEX_PROJECT = "OPEX 日常營運"
# 各部門人員（虛構姓名）：第一位為部門主管；顯示時依檢視身分決定是否遮罩
_STAFF_NAMES = ["陳怡君", "林家豪", "黃雅婷", "張志明", "李佳穎", "王俊傑", "吳佩珊", "劉冠宇", "蔡宜庭", "楊承恩",
                "許雅雯", "鄭宇翔", "謝欣怡", "郭柏翰", "洪詩涵", "曾子軒", "周品妤", "邱建宏", "賴思妤", "徐國峰",
                "蘇郁婷", "葉信宏", "莊雅筑", "呂明哲", "江婉婷", "何昱廷", "羅敏慧", "高偉倫", "潘怡如", "簡志豪",
                "朱佩君", "彭家瑋", "游淑芬", "詹宗翰", "胡雅琪", "施俊宏", "沈佳蓉", "余冠廷", "盧欣妤", "梁哲維"]
DEPT_STAFF = {d.split(" (")[0]: [(f"E{i + 1}{j + 1:03d}", _STAFF_NAMES[i * 5 + j], "部門主管" if j == 0 else ("經理" if j == 1 else "專員"))
                                   for j in range(5)] for i, d in enumerate(DEPTS)}
EMPLOYEE_NAMES = {code: name for staff in DEPT_STAFF.values() for code, name, _ in staff}
CFO_APPROVAL_LIMIT = 2_000_000  # 單筆 NT$ 200 萬以上需財務長核准
LINE_MEMOS = {
    "雲端服務費": ["雲端運算資源月租", "儲存與流量超額使用"], "軟體訂閱費": ["軟體授權年費分攤", "使用者授權加購"],
    "資訊外包費": ["系統維運外包月費", "專案開發人月費"], "設備維護費": ["伺服器維護合約", "端點設備維修"],
    "數位廣告費": ["搜尋與社群廣告投放", "程序化廣告投放"], "活動製作費": ["客戶說明會場地與製作", "通路激勵活動"],
    "差旅費": ["客戶與通路拜訪差旅", "研討會與訓練差旅"], "教育訓練費": ["專業證照課程", "內部講師訓練"],
    "員工訓練費": ["新進人員訓練", "主管領導力課程"], "理賠查勘費": ["理賠案件公證查勘", "颱風季急件查勘"],
    "外部查核費": ["年度財報查核公費", "內控專案查核"], "法遵顧問費": ["法規遵循諮詢", "監理申報顧問"],
}

MEMO_EN = {
    "雲端運算資源月租": "Cloud compute monthly fee", "儲存與流量超額使用": "Storage and bandwidth overage",
    "軟體授權年費分攤": "Annual licence amortisation", "使用者授權加購": "Additional user licences",
    "系統維運外包月費": "Managed service monthly fee", "專案開發人月費": "Project development man-months",
    "伺服器維護合約": "Server maintenance contract", "端點設備維修": "End-user device repair",
    "搜尋與社群廣告投放": "Search and social ads", "程序化廣告投放": "Programmatic ads",
    "客戶說明會場地與製作": "Client seminar venue and production", "通路激勵活動": "Channel incentive event",
    "客戶與通路拜訪差旅": "Client and channel visits", "研討會與訓練差旅": "Conference and training travel",
    "專業證照課程": "Professional certification course", "內部講師訓練": "Internal trainer programme",
    "新進人員訓練": "New-hire training", "主管領導力課程": "Leadership programme",
    "理賠案件公證查勘": "Claims loss adjusting", "颱風季急件查勘": "Typhoon-season urgent inspections",
    "年度財報查核公費": "Annual audit fee", "內控專案查核": "Internal control review",
    "法規遵循諮詢": "Compliance advisory", "監理申報顧問": "Regulatory reporting advisory", "資本支出": "Capital expenditure",
}
APPROVAL_EN = {"部門主管": "Department head", "財務長": "CFO"}

def show_memo(memo):
    return (MEMO_EN.get(memo) or EVENT_EN.get(memo) or ACCOUNT_EN.get(memo, memo)) if IS_EN else memo

def show_employee(code, name, department):
    """Personal names are visible only to the CFO and to the department's own head; others see a masked name."""
    if VIEW_ROLE == "cfo" or (VIEW_ROLE == "head" and department.split(" (")[0] == VIEW_DEPT_KEY):
        return f"{code} {name}"
    return f"{code} {name[0]}○{name[-1]}"

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
    """Invoice-level synthetic ledger: several dated lines per category and month, each with GL code, vendor,
    cost centre, project, requester and approval level. Monthly totals reconcile exactly to the monthly Actual."""
    rng = np.random.default_rng(20261021)
    result = []
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
        project_name, project_accounts = DEPT_PROJECTS.get((dept_key, int(row.Year)), (None, set()))
        staff = DEPT_STAFF[dept_key]
        centers = COST_CENTERS[dept_key]

        def add_line(account, amount, expense_id=None, memo=None, vendor=None):
            nonlocal seq
            vendor_keys = ACCOUNT_VENDORS[account]
            vendor = vendor or _V[vendor_keys[int(rng.integers(len(vendor_keys)))]][0]
            memos = LINE_MEMOS.get(account, [account])
            code, name, _ = staff[1 + int(rng.integers(len(staff) - 1))]
            in_project = project_name and account in project_accounts and (account == "一次性資本支出" or rng.random() < .7)
            day = int(rng.integers(1, 29))
            result.append({
                "Year": row.Year, "Month": row.Month, "Department": row.Department,
                "Invoice_Date": f"{row.Year}-{row.Month:02d}-{day:02d}",
                "Expense_ID": expense_id or f"AP{row.Year}{row.Month:02d}{seq:05d}",
                "Purchase_Order": f"PO{row.Year}{seq:06d}",
                "GL_Code": GL_CODES[account], "Account": account,
                "Vendor": vendor, "Description": memo or memos[int(rng.integers(len(memos)))],
                "Cost_Center": centers[int(rng.integers(len(centers)))],
                "Project": project_name if in_project else OPEX_PROJECT,
                "Employee": code, "Employee_Name": name,
                "Approval": "財務長" if amount >= CFO_APPROVAL_LIMIT else "部門主管",
                "Amount": int(amount), "Source": "合成示範資料",
            })
            seq += 1

        for (account, _), share in zip(profile, shares):
            account_total = round(recurring_actual * share)
            duplicate_example = dept_key == "資訊部" and row.Year == 2026 and row.Month == 6 and account == "雲端服務費"
            if duplicate_example:
                # 合成重複請款：同一張發票號碼被登錄兩次，供「可能重複的費用明細」示範
                half = account_total // 2
                dup_id = f"AP{row.Year}{row.Month:02d}{seq:05d}"
                add_line(account, half, dup_id, "雲端運算資源月租", _V["cloud1"][0])
                add_line(account, account_total - half, dup_id, "雲端運算資源月租", _V["cloud1"][0])
                continue
            n_lines = int(rng.integers(2, 6))
            weights = rng.dirichlet(np.full(n_lines, 1.6))
            amounts = [int(round(account_total * w)) for w in weights]
            amounts[-1] = account_total - sum(amounts[:-1])
            for amount in amounts:
                add_line(account, amount)
        if one_off_amount > 0:
            add_line("一次性資本支出", round(one_off_amount), memo=str(row.EventNote).strip() or "資本支出")
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

@st.cache_data(show_spinner=False, max_entries=128)
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
    """Cached entry point: the forecast + backtest loop is the slowest part of every rerun, and its result
    only changes with the data, year, departments, language (text fields) and alert thresholds."""
    thresholds = tuple(st.session_state.get(k, d) for k, d in (("thr_watch_pct", 102), ("thr_high_pct", 105), ("thr_lag_pct", 90)))
    return _analyze_budget(data, target_year, tuple(target_depts), IS_EN, thresholds).copy()

@st.cache_data(show_spinner=False, max_entries=64)
def _analyze_budget(data, target_year, target_depts, lang_en_key, thresholds_key):
    # lang_en_key / thresholds_key are unused in the body; they only key the cache (tx() and classify_status read globals).
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
def fmc(val, signed=False):
    """Amounts the way Taiwanese readers say them: 1 億以上用「億」（30 億、30.71 億），以下用「萬」（2,950 萬）.
    English uses B / M. Cards lead with a percentage; this is the supporting figure."""
    val = float(val)
    v = abs(val)
    trim = lambda x: f"{x:,.2f}".rstrip("0").rstrip(".")
    if IS_EN:
        body = f"NT${trim(v / 1e9)}B" if v >= 1e9 else f"NT${v / 1e6:,.1f}M" if v >= 1e6 else f"NT${v / 1e3:,.0f}K"
    else:
        body = f"{trim(v / 1e8)} 億" if v >= 1e8 else f"{v / 1e4:,.0f} 萬" if v >= 1e4 else f"{v:,.0f} 元"
    is_zero = body.startswith(("0 ", "NT$0", "0.0"))
    sign = "-" if val < 0 and not is_zero else ("+" if signed and val > 0 and not is_zero else "")
    return sign + body

def fm_num(val, signed=False):
    """Number part for tables whose header carries the unit: 新台幣萬元 integers (NT$ millions in English)."""
    n = float(val) / (1e6 if IS_EN else 1e4)
    body = f"{abs(n):,.1f}" if IS_EN else f"{abs(n):,.0f}"
    if n < 0 and float(body.replace(",", "")) != 0:
        return "-" + body
    return f"+{body}" if signed and n > 0 and float(body.replace(",", "")) != 0 else body

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
    """NT$ → table unit: 新台幣萬元 (integer) in Chinese, NT$ millions in English."""
    values = pd.to_numeric(series, errors="coerce")
    return (values / 1e6).round(1) if IS_EN else (values / 1e4).round(0)

def to_m_text(series):
    """Same unit as to_m, as right-aligned text for columns that can be empty: shows — instead of Streamlit's "None"."""
    return ["—" if pd.isna(v) else fm_num(v) for v in pd.to_numeric(pd.Series(series), errors="coerce")]

MONEY_TEXT = dict(alignment="right")

MONEY_FMT = "%,.1f" if IS_EN else "%,d"  # 金額欄位：千分位；中文為萬元整數

def status_label(status):
    return show_status(status)

@st.cache_resource(show_spinner=False)
def plot_template(dark):
    # 以名稱指定 template 每張圖要 ~40ms（每次重新驗證整份含各圖型預設）；只取 layout 預先建好約 4ms。
    # 各圖表都自行指定 trace 顏色，不需要 template 的 data 區段。
    import plotly.io as pio
    return go.layout.Template(layout=pio.templates["plotly_dark" if dark else "plotly_white"].layout)

PLOT_TEMPLATE = plot_template(IS_DARK)
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
    # 刻度直接帶單位（10 億、5,000 萬），和卡片、標籤的說法一致
    span = max(abs(ticks[0]), abs(ticks[-1]))
    if IS_EN:
        label_fmt = (lambda v: f"{v / 1e9:g}B") if span >= 1e9 else (lambda v: f"{v / 1e6:,.0f}M")
    else:
        label_fmt = (lambda v: f"{v / 1e8:g} 億") if span >= 1e8 else (lambda v: f"{v / 1e4:,.0f} 萬")
    axis = fig.update_xaxes if horizontal else fig.update_yaxes
    axis(tickmode="array", tickvals=ticks, ticktext=["0" if abs(v) < 1e-9 else label_fmt(v) for v in ticks], title_text=None,
         range=[ticks[0] - step * .02 if bottom < 0 else 0, ticks[-1]])
    for trace in fig.data:
        if trace.type == "waterfall":
            trace.hovertemplate = "<b>%{x}</b><br>%{text}<extra></extra>"
            continue
        if trace.type not in ("bar", "scatter") or trace.hovertemplate == "skip":
            continue
        name = trace.name or ""
        source = trace.x if horizontal else trace.y
        if trace.customdata is None and source is not None:
            # hover 用和卡片相同的億／萬格式，而不是 NT$ 1,952,873,970 這種原始數字
            trace.customdata = [fmc(v) if pd.notna(v) else "" for v in pd.to_numeric(pd.Series(list(source)), errors="coerce")]
            amount = "%{customdata}"
        else:
            amount = f"NT$ %{{{'x' if horizontal else 'y'}:,.0f}}"
        if horizontal:
            trace.hovertemplate = f"<b>%{{y}}</b><br>{name}: {amount}<extra></extra>"
        else:
            trace.hovertemplate = f"<b>%{{x}}</b><br>{name}: {amount}<extra></extra>"
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

def explain_card(title, steps):
    """「這頁在看什麼」：用 3 個步驟說明一個分析在做什麼，給第一次看的評審與組員。"""
    items = "".join(f'<div class="explain-step"><b>{i}</b><span>{s}</span></div>' for i, s in enumerate(steps, 1))
    st.markdown(f'<div class="explain"><div class="explain-title">{icon("sparkles", 15, ACCENT)}{title}</div>'
                f'<div class="explain-steps">{items}</div></div>', unsafe_allow_html=True)

def chart_hint(text):
    """One plain-language line under a chart title: what to look at and what it means."""
    st.markdown(f'<div class="chart-hint">{icon("arrow", 12)}<span>{text}</span></div>', unsafe_allow_html=True)

def show_chart(fig, title=None, help_text=None, key=None, caption=None, hint=None):
    """Render a chart inside a card with a heading, an optional 「怎麼看」 line and a hover help icon."""
    with card(key):
        if title:
            st.markdown(f'<div class="chart-title">{title}</div>', unsafe_allow_html=True, help=help_text)
        if hint:
            chart_hint(hint)
        st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG, theme=None, key=f"chart-{key}" if key else None)
        if caption:
            st.caption(caption)

_svg_ids = itertools.count()

def _clean(values):
    return [float(v) if v is not None and pd.notna(v) else None for v in values]

def ui_area(values, color, ref=None, height=64):
    """Full-bleed area sparkline with a vertical gradient fill (optionally with a dashed reference line)."""
    series, reference = _clean(values), _clean(ref or [])
    pool = [v for v in series + reference if v is not None]
    if len(pool) < 2:
        return ""
    lo, hi = min(pool), max(pool)
    span = (hi - lo) or 1.0
    n = max(len(series), len(reference), 2)

    def xy(seq):
        return [(i / (n - 1) * 100, (1 - (v - lo) / span) * (height - 10) + 6) for i, v in enumerate(seq) if v is not None]
    pts = xy(series)
    line = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    area = f"{pts[0][0]:.2f},{height} {line} {pts[-1][0]:.2f},{height}"
    gid = f"ga{next(_svg_ids)}"
    ref_line = ""
    if reference:
        ref_pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in xy(reference))
        ref_line = (f'<polyline points="{ref_pts}" fill="none" stroke="{MUTED}" stroke-width="1.3" '
                    f'stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>')
    return (f'<svg viewBox="0 0 100 {height}" preserveAspectRatio="none">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{color}" stop-opacity=".42"/><stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
            f'<polygon points="{area}" fill="url(#{gid})"/>{ref_line}'
            f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.2" '
            f'stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>')

def ui_bars(values, colors, height=64):
    """Full-bleed column sparkline; negative values hang below a zero line. colors: one per bar."""
    series = [v or 0.0 for v in _clean(values)]
    if not series:
        return ""
    top, bottom = max(series + [0.0]), min(series + [0.0])
    span = (top - bottom) or 1.0
    usable = height - 8
    zero = 4 + top / span * usable
    slot = 100 / len(series)
    rects = []
    for i, (v, c) in enumerate(zip(series, colors)):
        h = max(abs(v) / span * usable, .8)
        y = zero - h if v >= 0 else zero
        rects.append(f'<rect x="{i * slot + slot * .2:.2f}" y="{y:.2f}" width="{slot * .6:.2f}" height="{h:.2f}" fill="{c}"/>')
    baseline = (f'<line x1="0" x2="100" y1="{zero:.2f}" y2="{zero:.2f}" stroke="{BORDER}" stroke-width="1" '
                f'vector-effect="non-scaling-stroke"/>') if bottom < 0 else ""
    return f'<svg viewBox="0 0 100 {height}" preserveAspectRatio="none">{baseline}{"".join(rects)}</svg>'


def ui_range(low, mid, high, color):
    """Bullet gauge in % of budget: P80 band, forecast marker and the 100% budget line."""
    lo, hi = min(low, mid, 90.0), max(high, mid, 110.0)
    pos = lambda v: (v - lo) / (hi - lo) * 100
    return (f'<div class="rg"><div class="rg-track"><i class="rg-band" style="left:{pos(low):.1f}%;width:{pos(high) - pos(low):.1f}%;background:{rgba(color, .28)}"></i>'
            f'<i class="rg-limit" style="left:{pos(100):.1f}%"></i><i class="rg-mark" style="left:{pos(mid):.1f}%;background:{color}"></i></div>'
            f'<div class="rg-lb"><span>{tx("P80 區間", "P80 range")} {low:.0f}%–{high:.0f}%</span><span>{tx("預算 100%", "Budget 100%")}</span></div></div>')

def ui_delta(text, color, direction=None):
    """'vs last period' pill; direction 'up'/'down' adds a trend arrow."""
    arrow = icon(direction, 12, stroke=2.6) if direction in ("up", "down") else ""
    return f'<span class="delta" style="color:{color};background:{rgba(color, .14)};border:1px solid {rgba(color, .32)}">{arrow}{text}</span>'

def ui_kpi(label, value, sub, icon_name, color, glow=False, viz="", delta="", help=None):
    """The one number-card design used everywhere. Without `viz` it renders the compact variant."""
    if glow:
        background = f"linear-gradient(160deg,{rgba(color, .16)},{PANEL} 65%)"
        shadow = f"0 0 0 1px {rgba(color, .40)},0 12px 32px {rgba(color, .18)}"
        border = rgba(color, .55)
    else:
        background = f"linear-gradient(160deg,{RAISED},{PANEL} 70%)"
        shadow = f"0 8px 26px rgba(0,0,0,{.22 if IS_DARK else .05})"
        border = BORDER
    tip = f'<span class="tip" data-tip="{html.escape(help, quote=True)}">?</span>' if help else ""
    body = f'<div class="viz">{viz}</div>' if viz else ""
    return (f'<div class="kpi{"" if viz else " compact"}" style="background:{background};box-shadow:{shadow};border-color:{border}">'
            f'<div class="top"><div class="ic" style="background:{rgba(color, .14)};color:{color}">{icon(icon_name, 17)}</div>'
            f'<div class="lb">{label}</div>{tip}</div><div class="vl">{value}</div>'
            f'<div class="meta">{delta}<span class="sb" title="{html.escape(sub, quote=True)}">{sub}</span></div>{body}</div>')

def stat_row(cards):
    """Render a row of ui_kpi cards with equal heights and 4 → 2 → 1 (or 3 → 1) responsive columns."""
    st.markdown(f'<div class="kpi-wrap"><div class="kpi-grid c{len(cards)}" style="--cols:{len(cards)}">{"".join(cards)}</div></div>',
                unsafe_allow_html=True)

# ------------------------------------------
# PDF 報告：下載檔一律為設計過的 PDF（固定淺色版面，適合列印、轉寄與簽核）
# ------------------------------------------
PDF_FONT = Path(__file__).with_name("fonts") / "NotoSansTC-VF.ttf"  # Noto Sans TC（SIL OFL），雲端與本機產出一致
PDF_INK, PDF_MUTED, PDF_LINE, PDF_SOFT = (17, 24, 39), (90, 98, 114), (226, 229, 235), (246, 247, 250)
PDF_BRAND = (79, 70, 229)
PDF_WRAP = WrapMode.WORD if IS_EN else WrapMode.CHAR  # 中文逐字換行；英文依單字換行
PDF_STATUS = {"高風險超支": (214, 51, 74), "需注意": (183, 106, 0), "執行落後": (4, 121, 168), "預算正常": (17, 138, 88)}

class BudgetPDF(FPDF):
    def __init__(self, doc_title, footer_note):
        super().__init__(format="A4", unit="mm")
        self.doc_title, self.footer_note = doc_title, footer_note
        self.set_margins(16, 18, 16)
        self.set_auto_page_break(True, 18)
        self.add_font("tc", "", str(PDF_FONT), variations={"wght": 400})
        self.add_font("tc", "B", str(PDF_FONT), variations={"wght": 700})
        self.set_title(doc_title)
        self.set_author("BNP Paribas Cardif TW · Budget Command Center")

    @property
    def body_w(self):
        return self.w - self.l_margin - self.r_margin

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("tc", "", 8)
        self.set_text_color(*PDF_MUTED)
        self.set_xy(self.l_margin, 8)
        self.cell(0, 5, self.doc_title)
        self.set_draw_color(*PDF_LINE)
        self.line(self.l_margin, 14, self.w - self.r_margin, 14)
        self.set_y(18)

    def footer(self):
        self.set_y(-12)
        self.set_font("tc", "", 7.5)
        self.set_text_color(*PDF_MUTED)
        self.cell(self.body_w - 20, 5, self.footer_note)
        self.cell(20, 5, f"{self.page_no()} / {{nb}}", align="R")

    def cover(self, title, subtitle, meta):
        self.add_page()
        self.set_fill_color(*PDF_INK)
        self.rect(0, 0, self.w, 60, "F")
        self.set_fill_color(*PDF_BRAND)
        self.rect(0, 60, self.w, 1.6, "F")
        self.set_xy(self.l_margin, 14)
        self.set_font("tc", "", 9)
        self.set_text_color(186, 190, 255)
        self.cell(0, 5, "BNP PARIBAS CARDIF TW · " + tx("管理會計", "MANAGEMENT ACCOUNTING"))
        self.set_xy(self.l_margin, 22)
        self.set_font("tc", "B", 22)
        self.set_text_color(255, 255, 255)
        self.cell(0, 11, title)
        self.set_xy(self.l_margin, 35)
        self.set_font("tc", "", 10.5)
        self.set_text_color(205, 210, 222)
        self.cell(0, 6, subtitle)
        x = self.l_margin
        self.set_font("tc", "", 8.5)
        for item in meta:
            w = self.get_string_width(item) + 8
            self.set_fill_color(42, 48, 64)
            self.set_text_color(232, 235, 242)
            self.set_xy(x, 46)
            self.cell(w, 6.5, item, fill=True, align="C")
            x += w + 3
        self.set_y(70)

    def ensure_space(self, height):
        if self.get_y() + height > self.h - self.b_margin:
            self.add_page()

    def heading(self, text):
        self.ensure_space(22)
        y = self.get_y()
        self.set_fill_color(*PDF_BRAND)
        self.rect(self.l_margin, y + 1, 1.4, 5.2, "F")
        self.set_xy(self.l_margin + 3.5, y)
        self.set_font("tc", "B", 12)
        self.set_text_color(*PDF_INK)
        self.cell(0, 7, text)
        self.ln(10)

    def paragraph(self, text, size=10, color=PDF_INK):
        self.set_font("tc", "", size)
        self.set_text_color(*color)
        self.set_x(self.l_margin)
        self.multi_cell(0, size * .56, text, markdown=True, align="L", wrapmode=PDF_WRAP)
        self.ln(2.5)

    def bullet(self, text, rgb=PDF_BRAND):
        self.ensure_space(10)
        y = self.get_y()
        self.set_fill_color(*rgb)
        self.ellipse(self.l_margin + 1.5, y + 1.9, 1.7, 1.7, "F")
        self.set_xy(self.l_margin + 6, y)
        self.set_font("tc", "", 9.5)
        self.set_text_color(*PDF_INK)
        self.multi_cell(self.body_w - 6, 5.3, text, markdown=True, align="L", wrapmode=PDF_WRAP)
        self.ln(1.2)

    def markdown_block(self, md):
        for raw in md.splitlines():
            line = raw.strip()
            if not line:
                self.ln(1.5)
            elif line.startswith("#"):
                self.heading(line.lstrip("#").strip())
            elif line[:2] in ("- ", "* ", "• "):
                self.bullet(line[2:].strip())
            elif re.match(r"^\d+[.、]\s*", line):
                self.bullet(line)
            elif line.startswith(">"):
                self.paragraph(line.lstrip("> "), size=8.5, color=PDF_MUTED)
            else:
                self.paragraph(line)

    def kpis(self, items):
        gap, h = 4, 27
        w = (self.body_w - gap * (len(items) - 1)) / len(items)
        self.ensure_space(h + 8)
        y = self.get_y()
        for i, (label, value, sub, rgb) in enumerate(items):
            x = self.l_margin + i * (w + gap)
            self.set_fill_color(*PDF_SOFT)
            self.set_draw_color(*PDF_LINE)
            self.rect(x, y, w, h, "DF", round_corners=True, corner_radius=2.5)
            self.set_fill_color(*rgb)
            self.rect(x, y + 4, 1.2, h - 8, "F")
            for dy, size, style, color, text in ((3.5, 8, "", PDF_MUTED, label), (9.5, 15, "B", rgb, value), (19.5, 7.5, "", PDF_MUTED, sub)):
                self.set_xy(x + 5, y + dy)
                self.set_font("tc", style, size)
                while size > 8 and self.get_string_width(text) > w - 8:  # 長數字自動縮小，不超出卡片
                    size -= .5
                    self.set_font("tc", style, size)
                self.set_text_color(*color)
                self.cell(w - 8, size * .5, text)
        self.set_y(y + h + 8)

    def table(self, headers, rows, widths, aligns, row_colors=None):
        widths = [w * self.body_w / sum(widths) for w in widths]

        def head():
            self.set_font("tc", "B", 8.5)
            self.set_fill_color(*PDF_INK)
            self.set_text_color(255, 255, 255)
            for text, w, a in zip(headers, widths, aligns):
                self.cell(w, 7.5, text, fill=True, align=a)
            self.ln()
            self.set_font("tc", "", 8.5)

        table_h = 7.5 + 7 * len(rows)
        self.ensure_space(table_h if table_h < self.h - self.t_margin - self.b_margin - 10 else 20)  # 短表格不拆頁
        head()
        self.set_fill_color(*PDF_SOFT)
        for i, row in enumerate(rows):
            if self.get_y() + 7 > self.h - self.b_margin:
                self.add_page()
                head()
                self.set_fill_color(*PDF_SOFT)
            for j, (value, w, a) in enumerate(zip(row, widths, aligns)):
                color = (row_colors[i][j] if row_colors and row_colors[i][j] else PDF_INK)
                self.set_text_color(*color)
                self.cell(w, 7, str(value), fill=i % 2 == 1, align=a)
            self.ln()
        self.set_draw_color(*PDF_LINE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(5)

    def bars(self, items, caption):
        top = max([120.0] + [p + 5 for _, p, _, _ in items])
        label_w, value_w = 30, 36
        bar_w = self.body_w - label_w - value_w
        x0 = self.l_margin + label_w
        self.ensure_space(len(items) * 7.5 + 10)
        for name, pct, rgb, label in items:
            y = self.get_y()
            self.set_xy(self.l_margin, y)
            self.set_font("tc", "", 9)
            self.set_text_color(*PDF_INK)
            self.cell(label_w, 6, name)
            self.set_fill_color(236, 238, 243)
            self.rect(x0, y + 1.5, bar_w, 3.4, "F", round_corners=True, corner_radius=1.7)
            self.set_fill_color(*rgb)
            self.rect(x0, y + 1.5, max(1.0, bar_w * min(pct, top) / top), 3.4, "F", round_corners=True, corner_radius=1.7)
            limit_x = x0 + bar_w * 100 / top
            self.set_draw_color(*PDF_INK)
            self.set_dash_pattern(dash=.8, gap=.6)
            self.line(limit_x, y + .2, limit_x, y + 6.2)
            self.set_dash_pattern()
            self.set_xy(x0 + bar_w, y)
            self.set_font("tc", "B", 9)
            self.set_text_color(*rgb)
            self.cell(value_w, 6, label, align="R")
            self.ln(7.5)
        self.paragraph(caption, size=8, color=PDF_MUTED)

    def fields(self, pairs):
        for key, value in pairs:
            self.ensure_space(9)
            self.set_x(self.l_margin)
            self.set_draw_color(*PDF_LINE)
            self.set_fill_color(*PDF_SOFT)
            self.set_font("tc", "", 9)
            self.set_text_color(*PDF_MUTED)
            self.cell(46, 8.5, "  " + key, border="B", fill=True)
            self.set_font("tc", "B", 9.5)
            self.set_text_color(*PDF_INK)
            self.cell(0, 8.5, "  " + value, border="B")
            self.ln()
        self.ln(5)

    def note_box(self, text):
        self.set_font("tc", "", 9.5)
        height = self.multi_cell(self.body_w - 10, 5.6, text, dry_run=True, output=MethodReturnValue.HEIGHT, align="L", wrapmode=PDF_WRAP) + 9
        self.ensure_space(height + 4)
        y = self.get_y()
        self.set_fill_color(*PDF_SOFT)
        self.rect(self.l_margin, y, self.body_w, height, "F", round_corners=True, corner_radius=2)
        self.set_xy(self.l_margin + 5, y + 4.5)
        self.set_text_color(*PDF_INK)
        self.multi_cell(self.body_w - 10, 5.6, text, align="L", wrapmode=PDF_WRAP)
        self.set_y(y + height + 6)

    def signatures(self, roles):
        gap, h = 4, 28
        w = (self.body_w - gap * (len(roles) - 1)) / len(roles)
        self.ensure_space(h + 6)
        y = self.get_y()
        for i, role in enumerate(roles):
            x = self.l_margin + i * (w + gap)
            self.set_draw_color(*PDF_LINE)
            self.rect(x, y, w, h, "D", round_corners=True, corner_radius=2)
            self.set_xy(x, y + 2.5)
            self.set_font("tc", "B", 9)
            self.set_text_color(*PDF_INK)
            self.cell(w, 5, role, align="C")
            self.set_xy(x, y + h - 7.5)
            self.set_font("tc", "", 7.5)
            self.set_text_color(*PDF_MUTED)
            self.cell(w, 5, tx("簽章／日期", "Signature / date"), align="C")
        self.set_y(y + h + 6)

def render_pdf(doc):
    """doc = {title, subtitle, meta, blocks: [(kind, *args)]} → PDF bytes. Called lazily from download buttons."""
    pdf = BudgetPDF(doc["title"], tx("內建資料為競賽展示用合成資料，不代表任何公司實際數據。", "Built-in data is synthetic for the hackathon demo."))
    pdf.cover(doc["title"], doc["subtitle"], doc["meta"])
    blocks = doc["blocks"]
    for i, (kind, *args) in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if kind == "heading" and nxt and nxt[0] == "table":
            # 標題和後面的短表格放在同一頁，避免標題孤零零留在頁尾
            table_h = 7.5 + 7 * len(nxt[2])
            if table_h < pdf.h - pdf.t_margin - pdf.b_margin - 20:
                pdf.ensure_space(10 + table_h)
        getattr(pdf, kind)(*args)
    return bytes(pdf.output())

# 線條圖示（Lucide 風格），取代 emoji，用於自訂 HTML 區塊。
ICON_PATHS = {
    "wallet": '<path d="M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h14a2 2 0 0 1 2 2v3"/><path d="M3 5v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-3"/><path d="M21 12h-4a2 2 0 0 0 0 4h4z"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "trending": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    "check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "arrow": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "sparkles": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "building": '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01M16 6h.01M12 6h.01M12 10h.01M12 14h.01M16 10h.01M16 14h.01M8 10h.01M8 14h.01"/>',
    "sliders": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "up": '<path d="M7 17 17 7"/><path d="M8 7h9v9"/>',
    "down": '<path d="M7 7l10 10"/><path d="M17 8v9H8"/>',
}

def icon(name, size=16, color="currentColor", stroke=2):
    return (f'<svg class="ico" viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-linecap="round" stroke-linejoin="round" style="flex:0 0 auto;vertical-align:-0.15em">{ICON_PATHS[name]}</svg>')

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

def _local_host(host):
    """localhost → 127.0.0.1: Ollama only listens on IPv4, and Windows spends ~2s on the refused IPv6 attempt first."""
    return host.replace("://localhost", "://127.0.0.1")

@st.cache_data(ttl=30, show_spinner=False)
def list_ollama_models(host, api_key):
    """Return (installed model names, error text). Cached briefly so each rerun doesn't probe the server."""
    host = _local_host(host)
    parsed = urllib.parse.urlsplit(host)
    if parsed.hostname == "127.0.0.1":
        # Windows 連到沒在執行的本機埠不會立刻失敗，而是重試約 2–4 秒；每 30 秒重新偵測一次就會讓切頁卡住。
        # 先用 0.3 秒的 socket 測試，沒在執行就直接略過。
        try:
            socket.create_connection(("127.0.0.1", parsed.port or 11434), timeout=.3).close()
        except OSError:
            return [], "Ollama is not running"
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
        "options": {"temperature": 0.2, "num_ctx": 32768},  # 完整資料表約 1.5 萬 token，留足空間
    }
    request = urllib.request.Request(
        f"{_local_host(host)}/api/chat", data=json.dumps(payload).encode("utf-8"),
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
        f'<div class="sb-brand"><div class="sb-mark"><svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="#fff" '
        f'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l5-5 4 3 8-8"/><path d="M15 7h5v5"/></svg></div>'
        f'<div><div class="sb-title">{tx("預算決策中心", "Budget Command Center")}</div>'
        f'<div class="sb-sub">BNP Paribas Cardif TW · {tx("競賽展示版", "Hackathon demo")}</div></div></div>',
        unsafe_allow_html=True,
    )

# 原生主題（右上角選單）切換時 Streamlit 不會自動重跑，自訂樣式與圖表會停在舊配色。
# 這段腳本偵測原生背景亮度與目前渲染的主題不一致時，點擊隱藏按鈕觸發重跑，讓整頁一起換色。
with st.sidebar.container(key="theme_sync_slot"):
    st.button("theme-sync", key="theme_sync")
    st.html(f"""<script>
(() => {{
  const rendered = "{'dark' if IS_DARK else 'light'}";
  const tone = () => {{ const m = getComputedStyle(document.body).backgroundColor.match(/\\d+/g);
    return m && (0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2]) < 128 ? "dark" : "light"; }};
  clearInterval(window.__themeSync);
  window.__themeSync = setInterval(() => {{
    if (tone() !== rendered) {{ clearInterval(window.__themeSync); document.querySelector(".st-key-theme_sync button")?.click(); }}
  }}, 400);
}})();
</script>""", unsafe_allow_javascript=True)

# ---- 檢視身分（展示版的資料權限）：正式導入時改由公司 SSO 帳號自動帶入，使用者不能自己切換 ----
ROLE_LABELS = {
    "cfo": tx("財務長（全公司）", "CFO (all departments)"),
    "fpa": tx("財務分析師（全公司・個資遮罩）", "FP&A analyst (all, names masked)"),
    "head": tx("部門主管（僅本部門）", "Department head (own dept only)"),
}
ROLE_HELP = {
    "cfo": tx("可檢視全公司資料、經辦人姓名與所有系統設定。", "Sees all departments, handler names and every setting."),
    "fpa": tx("可檢視全公司數字；經辦人姓名遮罩（個資最小化）。", "Sees all departments; handler names are masked (data minimisation)."),
    "head": tx("只看得到本部門的預算、明細與 AI 回答；系統設定與資料匯入已鎖定。", "Sees only own-department budget, ledger and AI answers; settings and data import are locked."),
}
with sb_role:
    st.markdown(f'<div class="sb-label">{tx("檢視身分", "Viewing as")}</div>', unsafe_allow_html=True)
    VIEW_ROLE = st.selectbox(tx("檢視身分", "Viewing as"), list(ROLE_LABELS), format_func=ROLE_LABELS.get,
                             key="view_role", label_visibility="collapsed")
    VIEW_DEPT = None
    if VIEW_ROLE == "head":
        VIEW_DEPT = st.selectbox(tx("所屬部門", "Department"), DEPTS, format_func=show_dept, key="view_dept", label_visibility="collapsed")
    # 權限說明收進 ? 提示，側邊欄不再塞一大段文字
    st.markdown(f'<div class="sb-hint">{icon("shield", 13)} {tx("權限說明", "Access rules")}</div>', unsafe_allow_html=True,
                help=ROLE_HELP[VIEW_ROLE] + tx(" 正式導入時由公司 SSO 帳號自動帶入，使用者不能自行切換。", " In production this comes from company SSO and cannot be switched by users."))
VIEW_DEPT_KEY = VIEW_DEPT.split(" (")[0] if VIEW_DEPT else None

with sb_settings:
    st.markdown(f'<div class="sb-label">{tx("系統", "System")}</div>', unsafe_allow_html=True)
    with st.popover(tx("系統設定", "Settings"), icon=":material/settings:", width="stretch", disabled=VIEW_ROLE == "head",
                    help=tx("部門主管身分沒有系統設定權限", "Department heads cannot change system settings") if VIEW_ROLE == "head" else None):
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
            st.caption(tx(":material/lock: 公開模式：AI 服務與金鑰由管理者在伺服器端設定，訪客無法查看或修改。",
                          ":material/lock: Public mode: AI services and keys are configured on the server and cannot be viewed or changed by visitors."))
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
                st.caption(tx(f":material/warning: 目前連不到 Ollama（{ollama_error}）。本機請安裝 Ollama 並執行 `ollama pull {preferred_model}`。",
                              f":material/warning: Ollama is not reachable ({ollama_error}). Install Ollama locally and run `ollama pull {preferred_model}`."))
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
    # 年度用下拉選單（FY2026），部門收進彈出選單：兩個篩選並排在同一列，不再佔掉半個側邊欄
    year_col, dept_col_sb = st.columns([1, 1.25], gap="small")
    with year_col:
        selected_year = st.selectbox(tx("分析年度", "Fiscal year"), available_years[::-1], format_func=lambda y: f"FY{y}",
                                     key="fiscal_year", bind="query-params", label_visibility="collapsed")
    with dept_col_sb:
        if VIEW_ROLE == "head":
            # 部門主管：資料範圍鎖定在本部門，不能自行加選其他部門
            selected_depts = [VIEW_DEPT] if VIEW_DEPT in available_depts else available_depts[:1]
            st.popover(f"{show_dept(selected_depts[0])}", icon=":material/lock:", width="stretch", disabled=True,
                       help=tx("部門主管只能檢視本部門", "Department heads can only view their own department"))
        else:
            prior = st.session_state.get("dept_pills")
            n_sel = len(prior) if prior else len(available_depts)
            dept_label = tx("全部部門", "All depts") if n_sel in (0, len(available_depts)) else tx(f"{n_sel} 個部門", f"{n_sel} depts")
            with st.popover(dept_label, icon=":material/apartment:", width="stretch", key="dept_popover"):
                picked = st.pills(
                    tx("部門", "Departments"), available_depts, selection_mode="multi", default=available_depts,
                    format_func=show_dept, key="dept_pills",
                )
                st.caption(tx("未選擇任何部門時，預設分析全部部門。", "Select none to analyse all departments."))
            selected_depts = [d for d in available_depts if d in (picked or [])] or available_depts

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

@st.cache_data(show_spinner=False)
def _ai_data_tables(monthly_data, expense_data, lang_en, status_by_dept, selected_year_value, thresholds):
    """The whole loaded database as compact text tables (NT$ 萬, integers), so the assistant can answer any data question."""
    wan = lambda v: "" if pd.isna(v) else f"{v / 1e4:.0f}"  # 新台幣萬元整數，與表格單位一致
    name = lambda d: (DEPT_EN.get(d.split(" (")[0], d) if lang_en else d.split(" (")[0])
    monthly_lines = ["年度|部門|項目|1月 2月 3月 4月 5月 6月 7月 8月 9月 10月 11月 12月|全年合計（實際為已結算月份合計）"]
    annual_lines = ["年度|部門|年度預算|實際支出|已結算月數|執行率(實際÷同期預算)|狀態"]
    for (year, dept), g in monthly_data.sort_values(["Year", "Department", "Month"]).groupby(["Year", "Department"], sort=True):
        g = g.set_index("Month").reindex(MONTHS)
        closed = int(g.Actual.notna().sum())
        monthly_lines.append(f"{year}|{name(dept)}|預算|{' '.join(wan(v) for v in g.Budget)}|{wan(g.Budget.sum())}")
        monthly_lines.append(f"{year}|{name(dept)}|實際|{' '.join(wan(v) or '-' for v in g.Actual)}|{wan(g.Actual.sum(min_count=1))}")
        budget_to_date = g.Budget[g.Actual.notna()].sum()
        rate = g.Actual.sum() / budget_to_date * 100 if budget_to_date else float("nan")
        if closed == 12:
            status = show_status(classify_status(g.Actual.sum() / g.Budget.sum())) if g.Budget.sum() else ""
        elif year == selected_year_value and dept in status_by_dept:
            status = f"{status_by_dept[dept]}（依年底預測）"
        else:
            status = "進行中"
        annual_lines.append(f"{year}|{name(dept)}|{wan(g.Budget.sum())}|{wan(g.Actual.sum(min_count=1))}|{closed}|"
                            f"{'' if pd.isna(rate) else f'{rate:.1f}%'}|{status}")
    category_lines = ["年度|部門|各費用科目已發生金額（萬元）"]
    for (year, dept), g in expense_data.groupby(["Year", "Department"], sort=True):
        parts = g.groupby("Account").Amount.sum().sort_values(ascending=False)
        category_lines.append(f"{year}|{name(dept)}|" + "；".join(f"{show_account(a)} {wan(v)}" for a, v in parts.items()))
    events = monthly_data[monthly_data.EventNote.astype(str).str.strip().ne("")]
    event_lines = ["年度|部門|月份|事件|一次性金額（萬元，空白=經常性事件）"]
    for (year, dept, note), g in events.groupby(["Year", "Department", "EventNote"], sort=True):
        months = f"{int(g.Month.min())}-{int(g.Month.max())}" if g.Month.nunique() > 1 else f"{int(g.Month.min())}"
        one_off = g.OneOffAmount.sum()
        event_lines.append(f"{year}|{name(dept)}|{months}|{show_event(note)}|{wan(one_off) if one_off > 0 else ''}")
    return {
        "unit_note": "表格金額單位皆為新台幣「萬元」整數；引用時寫成「○○ 萬」，超過 10,000 萬換算為億（10,000 萬 = 1 億）。'-' 表示該月尚未結算。",
        "annual_by_department": "\n".join(annual_lines),
        "monthly_budget_and_actual": "\n".join(monthly_lines),
        "expense_categories_by_year": "\n".join(category_lines),
        "tagged_events_all_years": "\n".join(event_lines),
    }

def ai_data_tables():
    thresholds = tuple(st.session_state.get(k, d) for k, d in (("thr_watch_pct", 102), ("thr_high_pct", 105), ("thr_lag_pct", 90)))
    # 部門主管只把本部門資料交給 AI，避免透過對話問到其他部門的數字
    scope = df_db.Department.isin(selected_depts) if VIEW_ROLE == "head" else slice(None)
    expense_scope = expense_detail.Department.isin(selected_depts) if VIEW_ROLE == "head" else slice(None)
    return _ai_data_tables(df_db[scope], expense_detail[expense_scope], IS_EN, {r.Department: show_status(r.Status) for r in analysis_res.itertuples()},
                           selected_year, thresholds)

def build_ai_facts(question=None):
    """Budget facts for the LLM: pre-formatted headline analysis for the selected year plus the whole database as compact tables.

    Headline amounts are pre-formatted text so small models never convert units for the key figures.
    """
    q = (question or "").casefold()
    wants = lambda *terms: question is not None and any(t in q for t in terms)
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
            f"{show_dept(r.Department)} | {show_status(r.Status)} | "
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
        "selected_year_monthly_forecast_for_open_months_wan": " ".join(
            f"{mo}月:{monthly_estimate.loc[mo] / 1e4:.0f}" for mo in MONTHS if monthly_estimate.loc[mo] > 0),
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
    facts["full_database_tables"] = ai_data_tables()

    # 問到其他年度（「2025年」「去年」）時，另外附上該年度完整的部門分析與判斷依據。
    asked = {int(y) for y in re.findall(r"20\d{2}", q)}
    if wants("去年", "last year"):
        asked.add(selected_year - 1)
    if wants("前年"):
        asked.add(selected_year - 2)
    asked = sorted((asked & set(int(y) for y in df_db.Year.unique())) - {selected_year})
    if asked:
        facts["other_fiscal_years_requested"] = {}
        for year in asked[:2]:
            other = analyze_budget(df_db, year, selected_depts)
            other = other.assign(_s=other.Status.map(STATUS_SEVERITY)).sort_values(["_s", "Forecast_Var"], ascending=[True, False])
            closed = int(other.Actual_Cutoff_Month.max()) if len(other) else 0
            facts["other_fiscal_years_requested"][str(year)] = {
                "actuals_closed_through_month": closed,
                "company_total": {"annual_budget": fmc(other.Budget_Full.sum()), "actual_spent": fmc(other.Actual_YTD.sum()),
                                  "year_end_result_or_forecast": fmc(other.Forecast_EOY.sum()),
                                  "minus_budget": fmc(other.Forecast_EOY.sum() - other.Budget_Full.sum(), signed=True)},
                "departments": [
                    {"department": show_dept(r.Department), "status": show_status(r.Status),
                     "annual_budget": fmc(r.Budget_Full), "actual_spent": fmc(r.Actual_YTD),
                     "year_end_result_or_forecast": fmc(r.Forecast_EOY),
                     "minus_budget": f"{fmc(r.Forecast_Var, signed=True)} ({fpct(r.Forecast_Pct, signed=True)})",
                     "evidence": risk_evidence(df_db, year, r)}
                    for r in other.itertuples()
                ],
            }
    return facts

AI_RULES = (
    "You are a budget analysis assistant for an insurance company's finance team. "
    "Always answer in the requested language; for Chinese use Taiwan Traditional Chinese. "
    "Headline amounts are already formatted in Taiwanese units (e.g. '30.71 億', '+7,051 萬'): copy them exactly. Table amounts are integers in 萬 (NT$ 10 thousand); quote them with the 萬 unit, converting to 億 above 10,000 萬 (10,000 萬 = 1 億). Lead with percentages when comparing. "
    "Distinguish carefully between amounts 'through month N' (actuals so far) and 'year_end_forecast' figures; never mix them. "
    "For rankings (largest overspend, most unused budget / reallocation sources) use the pre-sorted lists as given; a positive variance is overspend, never headroom. "
    "The headline facts (company_total, departments, alerts) describe the dashboard's selected fiscal year and selected departments. "
    "full_database_tables contains the WHOLE loaded database for every year and department: monthly budget and actual, annual summary with status, "
    "expense categories by year and tagged events. Use these tables to answer any question about other years, months, quarters, departments, "
    "categories, trends, growth rates, rankings or comparisons; you may add, subtract and compute percentages from table values, and show the figures you used. "
    "A year with 12 closed months is a final result, not a forecast. For other years you may mention that the 分析年度 slider switches the dashboard to that year. "
    "For general finance, budgeting, insurance or regulation concepts (e.g. IFRS 17, TW-ICS, run rate, variance analysis) you may answer from your own knowledge, "
    "but every number about this company must come from the supplied facts; if the data truly does not contain something, say so and suggest what data would be needed. "
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
        tx(f"- **{show_dept(r.Department)}｜{show_status(r.Status)}**：年底預測差異 {fmc(r.Forecast_Var, signed=True)}（{fpct(r.Forecast_Pct, signed=True)}）。"
           f"{risk_evidence(df_db, selected_year, r)[0]}",
           f"- **{show_dept(r.Department)} | {show_status(r.Status)}**: year-end forecast variance {fmc(r.Forecast_Var, signed=True)} ({fpct(r.Forecast_Pct, signed=True)}). "
           f"{risk_evidence(df_db, selected_year, r)[0]}.")
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

PDF_ACTIONS = {
    "高風險超支": ("檢視剩餘月份的採購、合約與支出計畫，必要時暫緩非必要支出。", "Review remaining-month purchases and contracts; defer discretionary spend if needed."),
    "需注意": ("每月追蹤主要費用科目，確認超支是否為一次性或持續性。", "Track major categories monthly and confirm whether the overrun is one-off or recurring."),
    "執行落後": ("確認專案時程與剩餘預算需求；若確定有餘額，可列為調撥來源。", "Confirm project timing and remaining needs; confirmed headroom can fund reallocation."),
}

def pdf_meta():
    return [f"FY{selected_year}", tx(f"資料截至 {data_cutoff_month} 月", f"Data through M{data_cutoff_month}"),
            tx(f"{len(selected_depts)} 個部門", f"{len(selected_depts)} departments"), data_source,
            tx("產出 ", "Generated ") + datetime.now().strftime("%Y-%m-%d %H:%M")]

def pdf_kpi_items():
    use = tf_sum / tb_sum * 100 if tb_sum else 0.0
    gap = tf_sum - tb_sum
    status = classify_status(tf_sum / tb_sum) if tb_sum else "預算正常"
    return [
        (tx("年度總預算", "Annual budget"), fmc(tb_sum), tx("全年核定預算", "Approved annual budget"), PDF_BRAND),
        (tx("已執行進度", "Spent so far"), fpct(ta_sum / tb_sum * 100 if tb_sum else 0), fmc(ta_sum), PDF_BRAND),
        (tx("年底預算使用率", "Year-end budget use"), fpct(use), show_status(status), PDF_STATUS[status]),
        (tx("預估年底超支", "Projected overspend") if gap > 0 else tx("預估年底結餘", "Projected headroom"),
         fpct(abs(gap) / tb_sum * 100 if tb_sum else 0), fmc(abs(gap)), PDF_STATUS["高風險超支" if gap > 0 else "預算正常"]),
    ]

def budget_report_doc():
    """預算摘要報告：主管可直接轉寄或列印的正式版面。"""
    ordered_rows = analysis_res.assign(_s=analysis_res.Status.map(STATUS_SEVERITY)).sort_values(["_s", "Forecast_Var"], ascending=[True, False])
    bars = [(show_dept(r.Department), r.Forecast_EOY / r.Budget_Full * 100 if r.Budget_Full else 0, PDF_STATUS[r.Status],
             f"{fpct(r.Forecast_EOY / r.Budget_Full * 100 if r.Budget_Full else 0)}") for r in ordered_rows.itertuples()]
    rows, colors = [], []
    for r in ordered_rows.itertuples():
        rows.append([show_dept(r.Department), show_status(r.Status), fm_num(r.Budget_Full), fm_num(r.Actual_YTD),
                     fm_num(r.Forecast_EOY), fm_num(r.Forecast_Var, signed=True), fpct(r.Forecast_Pct, signed=True)])
        tone = PDF_STATUS[r.Status]
        colors.append([None, tone, None, None, None, tone, tone])
    alerts = [
        (tx(f"**{show_dept(r.Department)}｜{show_status(r.Status)}**：年底預測差異 {fmc(r.Forecast_Var, signed=True)}"
            f"（{fpct(r.Forecast_Pct, signed=True)}）。{risk_evidence(df_db, selected_year, r)[0]}。建議：{PDF_ACTIONS[r.Status][0]}",
            f"**{show_dept(r.Department)} | {show_status(r.Status)}**: year-end variance {fmc(r.Forecast_Var, signed=True)}"
            f" ({fpct(r.Forecast_Pct, signed=True)}). {risk_evidence(df_db, selected_year, r)[0]}. Action: {PDF_ACTIONS[r.Status][1]}"),
         PDF_STATUS[r.Status])
        for r in ordered_rows.itertuples() if r.Status != "預算正常"
    ]
    blocks = [
        ("kpis", pdf_kpi_items()),
        ("heading", tx("執行摘要", "Executive summary")), ("paragraph", executive_summary(analysis_res)),
        ("heading", tx("各部門年底預算使用率", "Year-end budget use by department")),
        ("bars", bars, tx("虛線＝年度預算 100%；顏色代表預警燈號。", "Dashed line = 100% of annual budget; colour = alert status.")),
        ("heading", tx("各部門預算與年底預測（單位：新台幣萬元）", "Budget and year-end forecast by department (NT$ millions)")),
        ("table", [tx("部門", "Department"), tx("燈號", "Status"), tx("年度預算", "Budget"), tx("已支出", "Spent"),
                   tx("年底預測", "Forecast"), tx("差異", "Variance"), tx("差異率", "Var %")],
         rows, [24, 22, 20, 20, 20, 20, 16], ["L", "L", "R", "R", "R", "R", "R"], colors),
        ("heading", tx("預警部門與建議行動", "Alerts and recommended actions")),
    ]
    blocks += [("bullet", text, rgb) for text, rgb in alerts] or [("paragraph", tx("目前沒有部門觸發預警。", "No department currently triggers an alert."))]
    return {"title": tx(f"{selected_year} 年度預算摘要報告", f"FY{selected_year} Budget Summary Report"),
            "subtitle": tx("預算執行、年底預測與預警重點", "Budget execution, year-end forecast and alerts"),
            "meta": pdf_meta(), "blocks": blocks}

def ai_brief_doc(markdown_text, source):
    return {"title": tx(f"{selected_year} AI 預算分析簡報", f"FY{selected_year} AI Budget Brief"),
            "subtitle": tx("主管摘要、預警訊息與建議行動", "Executive summary, alerts and recommended actions"),
            "meta": pdf_meta(),
            "blocks": [("kpis", pdf_kpi_items()), ("markdown_block", markdown_text),
                       ("paragraph", tx(f"產生來源：{source}。預警訊息與金額由系統計算，非模型生成。", f"Generated by: {source}. Alert figures are computed by the system, not the model."),
                        8.5, PDF_MUTED)]}

def pdf_download(label, doc, file_name, key):
    """PDF is built only when clicked (callable data), so page switches stay fast."""
    st.download_button(label, data=lambda: render_pdf(doc), file_name=file_name, mime="application/pdf",
                       key=key, icon=":material/picture_as_pdf:", width="stretch")

def ai_brief_panel(key):
    """Button + output for an AI-written executive summary and alert messages (requirement: 產生預算分析摘要與預警訊息)."""
    signature = (selected_year, tuple(selected_depts), IS_EN, ai_provider_label(), round(tf_sum))
    cached = st.session_state.get("ai_brief")
    with card(f"brief-{key}"):
        head, action = st.columns([3, 1.3], vertical_alignment="center")
        head.markdown(f'<div class="chart-title">{icon("sparkles", 16, ACCENT)} {tx("AI 預算分析摘要與預警訊息", "AI budget brief & alert messages")}</div>', unsafe_allow_html=True,
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
                    if notes and not ai_locked:  # 略過原因屬維運資訊，公開模式不顯示給訪客
                        source += tx("（已自動略過：", " (skipped: ") + "；".join(notes) + tx("）", ")")
                except Exception as err:
                    text, source = rule_based_brief(), tx("內建規則（模型額度已用完或無法連線）", "Built-in rules (model quota used up or unreachable)")
                    if not ai_locked:
                        st.caption(f":material/info: {err}")
            else:
                text, source = rule_based_brief(), tx("內建規則", "Built-in rules")
            cached = {"sig": signature, "text": text.strip(), "source": source}
            st.session_state["ai_brief"] = cached
        if cached and cached["sig"] == signature:
            st.markdown(md_safe(cached["text"]))
            foot, dl = st.columns([3, 1.3], vertical_alignment="center")
            foot.caption(tx(f"產生來源：{cached['source']}", f"Generated by: {cached['source']}"))
            with dl:
                pdf_download(tx("下載 PDF", "Download PDF"), ai_brief_doc(cached["text"], cached["source"]),
                             f"AI_budget_brief_FY{selected_year}.pdf", f"brief_dl_{key}")
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
            "Cost_Center": tx("成本中心", "Cost center"),
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

# 導覽放在共用計算之後建立（容器已預先排好位置），「預測與預警」才能帶出目前預警部門數。
alert_count = int((analysis_res.Status != "預算正常").sum())
main_nav_ids = ["overview", "budget_analysis", "forecast_risk", "scenarios_quality", "ai_assistant"]
main_nav_labels = {
    "overview": tx(":material/space_dashboard: 總覽", ":material/space_dashboard: Overview"),
    "budget_analysis": tx(":material/bar_chart: 預算分析", ":material/bar_chart: Budget analysis"),
    "forecast_risk": tx(":material/notifications_active: 預測與預警", ":material/notifications_active: Forecast & risk")
                     + (f" :red-badge[{alert_count}]" if alert_count else ""),
    "scenarios_quality": tx(":material/tune: 情境與資料品質", ":material/tune: Scenarios & data"),
    "ai_assistant": tx(":material/auto_awesome: AI 助理", ":material/auto_awesome: AI assistant"),
}
with sb_nav:
    st.markdown(f'<div class="sb-label">{tx("工作區", "Workspace")}</div>', unsafe_allow_html=True)
    # 目前頁面記在網址 ?page=…（不用 bind，因為 bind 會把含圖示與預警數字的顯示文字寫進網址），切換主題重新載入後仍停在同一頁。
    if "main_navigation_id" not in st.session_state and st.query_params.get("page") in main_nav_ids:
        st.session_state["main_navigation_id"] = st.query_params["page"]
    with st.container(key="nav_slot"):
        active_nav_id = st.radio(
            tx("主要功能", "Navigation"), main_nav_ids, format_func=lambda nav_id: main_nav_labels[nav_id],
            key="main_navigation_id", label_visibility="collapsed",
        )
    st.query_params["page"] = active_nav_id
    # 分組標題：總覽 ｜ 分析 ｜ 智慧工具
    st.markdown(f"""<style>
.st-key-nav_slot [role="radiogroup"] > div:nth-child(2), .st-key-nav_slot [role="radiogroup"] > div:nth-child(5) {{ margin-top:24px; position:relative; }}
.st-key-nav_slot [role="radiogroup"] > div:nth-child(2)::before, .st-key-nav_slot [role="radiogroup"] > div:nth-child(5)::before {{
    position:absolute; left:4px; top:-19px; font-size:10.5px; font-weight:700; letter-spacing:.12em; color:{MUTED}; opacity:.85; }}
.st-key-nav_slot [role="radiogroup"] > div:nth-child(2)::before {{ content:"{tx('分析', 'ANALYSIS')}"; }}
.st-key-nav_slot [role="radiogroup"] > div:nth-child(5)::before {{ content:"{tx('智慧工具', 'AI TOOLS')}"; }}
</style>""", unsafe_allow_html=True)
    sb_status.markdown(
        f'<div class="sb-label">{tx("資料狀態", "Data status")}</div><div class="sb-status">'
        f'<div class="sb-status-row"><span>FY{selected_year} {tx("結算進度", "close progress")}</span><b>{data_cutoff_month} / 12</b></div>'
        f'<div class="sb-progress"><i style="width:{data_cutoff_month / 12 * 100:.0f}%"></i></div>'
        f'<div class="sb-src" style="--c:{source_color}">{data_source}</div></div>',
        unsafe_allow_html=True,
    )
hero_chips = "".join([
    ui_chip(tx(f"FY{selected_year}", f"FY{selected_year}"), ACCENT),
    ui_chip(tx(f"資料截至 {data_cutoff_month} 月", f"Data through month {data_cutoff_month}") if data_cutoff_month else tx("尚無實際數", "No actuals yet")),
    ui_chip(tx(f"{len(selected_depts)} 個部門", f"{len(selected_depts)} departments")),
    ui_chip(data_source + (tx(" · 量級 ", " · scale ") + fmc(opex_anchor_100m * 1e8) if is_synthetic and VIEW_ROLE != "head" else ""), source_color),
    ui_chip(tx("身分：", "Role: ") + (f"{show_dept(VIEW_DEPT)}{tx('主管', ' head')}" if VIEW_ROLE == "head" else ROLE_LABELS[VIEW_ROLE].split("（")[0].split(" (")[0]), ACCENT2),
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
# 總覽：結論 → KPI → 主圖＋狀態環圖 → 燈號 → 熱力圖 → 詳細（折疊）
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
        f'<div class="lead" style="--c:{lead_color}"><div class="lead-tag">{icon("sparkles", 13)} {tx("智慧摘要", "Executive summary")}</div>'
        f'<div class="lead-text">{executive_summary(analysis_res)}</div><div class="chips">{chips}</div></div>',
        unsafe_allow_html=True,
    )

    # ---- 2. 四張 KPI 卡：變化膠囊 + 底部滿版迷你圖（每張不同圖形；異常時帶微光） ----
    cum_budget = monthly_budget.cumsum()
    cum_actual = monthly_actual.where(monthly_actual.index <= data_cutoff_month).cumsum()
    cum_path = (monthly_actual.fillna(0) + monthly_estimate).cumsum()
    pace_gap = actual_pct - budget_pace_pct
    actual_color = STATUS_COLORS["需注意"] if pace_gap > 2 else ACCENT
    forecast_color = STATUS_COLORS[forecast_status]
    over_color, ok_color = STATUS_COLORS["高風險超支"], STATUS_COLORS["預算正常"]
    low_total, high_total = float(analysis_res.Forecast_Low.sum()), float(analysis_res.Forecast_High.sum())
    closed = monthly_budget.index <= data_cutoff_month
    # 每月差異：已結算月份用實際數，未結算月份用預測分配數（淡色）
    monthly_gap = (monthly_actual.where(closed, monthly_estimate) - monthly_budget).fillna(0.0)
    prior_budget = float(df_db[(df_db.Year == selected_year - 1) & df_db.Department.isin(selected_depts)].Budget.sum())
    over_count = int((analysis_res.Forecast_Var > 0).sum())

    if prior_budget:
        budget_yoy = (tb_sum / prior_budget - 1) * 100
        budget_delta = ui_delta(fpct(budget_yoy, signed=True), ACCENT, "up" if budget_yoy >= 0 else "down")
        budget_sub = tx(f"vs FY{selected_year - 1} 預算", f"vs FY{selected_year - 1} budget")
    else:
        budget_delta, budget_sub = "", tx("目前選取部門合計", "Selected departments")
    # 大字一律是百分比（好判斷嚴重程度），金額放在下方當輔助
    utilization = tf_sum / tb_sum * 100 if tb_sum else 0.0
    kpis = [
        ui_kpi(tx("年度總預算", "Annual budget"), fmc(tb_sum), budget_sub, "wallet", ACCENT, delta=budget_delta,
               viz=ui_bars(monthly_budget.tolist(), [rgba(ACCENT, .85 if c else .32) for c in closed]),
               help=tx("所有比例的分母。下方長條是每月預算，深色＝已結算月份。", "The denominator for every ratio. Bars are monthly budgets; solid = closed months.")),
        ui_kpi(tx("已執行進度", "Spent so far"), fpct(actual_pct),
               tx(f"已花 {fmc(ta_sum)}｜應有 {fpct(budget_pace_pct)}", f"{fmc(ta_sum)} spent · plan {fpct(budget_pace_pct)}"),
               "activity", actual_color, glow=pace_gap > 2,
               delta=ui_delta(tx(f"{pace_gap:+.1f} 個百分點", f"{pace_gap:+.1f} pp"), actual_color if pace_gap > 2 else ok_color,
                              "up" if pace_gap >= 0 else "down"),
               viz=ui_area(cum_actual.tolist(), actual_color, ref=cum_budget.tolist()),
               help=tx("已花掉全年預算的比例；「應有」是依每月預算到目前為止應花的比例。超前代表花得比計畫快。",
                       "Share of the annual budget spent; 'plan' is what the monthly budget implies by now. Ahead of plan means spending faster.")),
        ui_kpi(tx("年底預算使用率", "Year-end budget use"), fpct(utilization),
               tx(f"預測 {fmc(tf_sum)}／預算 {fmc(tb_sum)}", f"{fmc(tf_sum)} forecast / {fmc(tb_sum)} budget"),
               "target", forecast_color, glow=forecast_status != "預算正常",
               delta=ui_delta(show_status(forecast_status), forecast_color),
               viz=ui_range(low_total / tb_sum * 100 if tb_sum else 0, utilization, high_total / tb_sum * 100 if tb_sum else 0, forecast_color),
               help=tx("照目前速度，年底會用掉全年預算的幾 %。超過 100% 就是超支；色帶是歷史回測的 P80 合理區間。",
                       "Share of the annual budget expected to be used by year end. Above 100% means overspend; the band is the backtest P80 range.")),
    ]
    gap_viz = ui_bars(monthly_gap.tolist(), [rgba(over_color if v > 0 else ok_color, .85 if c else .35)
                                             for v, c in zip(monthly_gap, closed)])
    over_delta = ui_delta(tx(f"{over_count} 個部門超支", f"{over_count} dept{'s' if over_count != 1 else ''} over"),
                          over_color if over_count else ok_color)
    gap_help = tx("年底預測和年度預算的差距占預算的比例。下方長條是每月超支（紅）或結餘（綠），淡色為預測月份。",
                  "Year-end gap as a share of the budget. Bars show monthly overspend (red) or headroom (green); faded = forecast months.")
    if total_variance > 0:
        kpis.append(ui_kpi(tx("預估年底超支", "Projected overspend"), fpct(variance_pct, signed=True),
                           tx(f"約 {fmc(total_variance)}", f"about {fmc(total_variance)}"),
                           "alert", over_color, glow=True, delta=over_delta, viz=gap_viz, help=gap_help))
    else:
        kpis.append(ui_kpi(tx("預估年底結餘", "Projected headroom"), fpct(abs(variance_pct)),
                           tx(f"約 {fmc(abs(total_variance))}", f"about {fmc(abs(total_variance))}"),
                           "shield", ok_color, delta=over_delta, viz=gap_viz, help=gap_help))
    stat_row(kpis)
    ai_brief_panel("overview")

    # ---- 3. 主視覺：累計支出路徑（漸層面積＋預測扇形區間）＋ 預算狀態環圖 ----
    hero_col, donut_col = st.container(key="wrap-hero").columns([2.15, 1], gap="medium")
    with hero_col:
        path_fig = go.Figure()
        if data_cutoff_month < 12:
            # 預測扇形：從結算月往年底逐步展開到 P80 區間
            start = max(data_cutoff_month, 1)
            fan_x = MONTHS[start - 1:]
            frac = np.linspace(0, 1, len(fan_x)) if len(fan_x) > 1 else np.array([1.0])
            fan_mid = cum_path.iloc[start - 1:].to_numpy()
            path_fig.add_scatter(x=fan_x, y=fan_mid + frac * (high_total - tf_sum), mode="lines", line=dict(width=0),
                                 showlegend=False, hoverinfo="skip", hovertemplate="skip")
            path_fig.add_scatter(x=fan_x, y=fan_mid - frac * (tf_sum - low_total), mode="lines", line=dict(width=0),
                                 fill="tonexty", fillcolor=rgba(forecast_color, .16), name=tx("P80 預測區間", "P80 range"),
                                 hoverinfo="skip", hovertemplate="skip")
        path_fig.add_scatter(x=MONTHS, y=cum_budget, name=tx("累計預算", "Cumulative budget"), mode="lines",
                             line=dict(color=MUTED, width=2, dash="dot"))
        if data_cutoff_month:
            path_fig.add_scatter(x=MONTHS[:data_cutoff_month], y=cum_actual.iloc[:data_cutoff_month],
                                 name=tx("累計實際", "Cumulative actual"), mode="lines",
                                 line=dict(color=ACCENT, width=3.2, shape="spline", smoothing=.5),
                                 fill="tozeroy", fillgradient=dict(type="vertical", start=0, stop=float(cum_actual.max()),
                                                                   colorscale=[[0, rgba(ACCENT, 0)], [1, rgba(ACCENT, .42)]]))
            path_fig.add_scatter(x=[data_cutoff_month], y=[float(cum_actual.iloc[data_cutoff_month - 1])], mode="markers",
                                 showlegend=False, hoverinfo="skip", hovertemplate="skip",
                                 marker=dict(size=11, color=ACCENT, line=dict(color=rgba(ACCENT, .35), width=7)))
        if data_cutoff_month < 12:
            path_fig.add_scatter(x=fan_x, y=fan_mid, name=tx("預測路徑", "Forecast path"), mode="lines",
                                 line=dict(color=forecast_color, width=2.6, dash="dash", shape="spline", smoothing=.5))
        if data_cutoff_month:
            path_fig.add_vline(x=data_cutoff_month + .5, line=dict(color=BORDER, width=1, dash="dot"))
            path_fig.add_annotation(x=data_cutoff_month + .5, y=.02, yref="paper", text=tx("實際 ◀ ｜ ▶ 預測", "Actual ◀ | ▶ Forecast"), showarrow=False,
                                    xanchor="center", yanchor="bottom", font=dict(size=11, color=MUTED), bgcolor=PANEL)
        gap_text = (tx("預估超支", "Projected overspend") if total_variance > 0 else tx("預估結餘", "Projected headroom")) + f" {fmc(abs(total_variance))}"
        path_fig.add_annotation(
            x=12, y=max(tf_sum, tb_sum), text=f"<b>{tx('年底預估', 'Year-end')} {fmc(tf_sum)}</b><br>{tx('年度預算', 'Budget')} {fmc(tb_sum)}<br><b>{gap_text}</b>",
            showarrow=True, arrowhead=0, arrowcolor=forecast_color, ax=-90, ay=-34, xanchor="right", align="right",
            bgcolor=rgba(forecast_color, .12), bordercolor=rgba(forecast_color, .5), borderpad=6,
            font=dict(color=TEXT, size=12),
        )
        style_fig(path_fig, height=400)
        path_fig.update_layout(legend_traceorder="normal")  # tonexty 會讓 Plotly 自動反轉圖例順序
        path_fig.update_xaxes(tickmode="array", tickvals=MONTHS, ticktext=[tx(f"{m}月", f"M{m}") for m in MONTHS], showgrid=False)
        money_axis(path_fig, max_hint=max(high_total, tb_sum))
        show_chart(path_fig, title=tx("全公司照目前速度花，年底會落在哪裡？", "At the current pace, where will total spending land?"), key="overview_path", hint=tx("看虛線終點有沒有超過灰色點線（年度預算）：超過就是年底會超支；淡色色帶是合理誤差範圍。", "Check whether the dashed line ends above the dotted budget line: if so, the year ends over budget. The band is the likely error range."), help_text=tx(
            "藍色漸層＝已結算月份的累計實際支出；彩色虛線＝依季節性與 Run-rate 推估的剩餘月份；灰色點線＝累計預算。虛線終點高於灰線即代表年底超支；扇形色帶為歷史回測 P80 區間。",
            "Gradient = cumulative closed actuals; dashed = remaining months estimated from seasonality and run rate; dotted = cumulative budget. The fan shows the backtest P80 range."))
    with donut_col:
        # 依燈號加總年度預算：一眼看出多少預算落在風險部門
        budget_by_status = analysis_res.groupby("Status").Budget_Full.sum().reindex(STATUS_ORDER).fillna(0.0)
        budget_by_status = budget_by_status[budget_by_status > 0]
        at_risk_share = float(budget_by_status.reindex(["高風險超支", "需注意"]).fillna(0).sum() / tb_sum * 100) if tb_sum else 0.0
        # 純 CSS 圓環（conic-gradient）：比 Plotly 圓餅圖少一次圖表繪製，切到總覽更快
        stops, start = [], 0.0
        for s, v in budget_by_status.items():
            end = start + (v / tb_sum * 100 if tb_sum else 0)
            stops.append(f"{STATUS_COLORS[s]} {start:.2f}% {end - .4:.2f}%, transparent {end - .4:.2f}% {end:.2f}%")
            start = end
        dept_count = analysis_res.Status.value_counts()
        rows = "".join(
            f'<div class="dl-row"><span class="dot" style="background:{STATUS_COLORS[s]}"></span>'
            f'<span class="dl-name">{show_status(s)}</span><span class="dl-n">{tx(f"{int(dept_count.get(s, 0))} 個部門", f"{int(dept_count.get(s, 0))} dept")}</span>'
            f'<span class="dl-amt">{fmc(v)}</span><b>{v / tb_sum * 100 if tb_sum else 0:.0f}%</b></div>'
            for s, v in budget_by_status.items())
        with card("overview_donut"):
            st.markdown(f'<div class="chart-title">{tx("各狀態部門的預算占比", "Budget share by department status")}</div>', unsafe_allow_html=True, help=tx(
                "把全公司年度預算依「部門目前的燈號」分組加總。中央數字＝落在「高風險超支」與「需注意」部門的預算占比，代表有多少預算需要主管關注。",
                "Annual budget grouped by each department's current status. The centre figure is the share held by High-risk and Monitor departments — how much budget needs management attention."))
            st.markdown(
                f'<div class="donut" style="background:conic-gradient({", ".join(stops)})"><div class="donut-hole">'
                f'<b>{at_risk_share:.0f}%</b><span>{tx("預算在需關注部門", "of budget needs attention")}</span></div></div>'
                f'<div class="dlist">{rows}</div>', unsafe_allow_html=True)

    # ---- 4. 部門燈號清單 + 優先處理 ----
    ordered = analysis_res.assign(_sev=analysis_res.Status.map(STATUS_SEVERITY).fillna(3)).sort_values(
        ["_sev", "Forecast_Var"], ascending=[True, False])
    list_col, focus_col = st.container(key="wrap-list").columns([1.65, 1], gap="medium")
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
            st.markdown(f'<div class="okcard">{icon("check", 17)} {tx("目前沒有需要優先處理的部門。", "No departments currently need priority review.")}</div>', unsafe_allow_html=True)
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
                f'<ul class="ev">{evidence}</ul><div class="next">{icon("arrow", 14)} {next_step}</div></div>',
                unsafe_allow_html=True,
            )

    # ---- 5. 部門 × 月份熱力圖：年底集中支出、一次性支出一眼可見 ----
    heat_years = [y for y in (selected_year, selected_year - 1) if y in available_years]
    with card("overview_heat"):
        title_col, year_col = st.columns([3, 1.2], vertical_alignment="center")
        with title_col:
            st.markdown(f'<div class="chart-title">{tx("哪個部門、哪個月花得比預算多？", "Which department overspent in which month?")}</div>',
                        unsafe_allow_html=True, help=tx(
                "每格＝該月實際支出相對當月預算的差異（%）；紅色＝超支、綠色＝低於預算。切到前一年度可看到完整 12 個月，年底（11–12 月）整排轉紅代表支出集中在年底（可能是年度活動、合約續約或延後請款），值得了解原因並提早規劃。",
                "Each cell = that month's actual vs. its budget (%); red = over, green = under. Switch to the prior year to see all 12 months — a red Nov–Dec column means spending is concentrated at year end (annual events, renewals or delayed invoicing) — worth understanding and planning earlier."))
        with year_col:
            heat_year = st.segmented_control(
                tx("年度", "Year"), heat_years, default=heat_years[0], required=True, key="overview_heat_year",
                format_func=lambda y: f"FY{y}", label_visibility="collapsed", width="stretch",
            ) or heat_years[0]
        heat_frame = df_db[(df_db.Year == heat_year) & df_db.Department.isin(selected_depts)]
        heat_ratio = heat_frame.assign(Pct=(heat_frame.Actual / heat_frame.Budget.replace(0, np.nan) - 1) * 100).pivot_table(
            index="Department", columns="Month", values="Pct", aggfunc="first", dropna=False).reindex(index=ordered.Department[::-1], columns=MONTHS)
        heat_notes = heat_frame.assign(Note=heat_frame.EventNote.fillna("").astype(str).map(lambda n: show_event(n) if n.strip() else "")).pivot_table(
            index="Department", columns="Month", values="Note", aggfunc="first").reindex(index=heat_ratio.index, columns=MONTHS).fillna("")
        heat_fig = go.Figure(go.Heatmap(
            z=heat_ratio.to_numpy(), x=MONTHS, y=[show_dept(d) for d in heat_ratio.index],
            zmid=0, zmin=-30, zmax=30, xgap=3, ygap=3, showscale=False,
            colorscale=[[0, ok_color], [.5, TRACK], [1, over_color]],
            text=heat_ratio.map(lambda v: "" if pd.isna(v) else f"{v:+.0f}%").to_numpy(),
            texttemplate="%{text}", textfont=dict(size=11, color=TEXT), customdata=heat_notes.to_numpy(),
            hovertemplate="<b>%{y}</b> · " + tx("%{x} 月", "M%{x}") + "<br>" + tx("相較當月預算", "vs. monthly budget") + " %{text}<br>%{customdata}<extra></extra>",
        ))
        style_fig(heat_fig, height=46 * len(heat_ratio) + 70, legend=False)
        heat_fig.update_xaxes(tickmode="array", tickvals=MONTHS, ticktext=[tx(f"{m}月", f"M{m}") for m in MONTHS],
                              showgrid=False, side="top")
        heat_fig.update_yaxes(showgrid=False)
        heat_fig.update_layout(margin=dict(l=8, r=8, t=8, b=8))
        open_months = 12 - int(heat_frame[heat_frame.Actual.notna()].Month.max()) if heat_frame.Actual.notna().any() else 12
        if open_months:
            heat_fig.add_vrect(x0=12.5 - open_months, x1=12.5, fillcolor=rgba(MUTED, .08), line_width=0,
                               annotation_text=tx("尚未結算", "Not closed"), annotation_position="inside top",
                               annotation_font=dict(size=11, color=MUTED))
        st.plotly_chart(heat_fig, width="stretch", config=PLOT_CONFIG, theme=None, key="chart-overview_heat")

    # ---- 6. 漸進式揭露：詳細拆解預設折疊 ----
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
            tx("年度預算（萬元）", "Budget (M)"): to_m(ordered.Budget_Full).to_numpy(),
            tx("已執行（萬元）", "Actual (M)"): to_m(ordered.Actual_YTD).to_numpy(),
            tx("年底預測（萬元）", "Forecast (M)"): to_m(ordered.Forecast_EOY).to_numpy(),
            tx("預測差異（萬元）", "Variance (M)"): to_m(ordered.Forecast_Var).to_numpy(),
            trend_col: trend_lists,
        })
        st.dataframe(
            detail_table, hide_index=True, width="stretch",
            column_config={
                dept_col: st.column_config.TextColumn(dept_col, pinned=True),
                util_col: st.column_config.ProgressColumn(
                    util_col, format="%.1f%%", min_value=0, max_value=125, color=ACCENT,
                    help=tx("預測全年支出佔年度預算的比例；100% 代表剛好用完預算。", "Forecast spending as a share of the annual budget; 100% means fully used.")),
                tx("年度預算（萬元）", "Budget (M)"): st.column_config.NumberColumn(format=MONEY_FMT),
                tx("已執行（萬元）", "Actual (M)"): st.column_config.NumberColumn(format=MONEY_FMT),
                tx("年底預測（萬元）", "Forecast (M)"): st.column_config.NumberColumn(format=MONEY_FMT),
                tx("預測差異（萬元）", "Variance (M)"): st.column_config.NumberColumn(format=MONEY_FMT),
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
    analysis_views = st.tabs([tx("差異分析", "Variance"), tx("使用率", "Utilization"), tx("歷史趨勢", "History")], key="tabs_analysis", on_change="rerun")

    if analysis_views[0].open:
        with analysis_views[0]:
            net_variance = float(analysis_res.Variance.sum())
            over_budget_rows = analysis_res[analysis_res.Variance > 0]
            largest_variance_row = analysis_res.loc[analysis_res.Variance.abs().idxmax()]
            over_c, ok_c = STATUS_COLORS["高風險超支"], STATUS_COLORS["預算正常"]
            net_pct = net_variance / analysis_res.Budget_YTD.sum() * 100 if analysis_res.Budget_YTD.sum() else 0.0
            big = largest_variance_row
            stat_row([
                ui_kpi(tx("整體同期差異", "Net variance to date"), fpct(net_pct, signed=True),
                       tx(f"約 {fmc(net_variance, signed=True)}｜截至 {data_cutoff_month} 月", f"about {fmc(net_variance, signed=True)} · through M{data_cutoff_month}"),
                       "activity", over_c if net_variance > 0 else ok_c,
                       delta=ui_delta(tx("高於同期預算", "Above plan") if net_variance > 0 else tx("低於同期預算", "Below plan"), over_c if net_variance > 0 else ok_c),
                       help=tx("到目前為止實際支出比「同期應花的預算」多或少幾 %。", "How far actual spending to date is above or below the budget for the same months.")),
                ui_kpi(tx("高於同期預算的部門", "Departments above plan"), f"{len(over_budget_rows)} / {len(analysis_res)}",
                       tx(f"合計多花 {fmc(float(over_budget_rows.Variance.sum()))}", f"{fmc(float(over_budget_rows.Variance.sum()))} over in total"),
                       "building", over_c if len(over_budget_rows) else ok_c,
                       delta=ui_delta(tx(f"{len(over_budget_rows)} 個部門超前", f"{len(over_budget_rows)} ahead of plan"), over_c if len(over_budget_rows) else ok_c)),
                ui_kpi(tx("差異最大的部門", "Largest variance"), show_dept(big.Department),
                       tx(f"約 {fmc(float(big.Variance), signed=True)}", f"about {fmc(float(big.Variance), signed=True)}"),
                       "alert", over_c if big.Variance > 0 else ok_c,
                       delta=ui_delta(fpct(float(big.Variance_Pct), signed=True), over_c if big.Variance > 0 else ok_c, "up" if big.Variance > 0 else "down")),
            ])

            # 圖表需要足夠寬度放標籤，改為上下排列。
            chart_col = table_col = st.container()
            with chart_col:
                var_fig = variance_bar_fig(
                    analysis_res.Department.map(show_dept), analysis_res.Variance, analysis_res.Variance_Pct,
                    [STATUS_COLORS["高風險超支"] if v > 0 else STATUS_COLORS["執行落後"] for v in analysis_res.Variance],
                    hover_extra=[f"<br>{tx('實際', 'Actual')} {fmc(a)} / {tx('同期預算', 'Budget to date')} {fmc(b)}" for a, b in zip(analysis_res.Actual_YTD, analysis_res.Budget_YTD)],
                )
                show_chart(var_fig, title=tx(f"截至 {data_cutoff_month} 月，誰花得比預算多？", f"Through month {data_cutoff_month}, who spent more than planned?"), key="variance_bar", hint=tx("往右（紅）＝到目前為止花得比預算多，往左＝花得比較少；先看最右邊的部門。", "Right (red) = spent more than planned so far, left = less. Start with the departments furthest right."),
                           help_text=tx("中線＝剛好等於同期預算。紅色往右＝已超出同期預算；藍色往左＝低於同期預算（花得較慢）。", "Centre line = exactly on budget to date. Red to the right = over; blue to the left = under (spending slower)."))
            with table_col:
                monthly_var = df_filtered_year[df_filtered_year.Actual.notna()].assign(
                    Var_Pct=lambda d: (d.Actual - d.Budget) / d.Budget * 100)
                trend = monthly_var.sort_values("Month").groupby("Department").Var_Pct.apply(lambda s: s.round(1).tolist())
                var_table = pd.DataFrame({
                    dept_col: analysis_res.Department.map(show_dept),
                    tx("同期預算（萬元）", "Budget to date (M)"): to_m(analysis_res.Budget_YTD),
                    tx("實際支出（萬元）", "Actual (M)"): to_m(analysis_res.Actual_YTD),
                    tx("差異（萬元）", "Variance (M)"): to_m(analysis_res.Variance),
                    tx("差異率", "Variance %"): analysis_res.Variance_Pct.round(1),
                    tx("每月差異率", "Monthly variance %"): analysis_res.Department.map(trend).apply(lambda v: v if isinstance(v, list) else []),
                })
                with card("variance_table"):
                    st.markdown(f'<div class="chart-title">{tx("差異明細", "Variance detail")}</div>', unsafe_allow_html=True)
                    st.dataframe(var_table, hide_index=True, width="stretch", height=330, column_config={
                        dept_col: st.column_config.TextColumn(pinned=True, width="small"),
                        tx("同期預算（萬元）", "Budget to date (M)"): st.column_config.NumberColumn(format=MONEY_FMT, width="small"),
                        tx("實際支出（萬元）", "Actual (M)"): st.column_config.NumberColumn(format=MONEY_FMT, width="small"),
                        tx("差異（萬元）", "Variance (M)"): st.column_config.NumberColumn(format=MONEY_FMT, width="small"),
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
                show_chart(heat_fig, title=tx("哪幾個月、哪些部門偏離當月預算？", "Which months and departments drifted from the monthly budget?"), key="variance_heat", hint=tx("紅色格子＝那個月花超過當月預算；整排都紅的部門或月份最值得追問原因。", "Red cells = that month exceeded its budget. A whole red row or column is the first thing to ask about."),
                           help_text=tx("僅顯示已結算月份。紅色＝超出當月預算；藍色＝低於當月預算。年末集中請款的部門會在前三季呈現偏藍。",
                                        "Closed months only. Red = above that month's budget; blue = below. Departments that flush budget at year end look blue through Q1–Q3."))
            else:
                st.info(tx("所選年度尚無已結算的實際支出月份。", "No actual spending months have been closed for the selected year."))

    if analysis_views[1].open:
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
                customdata=[[fmc(a), fmc(b)] for a, b in zip(util_ordered.Actual_YTD, util_ordered.Budget_YTD)],
                hovertemplate="<b>%{y}</b><br>" + tx("同期執行率", "Spend vs. plan") + " %{x:.1f}%<br>"
                              + tx("實際", "Actual") + " %{customdata[0]} / " + tx("同期預算", "Budget to date") + " %{customdata[1]}<extra></extra>",
            )
            util_fig.add_vrect(x0=90, x1=100, fillcolor=rgba(STATUS_COLORS["預算正常"], .08), line_width=0, layer="below")
            util_fig.add_vline(x=100, line=dict(color=TEXT, width=1.6),
                               annotation_text=tx("100%＝照預算進度", "100% = on plan"), annotation_position="top",
                               annotation_font=dict(color=MUTED, size=11))
            style_fig(util_fig, height=max(320, 44 * len(util_ordered) + 90), legend=False)
            util_fig.update_xaxes(range=[0, max(130, float(util_ordered.Exec_Rate.max()) + 15)], ticksuffix="%", title_text=None)
            util_fig.update_yaxes(showgrid=False)
            show_chart(util_fig, title=tx(f"截至 {data_cutoff_month} 月，各部門花錢速度是否超前預算？", f"Through month {data_cutoff_month}, is each department spending ahead of plan?"), key="util_bullet", hint=tx("長條超過 100% 直線＝花錢速度比預算計畫快；綠色帶（90–100%）是正常範圍，太短（藍）代表執行落後。", "A bar past the 100% line means spending faster than planned; the green band (90–100%) is normal, short blue bars are behind plan."),
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

    if analysis_views[2].open:
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
                show_chart(co_fig, title=tx("歷年預算執行：每年花得比預算多還是少？", "Year by year: did we spend more or less than budget?"), key="history_company", hint=tx("看每年是超支還是有結餘，判斷今年的狀況是常態還是例外。", "See whether each year ended over or under budget, to judge whether this year is normal or an exception."),
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
                show_chart(hist_fig, title=tx("各部門歷年實際支出", "Annual actual spending by department"), key="history_line", hint=tx("看各部門支出是否逐年穩定成長；突然跳升的年份通常有一次性支出。", "Check whether each department grows steadily; sudden jumps usually come from one-off spending."),
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
    risk_views = st.tabs([tx("年底預測", "Forecast"), tx("預算預警", "Alerts"), tx("成本歸因", "Cost drivers")], key="tabs_risk", on_change="rerun")

    if risk_views[0].open:
        with risk_views[0]:
            forecast_remaining_total = float((analysis_res.Forecast_EOY - analysis_res.Actual_YTD).sum())
            forecast_variance_total = float(tf_sum - tb_sum)
            difference_pct = forecast_variance_total / tb_sum * 100 if tb_sum else 0
            remaining_label = tx(f"{data_cutoff_month + 1}–12 月", f"months {data_cutoff_month + 1}–12") if data_cutoff_month < 12 else tx("無剩餘月份", "none")
            gap_status = classify_status(tf_sum / tb_sum) if tb_sum else "預算正常"
            gap_color = STATUS_COLORS[gap_status]
            pct_of = lambda v: v / tb_sum * 100 if tb_sum else 0.0
            stat_row([
                ui_kpi(tx("已花", "Spent"), fpct(pct_of(ta_sum)), tx(f"{fmc(ta_sum)}｜截至 {data_cutoff_month} 月", f"{fmc(ta_sum)} · through M{data_cutoff_month}"),
                       "wallet", ACCENT, delta=ui_delta(tx("已發生", "Actual"), ACCENT)),
                ui_kpi(tx("預計再花", "Still to spend"), fpct(pct_of(forecast_remaining_total)), f"{fmc(forecast_remaining_total)}｜{remaining_label}",
                       "clock", ACCENT2, delta=ui_delta(tx("模型預估", "Estimate"), ACCENT2),
                       help=tx("依歷史季節性（55%）與目前花費速度（45%）推估剩餘月份還會花多少；一次性支出不會延伸到未來。",
                               "Remaining months estimated from historical seasonality (55%) and current pace (45%); one-off costs are not extrapolated.")),
                ui_kpi(tx("年底預算使用率", "Year-end budget use"), fpct(pct_of(tf_sum)),
                       tx(f"區間 {fpct(pct_of(analysis_res.Forecast_Low.sum()), decimals=0)}–{fpct(pct_of(analysis_res.Forecast_High.sum()), decimals=0)}", f"range {fpct(pct_of(analysis_res.Forecast_Low.sum()), decimals=0)}–{fpct(pct_of(analysis_res.Forecast_High.sum()), decimals=0)}"),
                       "target", gap_color, glow=gap_status != "預算正常", delta=ui_delta(show_status(gap_status), gap_color)),
                ui_kpi(tx("預估年底超支", "Projected overspend") if forecast_variance_total > 0 else tx("預估年底結餘", "Projected headroom"),
                       fpct(abs(difference_pct)), tx(f"約 {fmc(abs(forecast_variance_total))}", f"about {fmc(abs(forecast_variance_total))}"),
                       "alert" if forecast_variance_total > 0 else "shield", gap_color,
                       delta=ui_delta(tx("超出年度預算", "Over budget") if forecast_variance_total > 0 else tx("低於年度預算", "Under budget"), gap_color)),
            ])

            # 預算水位條：已花 ＋ 預計再花，超過年度預算虛線的部分標紅，像油表一樣一眼看出會不會爆
            scale = max(tf_sum, tb_sum) * 1.04 or 1.0
            w = lambda v: max(0.0, v) / scale * 100
            spent_w = w(min(ta_sum, tb_sum))                   # 預算內已花
            spent_over_w = w(ta_sum - tb_sum)                  # 已花就超出預算的部分（已結算年度可能發生）
            rest_w = w(min(tf_sum, tb_sum) - ta_sum)           # 預算內預計再花
            over_w = w(tf_sum - max(ta_sum, tb_sum))           # 預計再花中超出預算的部分
            over_c = STATUS_COLORS["高風險超支"]
            with card("forecast_gauge"):
                st.markdown(f'<div class="chart-title">{tx("全公司年底支出怎麼算出來？", "How the year-end total is built")}</div>', unsafe_allow_html=True,
                            help=tx("實色＝已經花掉的錢；斜紋＝依模型預估剩餘月份還會花的錢；兩段加起來就是年底預估。超過白色虛線（年度預算）的紅色部分就是超支。",
                                    "Solid = already spent; striped = what the model expects for the remaining months; together they make the year-end forecast. The red part past the dashed budget line is the overspend."))
                st.markdown(
                    f'<div class="gauge"><div class="g-bar">'
                    f'<div class="g-seg" style="width:{spent_w:.2f}%;background:{ACCENT}"><span>{tx("已花", "Spent")} {fpct(pct_of(ta_sum), decimals=0)}</span></div>'
                    + (f'<div class="g-seg" style="width:{spent_over_w:.2f}%;background:{over_c}"></div>' if spent_over_w > 0 else "")
                    + (f'<div class="g-seg g-hatch" style="width:{rest_w:.2f}%;--c:{ACCENT2}"><span>{tx("預計再花", "To spend")}</span></div>' if rest_w > 0 else "")
                    + (f'<div class="g-seg g-hatch" style="width:{over_w:.2f}%;--c:{over_c}"></div>' if over_w > 0 else "")
                    + f'<div class="g-limit" style="left:{tb_sum / scale * 100:.2f}%"><em style="transform:translateX({-100 if tb_sum / scale > .75 else -50}%)">'
                      f'{tx("年度預算", "Budget")} {fmc(tb_sum)}</em></div></div>'
                    f'<div class="g-legend">'
                    f'<span><i style="background:{ACCENT}"></i>{tx("已花", "Spent")} <b>{fmc(ta_sum)}</b></span>'
                    f'<span><i class="g-hatch" style="--c:{ACCENT2}"></i>{tx("預計再花", "Still to spend")} <b>{fmc(forecast_remaining_total)}</b></span>'
                    f'<span>＝ {tx("年底預估", "Year-end")} <b>{fmc(tf_sum)}</b>（{fpct(pct_of(tf_sum))}）</span>'
                    + (f'<span style="color:{over_c}"><i class="g-hatch" style="--c:{over_c}"></i>{tx("超出預算", "Over budget")} <b>{fmc(tf_sum - tb_sum)}</b></span>' if tf_sum > tb_sum else "")
                    + '</div></div>',
                    unsafe_allow_html=True,
                )

            dept_fc_col = st.container()
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
                show_chart(fc_fig, title=tx("哪些部門年底會超支？差多少？", "Which departments will overspend by year end, and by how much?"), key="forecast_dept", hint=tx("中線＝剛好用完預算；往右越長，年底超支越多，是最需要優先處理的部門。", "Centre line = exactly on budget; the longer the bar to the right, the bigger the year-end overspend and the higher the priority."),
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
            show_chart(monthly_path, title=tx("每個月花多少？已發生（實色）與預估（淡色）對照每月預算", "Monthly spend: actual (solid) and forecast (light) vs. monthly budget"), key="forecast_monthly", hint=tx("實色是已經發生的月份、淡色是預估；長條高過虛線的月份就是預計超出當月預算。", "Solid = months already closed, light = forecast; bars above the dashed line are months expected to exceed their budget."),
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
                    **{c: st.column_config.NumberColumn(format=MONEY_FMT) for c in [tx("全年預算", "Budget"), tx("已支出", "Actual"), tx("剩餘預估", "Remaining"), tx("年底預估", "Year-end")]},
                    tx("差額", "Difference"): st.column_config.NumberColumn(format=MONEY_FMT, help=tx("單位：新台幣萬元。正值為預計超支，負值為結餘。", "NT$ millions. Positive = expected overspend.")),
                    tx("差額率", "Difference %"): st.column_config.NumberColumn(format="%+.1f%%"),
                })
                st.caption(tx("單位：新台幣萬元。", "Unit: NT$ millions."))

                section(tx("逐月明細", "Monthly detail"))
                combined = monthly_actual.fillna(0) + monthly_estimate
                has_data = monthly_actual.notna() | (monthly_estimate > 0)
                monthly_detail = pd.DataFrame({
                    tx("月份", "Month"): [tx(f"{m} 月", f"Month {m}") for m in MONTHS],
                    tx("每月預算", "Budget"): to_m(monthly_budget).to_numpy(),
                    tx("已結算實際", "Closed actual"): to_m_text(monthly_actual.to_numpy()),
                    tx("剩餘月份預估", "Estimate"): to_m_text(monthly_estimate.where(monthly_estimate > 0).to_numpy()),
                    tx("對預算差額", "Vs. budget"): to_m_text((combined - monthly_budget).where(has_data).to_numpy()),
                    tx("資料狀態", "Data status"): [
                        tx("實際＋預估", "Actual + estimate") if pd.notna(monthly_actual.loc[m]) and monthly_estimate.loc[m] > 0
                        else tx("已結算", "Closed") if pd.notna(monthly_actual.loc[m])
                        else tx("預估", "Estimated") if monthly_estimate.loc[m] > 0
                        else tx("尚無資料", "No data")
                        for m in MONTHS
                    ],
                })
                st.dataframe(monthly_detail, hide_index=True, width="stretch", column_config={
                    tx("每月預算", "Budget"): st.column_config.NumberColumn(format=MONEY_FMT),
                    **{c: st.column_config.TextColumn(**MONEY_TEXT) for c in [tx("已結算實際", "Closed actual"), tx("剩餘月份預估", "Estimate"), tx("對預算差額", "Vs. budget")]},
                })

                section(tx("模型與歷史參考", "Model and historical reference"),
                        help_text=tx("參考區間是依歷史回測誤差估算的規劃範圍，不是統計信賴區間；歷史年度越少，估算越不穩定。",
                                     "The range is a planning range from historical backtest errors, not a statistical confidence interval. Fewer historical years make it less stable."))
                model_view = pd.DataFrame({
                    dept_col: analysis_res.Department.map(show_dept),
                    tx("Run-rate 推估", "Run-rate"): to_m(analysis_res.Forecast_Run_Rate),
                    tx("季節性推估", "Seasonal"): to_m_text(analysis_res.Forecast_Seasonal.to_numpy()),
                    tx("區間下限", "Range low"): to_m(analysis_res.Forecast_Low),
                    tx("區間上限", "Range high"): to_m(analysis_res.Forecast_High),
                    tx("完整歷史年度", "History years"): analysis_res.History_Years,
                    tx("區間依據", "Range basis"): analysis_res.Error_Basis,
                })
                st.dataframe(model_view, hide_index=True, width="stretch", column_config={
                    **{c: st.column_config.NumberColumn(format=MONEY_FMT) for c in [tx("Run-rate 推估", "Run-rate"), tx("區間下限", "Range low"), tx("區間上限", "Range high")]},
                    tx("季節性推估", "Seasonal"): st.column_config.TextColumn(**MONEY_TEXT),
                })

    if risk_views[1].open:
        with risk_views[1]:
            alert_rows = analysis_res[analysis_res.Status != "預算正常"].copy()
            alert_rows["_Priority"] = alert_rows.Status.map(STATUS_SEVERITY)
            alert_rows = alert_rows.sort_values(["_Priority", "Forecast_Var"], ascending=[True, False])
            actions = {
                "高風險超支": tx("請檢視未執行月份的採購、合約與支出計畫，必要時暫緩非必要支出。", "Review planned purchases, contracts and spending for the remaining months; defer discretionary spend if needed."),
                "需注意": tx("建議每月檢視非必要支出，並設定剩餘月份的支出上限。", "Review discretionary spending monthly and set a cap for the remaining months."),
                "執行落後": tx("確認專案時程與剩餘預算需求；若確定有餘額，可列為調撥來源。", "Confirm project timing and remaining needs; confirmed headroom can fund reallocation."),
            }
            ai_brief_panel("alerts")
            status_icons = {"高風險超支": "alert", "需注意": "activity", "執行落後": "clock"}
            status_cards = []
            for status in ["高風險超支", "需注意", "執行落後"]:
                rows = alert_rows[alert_rows.Status == status]
                gap = float(rows.Forecast_Var.sum())
                gap_pct = gap / float(rows.Budget_Full.sum()) * 100 if not rows.empty and rows.Budget_Full.sum() else 0.0
                status_cards.append(ui_kpi(
                    show_status(status), tx(f"{len(rows)} 個部門", f"{len(rows)} dept{'s' if len(rows) != 1 else ''}"),
                    (tx("年底合計 ", "Year-end total ") + fmc(gap, signed=True)) if not rows.empty else tx("目前沒有", "None"),
                    status_icons[status], STATUS_COLORS[status],
                    delta=ui_delta(tx("對其預算 ", "vs. their budget ") + fpct(gap_pct, signed=True), STATUS_COLORS[status]) if not rows.empty else ""))
            stat_row(status_cards)
            if alert_rows.empty:
                st.markdown(f'<div class="okcard">{icon("check", 17)} {tx("目前沒有符合預警條件的部門。", "No departments currently meet the alert criteria.")}</div>', unsafe_allow_html=True)
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
                    f'<div class="next">{icon("arrow", 14)} {actions[row.Status]}</div></div>',
                    unsafe_allow_html=True,
                )

            with st.expander(tx("預算摘要報告（可下載）", "Budget summary report (downloadable)"), icon=":material/description:"):
                usage_pct = ta_sum / tb_sum * 100 if tb_sum else 0
                var_pct = (tf_sum - tb_sum) / tb_sum * 100 if tb_sum else 0
                if IS_EN:
                    report_lines = [
                        f"# Budget summary | FY{selected_year}", "",
                        f"- **Total annual budget**: {fmc(tb_sum)}",
                        f"- **Actual spending to date** (through month {data_cutoff_month}): {fmc(ta_sum)} ({usage_pct:.1f}% of annual budget)",
                        f"- **Year-end forecast**: {fmc(tf_sum)} (variance **{fmc(tf_sum - tb_sum, signed=True)}**, **{var_pct:+.1f}%**)",
                        f"- **Summary**: {executive_summary(analysis_res)}", "", "## Department status", "",
                    ]
                else:
                    report_lines = [
                        f"# 法巴人壽 {selected_year} 年度預算摘要", "",
                        f"- **年度總預算**：{fmc(tb_sum)}",
                        f"- **目前已執行金額**（截至 {data_cutoff_month} 月）：{fmc(ta_sum)}（佔全年預算 **{usage_pct:.1f}%**）",
                        f"- **年底預測支出**：{fmc(tf_sum)}（預測差異 **{fmc(tf_sum - tb_sum, signed=True)}**，**{var_pct:+.1f}%**）",
                        f"- **智慧摘要**：{executive_summary(analysis_res)}", "", "## 部門狀態", "",
                    ]
                for r in analysis_res.sort_values("Forecast_Var", ascending=False).itertuples():
                    report_lines.append(
                        f"- **{show_dept(r.Department)}**：{status_label(r.Status)} ｜ {tx('同期執行率', 'To-date execution')} {fpct(r.Exec_Rate)} ｜ "
                        f"{tx('預測差異', 'Forecast variance')} {fmc(r.Forecast_Var, signed=True)}（{fpct(r.Forecast_Pct, signed=True)}）"
                        if not IS_EN else
                        f"- **{show_dept(r.Department)}**: {status_label(r.Status)} | To-date execution {fpct(r.Exec_Rate)} | "
                        f"Forecast variance {fmc(r.Forecast_Var, signed=True)} ({fpct(r.Forecast_Pct, signed=True)})"
                    )
                report_lines += ["", tx("> 本報告由預算分析儀表板自動產生；內建資料為合成示範資料。", "> Generated by the budget analysis dashboard; built-in data is synthetic.")]
                report_md = "\n".join(report_lines)
                st.markdown(md_safe(report_md))
                pdf_download(tx("下載預算摘要報告（PDF）", "Download budget summary report (PDF)"), budget_report_doc(),
                             f"Budget_summary_report_FY{selected_year}.pdf", "download_budget_report")

    if risk_views[2].open:
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
                    tx("一次性金額（萬元）", "One-off (M)"): to_m_text(event_summary.OneOff.where(event_summary.OneOff > 0).to_numpy()),
                })
                st.dataframe(event_table, hide_index=True, width="stretch", column_config={
                    tx("一次性金額（萬元）", "One-off (M)"): st.column_config.TextColumn(**MONEY_TEXT),
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
                    tx("本期（萬元）", "Current (M)"): to_m(drivers.Amount),
                    tx("歷史同期平均（萬元）", "Historical avg (M)"): to_m_text(drivers.Historical_Avg.to_numpy()),
                    tx("增加（萬元）", "Increase (M)"): to_m_text(drivers.Variance.to_numpy()),
                    tx("增幅", "Increase %"): drivers.Variance_Pct.round(1),
                })
                with st.expander(tx("查看全部科目比較", "View all category comparisons"), icon=":material/list:"):
                    st.dataframe(driver_view, hide_index=True, width="stretch", column_config={
                        dept_col: st.column_config.TextColumn(pinned=True),
                        tx("本期（萬元）", "Current (M)"): st.column_config.NumberColumn(format=MONEY_FMT),
                        tx("歷史同期平均（萬元）", "Historical avg (M)"): st.column_config.TextColumn(**MONEY_TEXT),
                        tx("增加（萬元）", "Increase (M)"): st.column_config.TextColumn(**MONEY_TEXT),
                        tx("增幅", "Increase %"): st.column_config.ProgressColumn(format="%+.1f%%", min_value=0, max_value=60, color="red"),
                    })
            else:
                st.info(tx("所選年度沒有可比較的往年資料。", "No prior-year data is available for comparison."))

            section(tx("多維度費用下鑽", "Multi-dimensional drill-down"), help_text=tx(
                "專案、供應商與成本中心皆為競賽合成資料（虛構名稱）。分析以「單位與用途」為對象，不以個人排名，避免把預算壓力歸咎到經辦人。",
                "Projects, vendors and cost centres are synthetic (fictional names). Analysis is by unit and purpose, never ranked by individual employee."))
            drill_dimensions = {
                "Account": tx("會計科目", "Expense category"), "Project": tx("專案", "Project"),
                "Vendor": tx("供應商", "Vendor"), "Cost_Center": tx("成本中心", "Cost center"),
            }
            drill_column = st.segmented_control(
                tx("費用維度", "Dimension"), list(drill_dimensions), format_func=lambda k: drill_dimensions[k],
                default="Account", required=True, key="expense_drill_dimension", label_visibility="collapsed",
            )
            if current_expenses.empty:
                st.info(tx("目前篩選條件沒有費用明細。", "No expense lines match the current filters."))
            elif drill_column == "Project":
                # 專案：日常營運占大宗，放在同一張圖會把專案擠成看不見，所以只畫專案、日常營運用比例說明
                total_spend = float(current_expenses.Amount.sum())
                projects = current_expenses[current_expenses.Project != OPEX_PROJECT].groupby(["Project", "Department"], as_index=False).Amount.sum()
                opex_share = 1 - (float(projects.Amount.sum()) / total_spend if total_spend else 0)
                if projects.empty:
                    st.info(tx("今年目前沒有專案支出；支出 100% 為日常營運。", "No project spending this year; 100% is routine operations."))
                else:
                    projects = projects.sort_values("Amount")
                    proj_fig = go.Figure()
                    for dept, part in projects.groupby("Department", sort=False):
                        proj_fig.add_bar(y=part.Project, x=part.Amount, orientation="h", name=show_dept(dept), marker_color=dept_color(dept),
                                         text=[f"{fmc(v)}（{v / total_spend * 100:.1f}%）" if not IS_EN else f"{fmc(v)} ({v / total_spend * 100:.1f}%)" for v in part.Amount],
                                         textposition="outside", cliponaxis=False, textfont=dict(color=TEXT, size=11.5))
                    proj_fig.update_layout(barmode="stack")
                    proj_fig.update_yaxes(categoryorder="total ascending", showgrid=False)
                    style_fig(proj_fig, height=max(260, 54 * projects.Project.nunique() + 100))
                    money_axis(proj_fig, horizontal=True, max_hint=float(projects.groupby("Project").Amount.sum().max()) * 1.45)
                    show_chart(proj_fig, title=tx("今年有哪些專案在花錢？", "Which projects are spending this year?"), key="drill_chart",
                               hint=tx(f"只列專案支出（括號為占總支出比例）；其餘 {opex_share * 100:.0f}% 是日常營運費用，沒有畫進來。專案通常是超支或延宕的來源，值得逐一追蹤。",
                                       f"Projects only (share of total in brackets); the other {opex_share * 100:.0f}% is routine operations and not drawn. Projects are the usual source of overruns or delays."))
            elif drill_column == "Account":
                # 科目：排名長條，依部門分段，看出「哪個科目最貴、由哪些部門花的」；尾端科目併成「其他」
                total_spend = float(current_expenses.Amount.sum())
                acct = current_expenses.groupby(["Account", "Department"], as_index=False).Amount.sum()
                acct_tot = acct.groupby("Account").Amount.sum().sort_values(ascending=False)
                top_accts, other_label = list(acct_tot.index[:12]), tx(f"其他 {max(len(acct_tot) - 12, 0)} 個科目", f"{max(len(acct_tot) - 12, 0)} other categories")
                acct["Label"] = [show_account(a) if a in top_accts else other_label for a in acct.Account]
                order = [show_account(a) for a in top_accts] + ([other_label] if len(acct_tot) > 12 else [])
                label_tot = acct.groupby("Label").Amount.sum().reindex(order)
                acct_fig = go.Figure()
                for dept in acct.groupby("Department").Amount.sum().sort_values(ascending=False).index:
                    part = acct[acct.Department == dept].groupby("Label", as_index=False).Amount.sum()
                    acct_fig.add_bar(y=part.Label, x=part.Amount, orientation="h", name=show_dept(dept), marker_color=dept_color(dept))
                acct_fig.add_scatter(y=order, x=label_tot.to_numpy(), mode="text", textposition="middle right", showlegend=False,
                                     text=[f"  {fmc(v)} · {v / total_spend * 100:.1f}%" for v in label_tot], textfont=dict(color=TEXT, size=11.5),
                                     cliponaxis=False, hoverinfo="skip", hovertemplate="skip")
                acct_fig.update_layout(barmode="stack")
                acct_fig.update_yaxes(categoryorder="array", categoryarray=order[::-1], showgrid=False)
                style_fig(acct_fig, height=max(320, 34 * len(order) + 120))
                money_axis(acct_fig, horizontal=True, max_hint=float(label_tot.max()) * 1.4)
                show_chart(acct_fig, title=tx("今年的錢花在哪些會計科目？", "Where did this year's money go, by category?"), key="drill_chart",
                           hint=tx("由上往下是花費最多的科目，顏色代表由哪個部門支出；右側為金額與占總支出比例。跨部門共用的科目（如差旅、訓練）會出現多種顏色。",
                                   "Top to bottom are the costliest categories; colours show which department spent it, with amount and share of total on the right. Shared categories (travel, training) show several colours."))
            elif drill_column == "Vendor":
                # 供應商：柏拉圖式排名（累計占比），前 5 大加深，直接回答集中度
                total_spend = float(current_expenses.Amount.sum())
                vend = current_expenses.groupby("Vendor").Amount.sum().sort_values(ascending=False)
                cum_share = vend.cumsum() / total_spend if total_spend else vend * 0
                core_n, top_n = min(5, len(vend)), min(12, len(vend))
                top5_share, top10_share = float(cum_share.iloc[core_n - 1]), float(cum_share.iloc[min(10, len(vend)) - 1])
                short = lambda v: re.sub(r"(股份有限公司|有限公司|Co\.?,? Ltd\.?)$", "", show_vendor(v)).strip()
                names = [short(v) for v in vend.index[:top_n]]
                values, cums = list(vend.to_numpy()[:top_n]), list(cum_share.to_numpy()[:top_n])
                colors = [ACCENT if i < core_n else rgba(ACCENT, .35) for i in range(top_n)]
                rest_note = tx(f"其餘 {len(vend) - top_n} 家合計 {(1 - cums[-1]) * 100:.0f}% 未畫出。", f"The other {len(vend) - top_n} ({(1 - cums[-1]) * 100:.0f}%) are not drawn. ") if len(vend) > top_n else ""
                vend_fig = go.Figure(go.Bar(
                    y=names, x=values, orientation="h", marker_color=colors, cliponaxis=False, textposition="outside",
                    textfont=dict(color=TEXT, size=11.5), customdata=[fmc(v) for v in values],
                    text=[f"{fmc(v)} · {tx('累計', 'cum.')} {c * 100:.0f}%" for v, c in zip(values, cums)],
                ))
                vend_fig.update_yaxes(categoryorder="array", categoryarray=names[::-1], showgrid=False)
                style_fig(vend_fig, height=max(320, 32 * len(names) + 100), legend=False)
                money_axis(vend_fig, horizontal=True, max_hint=max(values) * 1.5)
                vend_fig.data[0].hovertemplate = "<b>%{y}</b><br>%{text}<extra></extra>"
                show_chart(vend_fig, title=tx("支出集中在哪些供應商？", "How concentrated is vendor spending?"), key="drill_chart",
                           hint=tx(f"共 {len(vend)} 家供應商：深色前 {core_n} 大占 {top5_share * 100:.0f}%、前 10 大占 {top10_share * 100:.0f}%（右側為累計比例），" + rest_note
                                   + ("支出集中在少數供應商，議價空間與依賴風險值得檢視。" if top5_share >= .5 else "支出分散，沒有單一供應商依賴；可檢視同類服務是否能整併議價。"),
                                   f"{len(vend)} vendors: the {core_n} darker bars make up {top5_share * 100:.0f}%, the top 10 {top10_share * 100:.0f}% (cumulative share on the right). " + rest_note
                                   + ("Spend is concentrated: review negotiation leverage and dependency risk." if top5_share >= .5 else "Spend is spread out with no single-vendor dependency; look for similar services to consolidate.")))
            else:
                # 成本中心：依部門分組排列，標示各單位占所屬部門的比例，找到要溝通的負責單位
                cc = current_expenses.groupby(["Department", "Cost_Center"], as_index=False).Amount.sum()
                dept_tot = cc.groupby("Department").Amount.sum().sort_values(ascending=False)
                cc["Share"] = cc.Amount / cc.Department.map(dept_tot)
                cc["Rank"] = cc.Department.map({d: i for i, d in enumerate(dept_tot.index)})
                cc = cc.sort_values(["Rank", "Amount"], ascending=[True, False])
                cc_fig = go.Figure()
                for dept in dept_tot.index:
                    part = cc[cc.Department == dept]
                    cc_fig.add_bar(y=part.Cost_Center, x=part.Amount, orientation="h", name=show_dept(dept), marker_color=dept_color(dept),
                                   text=[f"{fmc(v)} · {tx('占部門', 'of dept')} {s * 100:.0f}%" for v, s in zip(part.Amount, part.Share)],
                                   textposition="outside", cliponaxis=False, textfont=dict(color=TEXT, size=11.5))
                cc_fig.update_yaxes(categoryorder="array", categoryarray=list(cc.Cost_Center)[::-1], showgrid=False)
                style_fig(cc_fig, height=max(320, 30 * len(cc) + 130))
                money_axis(cc_fig, horizontal=True, max_hint=float(cc.Amount.max()) * 1.55)
                show_chart(cc_fig, title=tx("各部門底下哪個成本中心花最多？", "Which cost centre spends most in each department?"), key="drill_chart",
                           hint=tx("同色為同一部門，部門依總支出由上往下排；「占部門」表示該單位占所屬部門支出的比例，比例越高越是該部門要先溝通的單位。",
                                   "Same colour = same department, ordered by department spend; 'of dept' is the unit's share of its department, so the highest share is the first team to talk to."))

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
                    tx("發票／憑證號碼", "Invoice no."): duplicates.Expense_ID,
                    tx("採購單號", "PO"): duplicates.Purchase_Order,
                    tx("金額（元）", "Amount (NT$)"): duplicates.Amount,
                }), hide_index=True, width="stretch", column_config={
                    tx("金額（元）", "Amount (NT$)"): st.column_config.NumberColumn(format="%,d"),
                })

            # ---- 費用明細帳：逐筆發票層級，主管可直接查到「哪張單、誰申請、誰核准」----
            section(tx("費用明細帳", "Expense ledger"), help_text=tx(
                "逐筆發票層級的費用明細（合成資料）：日期、憑證號碼、科目代碼、成本中心、專案、供應商、經辦人與核准層級。經辦人欄位僅供內控與稽核追蹤，不作為個人績效評比；單筆 NT$ 200 萬以上需財務長核准。可用表格右上角的搜尋找特定供應商或單號。",
                "Invoice-level synthetic ledger: date, voucher, GL code, cost centre, project, vendor, handler and approval level. The handler field is for internal-control traceability only, not individual performance review. Lines of NT$2M or more need CFO approval."))
            ledger_cols = st.columns([1.2, 1.2, 1], vertical_alignment="bottom")
            ledger_dept = ledger_cols[0].selectbox(tx("部門", "Department"), ["__all__"] + selected_depts, key="ledger_dept",
                                                   format_func=lambda d: tx("全部部門", "All departments") if d == "__all__" else show_dept(d))
            ledger_account = ledger_cols[1].selectbox(tx("會計科目", "Category"), ["__all__"] + sorted(current_expenses.Account.unique(), key=lambda a: GL_CODES.get(a, "9")),
                                                      key="ledger_account", format_func=lambda a: tx("全部科目", "All categories") if a == "__all__" else f"{GL_CODES.get(a, '')} {show_account(a)}")
            ledger_big = ledger_cols[2].toggle(tx("只看需財務長核准", "CFO-approval lines only"), key="ledger_big")
            ledger = current_expenses
            if ledger_dept != "__all__":
                ledger = ledger[ledger.Department == ledger_dept]
            if ledger_account != "__all__":
                ledger = ledger[ledger.Account == ledger_account]
            if ledger_big:
                ledger = ledger[ledger.Approval == "財務長"]
            ledger = ledger.sort_values(["Invoice_Date", "Expense_ID"], ascending=False)
            st.caption(tx(f"共 {len(ledger):,} 筆，合計 {fmc(ledger.Amount.sum())}；顯示最近 300 筆。",
                          f"{len(ledger):,} lines totalling {fmc(ledger.Amount.sum())}; showing the latest 300."))
            shown = ledger.head(300)
            st.dataframe(pd.DataFrame({
                tx("日期", "Date"): shown.Invoice_Date,
                tx("憑證號碼", "Voucher"): shown.Expense_ID,
                dept_col: shown.Department.map(show_dept),
                tx("成本中心", "Cost centre"): shown.Cost_Center,
                tx("科目", "GL account"): shown.GL_Code + " " + shown.Account.map(show_account),
                tx("供應商", "Vendor"): shown.Vendor.map(show_vendor),
                tx("摘要", "Description"): shown.Description.map(show_memo),
                tx("專案", "Project"): shown.Project,
                tx("經辦人", "Handled by"): [show_employee(c, n, d) for c, n, d in zip(shown.Employee, shown.Employee_Name, shown.Department)],
                tx("核准層級", "Approval"): shown.Approval.map(lambda a: APPROVAL_EN.get(a, a) if IS_EN else a),
                tx("金額（元）", "Amount (NT$)"): shown.Amount,
            }), hide_index=True, width="stretch", height=420, column_config={
                tx("金額（元）", "Amount (NT$)"): st.column_config.NumberColumn(format="%,d"),
                tx("憑證號碼", "Voucher"): st.column_config.TextColumn(pinned=True),
            })

# ------------------------------------------
# 情境與資料品質
# ------------------------------------------
if active_nav_id == "scenarios_quality":
    page_header(tx("情境模擬與資料品質", "Scenarios & data quality"),
                tx("情境結果是規劃估算，並非現金流預測；調撥建議不會自動變更任何預算。", "Scenario results are planning estimates, not cash-flow forecasts. Recommendations never change budgets automatically."))
    planning_views = st.tabs([tx("情境與調撥", "Scenarios"), tx("回測與資料品質", "Backtest & data quality")], key="tabs_planning", on_change="rerun")

    if planning_views[0].open:
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

            scenario_total = float(scenario.Scenario_Forecast.sum())
            scenario_shift = scenario_total - tf_sum
            scenario_active = any(abs(v) > 1e-9 for v in (inflation_delta, volume_growth, fx_change))
            base_use = tf_sum / tb_sum * 100 if tb_sum else 0.0
            scen_use = scenario_total / tb_sum * 100 if tb_sum else 0.0
            scen_var = float(scenario.Scenario_Variance.sum())
            over_n = int((scenario.Scenario_Variance > 0).sum())
            base_n = int((analysis_res.Forecast_Var > 0).sum())
            over_c, ok_c = STATUS_COLORS["高風險超支"], STATUS_COLORS["預算正常"]
            stat_row([
                ui_kpi(tx("原本：年底預算使用率", "Before: year-end budget use"), fpct(base_use), tx(f"預測 {fmc(tf_sum)}", f"forecast {fmc(tf_sum)}"),
                       "target", MUTED, delta=ui_delta(tx("未套用情境", "No scenario"), MUTED),
                       help=tx("未套用任何情境假設時，年底會用掉全年預算的比例。", "Share of the annual budget used by year end with no scenario applied.")),
                ui_kpi(tx("套用情境後：預算使用率", "With scenario: budget use"), fpct(scen_use), tx(f"預測 {fmc(scenario_total)}", f"forecast {fmc(scenario_total)}"),
                       "sliders", over_c if scen_use > 100 else ok_c,
                       delta=ui_delta(tx(f"{scen_use - base_use:+.1f} 個百分點", f"{scen_use - base_use:+.1f} pp"), over_c if scenario_shift > 0 else ok_c,
                                      "up" if scenario_shift > 0 else "down") if abs(scenario_shift) >= 1 else ui_delta(tx("與原本相同", "Same as before"), MUTED),
                       help=tx("情境只影響尚未發生的剩餘月份，已發生的支出不變。", "Scenarios only affect the remaining months; spending already incurred is unchanged.")),
                ui_kpi(tx("套用情境後：年底超支" if scen_var > 0 else "套用情境後：年底結餘", "With scenario: overspend" if scen_var > 0 else "With scenario: headroom"),
                       fpct(abs(scen_var) / tb_sum * 100 if tb_sum else 0), tx(f"約 {fmc(abs(scen_var))}", f"about {fmc(abs(scen_var))}"),
                       "alert" if scen_var > 0 else "shield", over_c if scen_var > 0 else ok_c,
                       delta=ui_delta(tx("超出年度預算", "Over budget") if scen_var > 0 else tx("低於年度預算", "Under budget"), over_c if scen_var > 0 else ok_c)),
                ui_kpi(tx("套用情境後：超支部門", "With scenario: departments over"), f"{over_n} / {len(scenario)}",
                       tx(f"原本 {base_n} 個", f"before: {base_n}"), "building", over_c if over_n else ok_c,
                       delta=ui_delta(tx(f"{over_n - base_n:+d} 個", f"{over_n - base_n:+d}"), over_c if over_n > base_n else (ok_c if over_n < base_n else MUTED))),
            ])
            if not scenario_active:
                st.caption(tx(":material/info: 目前三個假設都是 0%，所以「套用情境後」與原本相同；拖動上方滑桿即可看到影響。",
                              ":material/info: All three assumptions are 0%, so the scenario equals the original forecast. Move the sliders above to see the impact."))

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
            show_chart(scenario_chart, title=tx("情境假設下，各部門年底會超支還是有結餘？", "Under this scenario, which departments end over or under budget?"), key="scenario_chart", hint=tx("調整上方滑桿後，看哪些部門從結餘變成超支——就是對通膨、業務量或匯率最敏感的部門。", "Move the sliders above and watch which departments flip from headroom to overspend: those are the most sensitive to inflation, volume or FX."),
                       help_text=tx("中線＝剛好用完年度預算；往右＝超支、往左＝結餘。灰色＝目前預測，彩色＝套用上方情境後（顏色為情境下的燈號）。情境只影響尚未發生的月份。",
                                    "Centre line = exactly the budget; right = overspend, left = headroom. Grey = current forecast, coloured = with the scenario applied (colour = scenario status). Only future months change."))

            scenario_view = pd.DataFrame({
                dept_col: names,
                tx("情境燈號", "Scenario status"): scenario.Scenario_Status.map(status_label),
                tx("基準預測（萬元）", "Base (M)"): to_m(scenario.Forecast_EOY),
                tx("情境預測（萬元）", "Scenario (M)"): to_m(scenario.Scenario_Forecast),
                tx("年度預算（萬元）", "Budget (M)"): to_m(scenario.Budget_Full),
                tx("情境差異（萬元）", "Scenario variance (M)"): to_m(scenario.Scenario_Variance),
            })
            st.dataframe(scenario_view, hide_index=True, width="stretch", column_config={
                dept_col: st.column_config.TextColumn(pinned=True),
                **{c: st.column_config.NumberColumn(format=MONEY_FMT) for c in [tx("基準預測（萬元）", "Base (M)"), tx("情境預測（萬元）", "Scenario (M)"), tx("年度預算（萬元）", "Budget (M)")]},
                tx("情境差異（萬元）", "Scenario variance (M)"): st.column_config.NumberColumn(format=MONEY_FMT),
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
                    donor_row = scenario.loc[scenario.Department == donor].iloc[0]
                    recipient_row = scenario.loc[scenario.Department == recipient].iloc[0]
                    request_no = f"TR-{selected_year}-{DEPTS.index(donor) + 1:02d}{DEPTS.index(recipient) + 1:02d}-{int(amount / 1e4) % 10000:04d}"
                    transfer_doc = {
                        "title": tx("預算調撥申請單", "Budget Transfer Request"),
                        "subtitle": tx("草稿｜待人工覆核與核准", "Draft · pending review and approval"),
                        "meta": [request_no, f"FY{selected_year}", tx("申請日期 ", "Date ") + datetime.now().strftime("%Y-%m-%d"), tx("狀態：草稿", "Status: draft")],
                        "blocks": [
                            ("heading", tx("調撥內容", "Transfer details")),
                            ("fields", [
                                (tx("申請單號", "Request no."), request_no),
                                (tx("調出部門", "From department"), show_dept(donor)),
                                (tx("調入部門", "To department"), show_dept(recipient)),
                                (tx("建議調撥金額上限", "Suggested amount cap"), fmc(amount)),
                                (tx("調出部門 年底預測／預算", "From: forecast / budget"), f"{fmc(donor_row.Forecast_EOY)} ／ {fmc(donor_row.Budget_Full)}（{fpct(donor_row.Forecast_Pct, signed=True)}）"),
                                (tx("調入部門 年底預測／預算", "To: forecast / budget"), f"{fmc(recipient_row.Forecast_EOY)} ／ {fmc(recipient_row.Budget_Full)}（{fpct(recipient_row.Forecast_Pct, signed=True)}）"),
                                (tx("情境假設", "Scenario assumptions"), f"{tx('通膨', 'Inflation')} {inflation_delta:+.1%}｜{tx('業務量', 'Volume')} {volume_growth:+.1%}｜{tx('匯率', 'FX')} {fx_change:+.1%}"),
                            ]),
                            ("heading", tx("申請原因", "Rationale")), ("note_box", request_reason),
                            ("heading", tx("簽核", "Approvals")),
                            ("signatures", [tx("申請人", "Requester"), tx("調出部門主管", "From-dept head"), tx("調入部門主管", "To-dept head"), tx("財務長", "CFO")]),
                            ("paragraph", tx("此文件僅為申請草稿：下載不會變更任何預算，也不會送出簽核；實際金額與專案承諾須由主管覆核。",
                                             "Draft only: downloading does not change budgets or submit an approval. A manager must review the final amount and commitments."), 8.5, PDF_MUTED),
                        ],
                    }
                    pdf_download(tx("下載調撥申請單（PDF）", "Download transfer request (PDF)"), transfer_doc,
                                 f"Budget_transfer_request_{request_no}.pdf", "download_transfer_draft")
            else:
                st.info(tx("依目前情境，沒有可配對的預算餘額與預測缺口。", "This scenario has no available headroom that can be paired with a forecast shortfall."))

    if planning_views[1].open:
        with planning_views[1]:
            prior_years = sorted(int(y) for y in df_db.loc[df_db.Year < selected_year, "Year"].unique())
            explain_card(tx("這頁在證明什麼？年底預測到底準不準", "What this proves: how accurate the year-end forecast is"), [
                tx("回到過去某一年的某個月份（下方滑桿），只用「當時已經知道」的支出資料。", "Go back to a month in a past year (slider below), using only the spending known at that time."),
                tx("用本系統的方法預測那一年年底會花多少，同時用「照目前速度推估」當對照組。", "Forecast that year's total with this system, and with a simple pace projection as the benchmark."),
                tx("再和那一年「真正花掉的金額」比對：誤差越小，代表今年的預測越值得信任。", "Compare with what was actually spent that year: the smaller the error, the more you can trust this year's forecast."),
            ])
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
                    better = combined_wape <= baseline_wape
                    good_c, bad_c = STATUS_COLORS["預算正常"], STATUS_COLORS["高風險超支"]
                    stat_row([
                        ui_kpi(tx("本系統預測誤差", "This system's forecast error"), f"{combined_wape:.1f}%",
                               tx(f"平均每 100 元差 {combined_wape:.1f} 元", f"≈ {combined_wape:.1f} off per 100"), "target", good_c if better else bad_c,
                               delta=ui_delta(tx(f"優於對照 {baseline_wape - combined_wape:.1f} 個百分點", f"{baseline_wape - combined_wape:.1f} pp better") if better
                                              else tx(f"劣於對照 {combined_wape - baseline_wape:.1f} 個百分點", f"{combined_wape - baseline_wape:.1f} pp worse"), good_c if better else bad_c),
                               help=tx(f"用過去年度模擬「在 {backtest_month} 月做預測」，再和該年實際全年支出比較（WAPE，加權平均絕對誤差）。",
                                       f"Simulates forecasting in month {backtest_month} of past years and compares with the actual full year (WAPE).")),
                        ui_kpi(tx("對照：照目前速度推估", "Benchmark: simple pace"), f"{baseline_wape:.1f}%",
                               tx(f"平均每 100 元差 {baseline_wape:.1f} 元", f"≈ {baseline_wape:.1f} off per 100"), "activity", MUTED,
                               delta=ui_delta(tx("未考慮季節性", "No seasonality"), MUTED),
                               help=tx("只把目前的花費速度延伸到年底（Run-rate），不考慮年底旺季等季節性；作為比較基準。",
                                       "Extends the current spending pace to year end (run rate) without seasonality; used as the benchmark.")),
                        ui_kpi(tx("驗證次數", "Test cases"), tx(f"{len(backtest_df)} 次", f"{len(backtest_df)}"),
                               tx(f"{backtest_df.Year.nunique()} 個年度 × {backtest_df.Department.nunique()} 個部門", f"{backtest_df.Year.nunique()} years × {backtest_df.Department.nunique()} depts"),
                               "layers", ACCENT, delta=ui_delta(tx("歷史資料", "History"), ACCENT)),
                    ])
                    # 各部門預測誤差：本系統 vs 對照組，長條越短越準（取代原本「實際長條＋兩個點」難以解讀的圖）
                    by_dept = backtest_df.groupby("Department").agg(Actual=("Actual", "sum"), Model=("Abs_Error", "sum"),
                                                                    Bench=("Run_Rate_Abs_Error", "sum"))
                    by_dept["Model_Pct"] = by_dept.Model / by_dept.Actual * 100
                    by_dept["Bench_Pct"] = by_dept.Bench / by_dept.Actual * 100
                    by_dept = by_dept.sort_values("Model_Pct", ascending=True)
                    names = [show_dept(d) for d in by_dept.index]
                    bt_fig = go.Figure()
                    bt_fig.add_bar(y=names, x=by_dept.Bench_Pct, orientation="h", name=tx("對照：照目前速度推估", "Benchmark: simple pace"),
                                   marker_color=rgba(MUTED, .45), text=[f"{v:.1f}%" for v in by_dept.Bench_Pct], textposition="outside",
                                   textfont=dict(color=MUTED, size=11), cliponaxis=False,
                                   hovertemplate="<b>%{y}</b><br>" + tx("對照組誤差", "Benchmark error") + " %{x:.1f}%<extra></extra>")
                    bt_fig.add_bar(y=names, x=by_dept.Model_Pct, orientation="h", name=tx("本系統預測", "This system"),
                                   marker_color=STATUS_COLORS["預算正常"], text=[f"{v:.1f}%" for v in by_dept.Model_Pct], textposition="outside",
                                   textfont=dict(color=TEXT, size=11.5), cliponaxis=False,
                                   hovertemplate="<b>%{y}</b><br>" + tx("本系統誤差", "System error") + " %{x:.1f}%<extra></extra>")
                    style_fig(bt_fig, height=max(320, 52 * len(by_dept) + 80))
                    bt_fig.update_layout(barmode="group", bargap=.3, bargroupgap=.08)
                    bt_fig.update_xaxes(ticksuffix="%", rangemode="tozero", range=[0, float(max(by_dept.Bench_Pct.max(), by_dept.Model_Pct.max())) * 1.25 + .5])
                    bt_fig.update_yaxes(showgrid=False)
                    best = by_dept.index[0]
                    years_text = "、".join(str(y) for y in sorted(backtest_df.Year.unique())) if not IS_EN else ", ".join(str(y) for y in sorted(backtest_df.Year.unique()))
                    show_chart(bt_fig, title=tx(f"如果在 {backtest_month} 月預測年底，各部門會差多少？", f"If we had forecast the year end in month {backtest_month}, how far off would each department be?"),
                               key="backtest_chart",
                               hint=tx(f"長條越短越準。綠色是本系統、灰色是單純照目前速度推估；驗證年度：{years_text}。{show_dept(best)}預測最穩定。",
                                       f"Shorter is more accurate. Green = this system, grey = simple pace projection; test years: {years_text}. {show_dept(best)} is the most stable."),
                               help_text=tx("年底集中請款的部門（例如行銷、人資）若只照目前速度推估，會系統性低估；本系統加入歷史季節性修正這個偏差。",
                                            "Departments with a year-end spending surge are systematically under-forecast by a simple pace projection; adding historical seasonality corrects this."))
                    backtest_view = pd.DataFrame({
                        tx("年度", "Year"): backtest_df.Year.astype(str),
                        dept_col: backtest_df.Department.map(show_dept),
                        tx("全年實際（萬元）", "Actual (M)"): to_m(backtest_df.Actual),
                        tx("模型預測（萬元）", "Model (M)"): to_m(backtest_df.Forecast),
                        tx("Run-rate（萬元）", "Run-rate (M)"): to_m(backtest_df.Run_Rate_Forecast),
                        tx("模型誤差", "Model error"): backtest_df.Abs_Error_Pct.round(1),
                    })
                    with st.expander(tx("查看回測明細", "View backtest detail"), icon=":material/list:"):
                        st.dataframe(backtest_view, hide_index=True, width="stretch", column_config={
                            **{c: st.column_config.NumberColumn(format=MONEY_FMT) for c in [tx("全年實際（萬元）", "Actual (M)"), tx("模型預測（萬元）", "Model (M)"), tx("Run-rate（萬元）", "Run-rate (M)")]},
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
                f'<div class="check"><span style="color:{STATUS_COLORS["預算正常"] if ok else STATUS_COLORS["需注意"]}">{icon("check" if ok else "alert", 16)}</span><span>{label}</span>'
                f'<b style="color:{STATUS_COLORS["預算正常"] if ok else STATUS_COLORS["需注意"]}">{tx("通過", "Pass") if ok else tx("需檢查", "Review")}</b></div>'
                for label, ok in checks
            )
            rows_html += f'<div class="check"><span style="color:{MUTED}">{icon("database", 16)}</span><span>{tx("資料來源", "Data source")}</span><b>{data_source}</b></div>'
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
        # 訪客只看到「已連線」；模型名稱與備援順序屬於維運資訊，收在 ? 提示裡供部署檢查用。
        backups = "、".join(p["label"].split(" · ")[0] for p in chain[1:])
        detail = tx(f"目前模型：{chain[0]['label']}；備援：{backups + ' → ' if backups else ''}內建規則",
                    f"Model: {chain[0]['label']}; fallback: {backups + ' → ' if backups else ''}built-in rules")
        st.markdown(f'<div class="chips">{ui_chip(tx("AI 助理已連線", "AI assistant online"), STATUS_COLORS["預算正常"])}</div>',
                    unsafe_allow_html=True, help=detail)
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

    prompt_row = st.container(key="nowrap-prompt").columns([5, 1])
    with prompt_row[0]:
        st.pills(tx("快速提問", "Quick questions"), prompts, key="quick_prompt", label_visibility="collapsed", on_change=queue_quick_prompt, wrap=True)
    with prompt_row[1]:
        if st.button(tx("清除對話", "Clear chat"), key="clear_chat", icon=":material/delete_sweep:", width="stretch"):
            st.session_state.pop("chat_messages", None)
            st.rerun()

    for i, message in enumerate(st.session_state.chat_messages):
        with st.chat_message(message["role"], avatar=":material/person:" if message["role"] == "user" else ":material/auto_awesome:"):
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
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(md_safe(user_input))
        with st.chat_message("assistant", avatar=":material/auto_awesome:"):
            source = tx("內建規則", "Built-in rules")
            if ai_available():
                conversation = st.session_state.chat_messages[-12:]
                while conversation and conversation[0]["role"] == "assistant":
                    conversation = conversation[1:]
                system_context = AI_RULES + json.dumps(build_ai_facts(user_input), ensure_ascii=False)
                try:
                    with st.spinner(tx(f"{ai_provider_label()} 思考中…", f"{ai_provider_label()} is thinking…")):
                        reply, source, notes = llm_answer(conversation, system_context)
                    if notes and not ai_locked:  # 略過原因屬維運資訊，公開模式不顯示給訪客
                        source += tx("（已自動略過：", " (skipped: ") + "；".join(notes) + tx("）", ")")
                except Exception as err:
                    reply = local_budget_reply(user_input, analysis_res, selected_year)
                    source = tx("內建規則（模型額度已用完或無法連線）", "Built-in rules (model quota used up or unreachable)")
                    if not ai_locked:
                        st.caption(f":material/info: {err}")
                st.markdown(md_safe(reply))
            else:
                reply = local_budget_reply(user_input, analysis_res, selected_year)
                st.markdown(md_safe(reply))
            q = user_input.casefold()
            chart_terms = ["圖", "趨勢", "走勢", "圖表", "chart", "plot", "trend", "graph", "哪個部門", "哪些部門", "which department", "which departments", "overspend", "risk", "專案", "供應商", "成本中心", "project", "vendor", "cost center"]
            chart_terms += [term.casefold() for dept in selected_depts for term in (dept.split(" (")[0], DEPT_EN.get(dept.split(" (")[0], "")) if term]
            chart_terms += [term.casefold() for account in ACCOUNT_EN for term in (account, ACCOUNT_EN[account])]
            chart_spec = None
            if any(term in q for term in chart_terms):
                matched_department = next((d for d in selected_depts if d.split(" (")[0].casefold() in q or DEPT_EN.get(d.split(" (")[0], "").casefold() in q), None)
                matched_account = next((account for account in ACCOUNT_EN if account.casefold() in q or ACCOUNT_EN[account].casefold() in q), None)
                dimension_aliases = {
                    "Project": ("專案", "project"), "Vendor": ("供應商", "廠商", "vendor", "supplier"),
                    "Cost_Center": ("成本中心", "cost center"),
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
