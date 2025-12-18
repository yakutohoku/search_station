# streamlit_app.py
# -*- coding: utf-8 -*-

import streamlit as st
import pandas as pd
from station_core import find_walkable_stations

st.set_page_config(page_title="住所から駅検索（社内）", layout="wide")

st.title("住所から駅を探す（徒歩圏内）")
st.caption("徒歩分は直線距離を「徒歩1分=80m」で換算した目安です（実際の徒歩ルート時間ではありません）。")

# サイドバー：設定
with st.sidebar:
    st.header("検索設定")
    徒歩上限分 = st.slider("徒歩上限（分）", min_value=5, max_value=60, value=30, step=5)
    表示件数 = st.slider("表示件数（最大）", min_value=1, max_value=10, value=3, step=1)

    st.divider()
    st.subheader("入力のコツ")
    st.write("・郵便番号7桁が入っていると精度が上がります。")
    st.write("・例：〒980-0021 仙台市青葉区中央二丁目10-20")

st.subheader("住所を入力")
with st.form("form", clear_on_submit=False):
    住所 = st.text_input(
        "住所（郵便番号7桁付き推奨）",
        value="〒980－0021 仙台市青葉区中央二丁目１０－２０",
        placeholder="例：〒980-0021 仙台市青葉区中央二丁目10-20",
    )
    col1, col2 = st.columns([1, 8])
    検索 = col1.form_submit_button("検索")

@st.cache_data(ttl=60 * 60, show_spinner=False)
def cached_search(addr: str, walk_min: int, n: int):
    return find_walkable_stations(addr, max_walk_min=walk_min, max_candidates=n)

if 検索:
    if not 住所.strip():
        st.error("住所が空です。入力してください。")
        st.stop()

    with st.spinner("検索中..."):
        try:
            results = cached_search(住所, int(徒歩上限分), int(表示件数))
        except Exception as e:
            st.error(f"検索に失敗しました。住所を見直してください。\n\nエラー内容：{e}")
            st.stop()

    if not results:
        st.warning("徒歩圏内の駅が見つかりませんでした。")
        st.stop()

    st.success(f"{len(results)}件見つかりました（徒歩{徒歩上限分}分以内、最大{表示件数}件表示）")

    st.subheader("結果（見やすい表示）")
    for r in results:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 4, 2])
            with c1:
                st.markdown(f"### {r.station_name}駅")
                st.caption("候補駅")
            with c2:
                st.markdown("**路線**")
                st.write(" / ".join(r.lines) if r.lines else "不明")
            with c3:
                st.metric("徒歩", f"{r.walk_minutes} 分")
                st.caption(f"直線距離：約{r.distance_m} m")

    st.subheader("結果（一覧表）")
    df = pd.DataFrame(
        [
            {
                "駅名": f"{r.station_name}駅",
                "路線": " / ".join(r.lines) if r.lines else "不明",
                "徒歩(分)": r.walk_minutes,
                "直線距離(m)": r.distance_m,
                "表示用（コピペ）": r.format(),
            }
            for r in results
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("コピペ用（指定フォーマット）")
    text_lines = "\n".join([r.format() for r in results])
    st.text_area("そのまま貼れます", value=text_lines, height=120)
    st.download_button(
        label="テキストでダウンロード（.txt）",
        data=text_lines.encode("utf-8"),
        file_name="stations.txt",
        mime="text/plain",
    )

    with st.expander("補足（計算方法・注意点）"):
        st.write("・徒歩分数は「直線距離 ÷ 80m/分」を切り上げで計算しています。")
        st.write("・信号や道路形状などは反映されません。実際の徒歩時間とは差が出る場合があります。")
        st.write("・結果は外部APIの返す周辺駅情報に依存します。")
