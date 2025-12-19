# streamlit_app.py
# -*- coding: utf-8 -*-

import re
import unicodedata
import streamlit as st
import pandas as pd
from station_core import find_walkable_stations

# =========================
# ページ設定
# =========================
st.set_page_config(page_title="住所から徒歩圏内の駅を検索", layout="wide")

st.markdown(
    """
    <style>
      :root{
        --addr-header-size: 1.2rem; /* 「住所を入力」 */
        --title-size: 1.9rem;       /* アプリタイトル（ここだけ調整すればOK） */
      }

      .app-title{
        font-size: var(--title-size);
        font-weight: 700;
        line-height: 1.3;
        margin: 0.2rem 0 0.4rem 0;
        letter-spacing: 0.03em;
      }

      .app-title-divider{
        border-bottom: 2px solid #e5e7eb;
        margin-bottom: 0.8rem;
      }

      .addr-header{
        font-size: var(--addr-header-size);
        font-weight: 600;
        margin: 0.6rem 0 0.2rem 0;
      }

      /* コピペ欄は等幅フォント */
      .stTextArea textarea{
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
                     "Liberation Mono", "Courier New", monospace;
        white-space: pre;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================
# タイトル表示
# =========================
st.markdown(
    """
    <div class="app-title">住所から徒歩圏内の駅を検索</div>
    <div class="app-title-divider"></div>
    """,
    unsafe_allow_html=True,
)

st.caption(
    "徒歩分は直線距離を「徒歩1分=80m」で換算した目安です（実際の徒歩ルート時間ではありません）。"
)

# =========================
# 正規化・整形関数
# =========================
def normalize_address(addr: str) -> str:
    """住所の表記ゆれを正規化"""
    if not addr:
        return ""
    s = unicodedata.normalize("NFKC", addr)
    s = re.sub(r"[‐-‒–—―ー－−]", "-", s)
    s = re.sub(r"[ 　\t]+", " ", s).strip()
    return s


def normalize_station_name(name: str) -> str:
    """駅名の空白ゆれを除去"""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name)
    s = s.replace("　", " ")
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s


def safe_lines(lines, sep: str = "・") -> str:
    """路線の安全な文字列化"""
    try:
        if lines:
            cleaned = [str(x).strip() for x in lines if x and str(x).strip()]
            if cleaned:
                return sep.join(cleaned)
    except Exception:
        pass
    return "不明"


def dedupe_and_sort(results):
    """重複除去＋徒歩→距離→駅名で安定ソート"""
    best = {}
    for r in results:
        name = getattr(r, "station_name", "") or ""
        walk = getattr(r, "walk_minutes", 10**9)
        dist = getattr(r, "distance_m", 10**12)
        key = str(getattr(r, "station_id", "") or getattr(r, "id", "") or name).strip()
        if not key:
            continue

        prev = best.get(key)
        if prev is None:
            best[key] = r
        else:
            if (walk, dist) < (
                getattr(prev, "walk_minutes", 10**9),
                getattr(prev, "distance_m", 10**12),
            ):
                best[key] = r

    cleaned = list(best.values())
    cleaned.sort(
        key=lambda r: (
            getattr(r, "walk_minutes", 10**9),
            getattr(r, "distance_m", 10**12),
            normalize_station_name(getattr(r, "station_name", "") or ""),
        )
    )
    return cleaned


def station_label(r) -> str:
    name = normalize_station_name(getattr(r, "station_name", "") or "")
    if not name:
        return "駅"
    return name if name.endswith("駅") else f"{name}駅"


def format_copy_block(r) -> str:
    station = station_label(r)
    walk = int(getattr(r, "walk_minutes", 0))
    lines_str = safe_lines(getattr(r, "lines", None), sep="・")
    return f"{station} 徒歩{walk}分\n（{lines_str}）"

# =========================
# サイドバー
# =========================
with st.sidebar:
    st.header("検索設定")
    徒歩上限分 = st.slider("徒歩上限（分）", 5, 60, 30, 5)
    表示件数 = st.slider("表示件数（最大）", 1, 10, 3, 1)

    候補取得を多めに = st.checkbox("結果の漏れ防止（候補を多めに取得）", value=True)
    if 候補取得を多めに:
        st.caption("表示件数より多めに候補駅を取得して並べ替えます。")

    st.divider()
    st.subheader("入力のコツ")
    st.write("・郵便番号7桁が入っていると精度が上がります。")
    st.write("・例：〒980-0021 仙台市青葉区中央二丁目10-20")

# =========================
# 入力欄
# =========================
st.markdown('<div class="addr-header">住所を入力</div>', unsafe_allow_html=True)

with st.form("form", clear_on_submit=False):
    住所 = st.text_input(
        "住所（郵便番号7桁付き推奨）",
        value="〒980-0021 仙台市青葉区中央二丁目10-20",
    )
    col1, _ = st.columns([1, 8])
    検索 = col1.form_submit_button("検索")

@st.cache_data(ttl=3600, show_spinner=False)
def cached_search(addr_norm, walk_min, max_candidates):
    return find_walkable_stations(addr_norm, max_walk_min=walk_min, max_candidates=max_candidates)

# =========================
# 検索処理
# =========================
if 検索:
    addr_norm = normalize_address(住所)

    if not addr_norm:
        st.error("住所が空です。入力してください。")
        st.stop()

    max_candidates = max(表示件数 * 8, 30) if 候補取得を多めに else 表示件数

    with st.spinner("検索中..."):
        results = cached_search(addr_norm, 徒歩上限分, max_candidates)

    if not results:
        st.warning("徒歩圏内の駅が見つかりませんでした。")
        st.stop()

    results = dedupe_and_sort(results)[:表示件数]

    st.success(f"{len(results)}件表示（徒歩{徒歩上限分}分以内）")

    st.subheader("結果（見やすい表示）")
    for r in results:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 4, 2])
            c1.markdown(f"### {station_label(r)}")
            c2.write(safe_lines(getattr(r, "lines", None), sep=" / "))
            c3.metric("徒歩", f"{int(r.walk_minutes)} 分")

    st.subheader("コピペ用")
    text_lines = "\n".join([format_copy_block(r) for r in results])
    st.text_area("そのまま貼れます", value=text_lines, height=220)
    st.download_button(
        label="テキストでダウンロード（.txt）",
        data=text_lines.encode("utf-8"),
        file_name="stations.txt",
        mime="text/plain",
)
    with st.expander("補足（計算方法・注意点）"):
        st.write("・徒歩分数は「直線距離 ÷ 80m/分」を切り上げで計算しています。")
        st.write("・信号や道路形状などは反映されません。実際の徒歩時間とは差が出る場合があります。")
        

