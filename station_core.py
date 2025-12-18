# station_core.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

# 無料API（APIキー不要）
GEO_API_URL = "https://geoapi.heartrails.com/api/json"
EXPRESS_API_URL = "https://express.heartrails.com/api/json"
REQUEST_TIMEOUT_SEC = 10

WALK_METERS_PER_MIN = 80  # 徒歩1分=80m（簡易換算）

# 全角数字・全角ハイフン類を半角へ寄せる
_ZEN2HAN = str.maketrans(
    {
        ord("０"): "0",
        ord("１"): "1",
        ord("２"): "2",
        ord("３"): "3",
        ord("４"): "4",
        ord("５"): "5",
        ord("６"): "6",
        ord("７"): "7",
        ord("８"): "8",
        ord("９"): "9",
        ord("－"): "-",
        ord("ー"): "-",
        ord("−"): "-",
        ord("‐"): "-",
        ord("-"): "-",
        ord("–"): "-",
        ord("—"): "-",
        ord("―"): "-",
    }
)

# =========================
# 路線名の全国向け 表示正規化
# =========================

# 1) 最終上書き（例外対応：ここに追加していけば確実に直る）
LINE_NAME_OVERRIDES: Dict[str, str] = {
    # 仙台（例）
    "仙台市南北線": "仙台市地下鉄南北線",
    "仙台市東西線": "仙台市地下鉄東西線",

    # 東京メトロ（例外的な入り方があればここで吸収）
    "東京地下鉄銀座線": "東京メトロ銀座線",
    "東京地下鉄丸ノ内線": "東京メトロ丸ノ内線",
    "東京地下鉄日比谷線": "東京メトロ日比谷線",
    "東京地下鉄東西線": "東京メトロ東西線",
    "東京地下鉄千代田線": "東京メトロ千代田線",
    "東京地下鉄有楽町線": "東京メトロ有楽町線",
    "東京地下鉄半蔵門線": "東京メトロ半蔵門線",
    "東京地下鉄南北線": "東京メトロ南北線",
    "東京地下鉄副都心線": "東京メトロ副都心線",

    # りんかい線
    "東京臨海高速鉄道りんかい線": "りんかい線",

    # ゆりかもめ
    "ゆりかもめ東京臨海新交通臨海線": "ゆりかもめ",
    "東京臨海新交通臨海線": "ゆりかもめ",
}

# 2) 「◯◯市◯◯線」系を地下鉄表記に寄せる（市営地下鉄のある都市だけ）
CITY_SUBWAY_PREFIX: Dict[str, str] = {
    "札幌市": "札幌市営地下鉄",
    "仙台市": "仙台市地下鉄",
    "横浜市": "横浜市営地下鉄",
    "名古屋市": "名古屋市営地下鉄",
    "京都市": "京都市営地下鉄",
    "神戸市": "神戸市営地下鉄",
    "福岡市": "福岡市地下鉄",
    # 大阪は表記が揺れやすいので、社内で好みを固定
    "大阪市": "Osaka Metro",  # もしくは "大阪メトロ"
}

# 3) 事業者名・通称のよくある表記ゆれ（全国共通）
# ※ ここは「確度が高い」ものだけに絞るのが安全（誤変換を避けるため）
COMMON_REPLACES: Dict[str, str] = {
    "ＪＲ": "JR",
    "ＪＲ東日本": "JR東日本",
    "ＪＲ西日本": "JR西日本",
    "ＪＲ東海": "JR東海",
    "ＪＲ九州": "JR九州",
    "ＪＲ北海道": "JR北海道",
    "ＪＲ四国": "JR四国",
    "東京地下鉄": "東京メトロ",
    "都営地下鉄": "都営",          # 「都営○○線」に寄せる
    "東京都交通局": "都営",          # 同上
    "大阪市高速電気軌道": "Osaka Metro",
    "名古屋鉄道": "名鉄",
    "近畿日本鉄道": "近鉄",
    "京浜急行電鉄": "京急",
    "小田急電鉄": "小田急",
    "東武鉄道": "東武",
    "西武鉄道": "西武",
    "京王電鉄": "京王",
    "相模鉄道": "相鉄",
    "東京急行電鉄": "東急",
    "東急電鉄": "東急",
    "京成電鉄": "京成",
    "南海電気鉄道": "南海",
    "阪急電鉄": "阪急",
    "阪神電気鉄道": "阪神",
    "西日本鉄道": "西鉄",
    "大阪高速鉄道": "大阪モノレール",
}

# 4) 路線名だけで出てくる“よく出る系”を、通称・短い表示に寄せる
# 例：東京臨海高速鉄道りんかい線 → りんかい線
POPULAR_LINE_ALIASES: Dict[str, str] = {
    "りんかい線": "りんかい線",
    "東京臨海高速鉄道りんかい線": "りんかい線",
    "ゆりかもめ": "ゆりかもめ",
    "ゆりかもめ東京臨海新交通臨海線": "ゆりかもめ",
    "東京臨海新交通臨海線": "ゆりかもめ",
    "日暮里・舎人ライナー": "日暮里・舎人ライナー",
    "東京モノレール": "東京モノレール",
    "大阪モノレール": "大阪モノレール",
}

# 5) 都営/メトロ/市営地下鉄の“線”表記を整えるためのパターン
# 例：「都営浅草線」「東京メトロ銀座線」「横浜市営地下鉄ブルーライン」など
_TOEI_LINE_RE = re.compile(r"^(都営)(.+線)$")
_METRO_LINE_RE = re.compile(r"^(東京メトロ)(.+線)$")
_SUBWAY_LINE_RE = re.compile(r"^(?P<prefix>.+地下鉄)(?P<rest>.+線)$")


def normalize_text(s: str) -> str:
    return (s or "").strip().translate(_ZEN2HAN)


def normalize_line_name(line: str) -> str:
    """
    HeartRails Express が返す路線名の「見た目」を全国向けに整える。

    やっていること：
      1) 全角/半角・空白の整理
      2) 代表的な事業者名の置換（JR/近鉄/名鉄/都営/東京メトロなど）
      3) 市営地下鉄っぽい '◯◯市◯◯線' を '◯◯市(営)地下鉄◯◯線' に寄せる（対象都市のみ）
      4) “よく出る系”の通称寄せ（ゆりかもめ/りんかい線 など）
      5) 最後に overrides で確定補正
    """
    if not line:
        return ""

    s = normalize_text(line)

    # 余計な空白を整理
    s = re.sub(r"\s+", " ", s).strip()

    # まず「確度の高い」置換
    for src, dst in COMMON_REPLACES.items():
        s = s.replace(src, dst)

    # 「◯◯市◯◯線」→「◯◯市(営)地下鉄◯◯線」寄せ（対象都市のみ）
    # 例: 仙台市南北線 → 仙台市地下鉄南北線
    m_city = re.match(r"^(?P<city>.+?市)(?P<rest>.+線)$", s)
    if m_city:
        city = m_city.group("city")
        rest = m_city.group("rest")
        if "地下鉄" not in s and city in CITY_SUBWAY_PREFIX:
            s = f"{CITY_SUBWAY_PREFIX[city]}{rest}"

    # 「都営」表記を整える（都営 + ○○線 に統一）
    m_toei = _TOEI_LINE_RE.match(s)
    if m_toei:
        s = f"都営{m_toei.group(2)}"

    # 「東京メトロ」表記を整える（東京メトロ + ○○線）
    m_metro = _METRO_LINE_RE.match(s)
    if m_metro:
        s = f"東京メトロ{m_metro.group(2)}"

    # 「○○地下鉄○○線」系の空白などを整える
    m_subway = _SUBWAY_LINE_RE.match(s)
    if m_subway:
        s = f"{m_subway.group('prefix')}{m_subway.group('rest')}"

    # “よく出る系”は通称寄せ（完全一致で安全に）
    s = POPULAR_LINE_ALIASES.get(s, s)

    # 最終上書き（例外吸収）
    s = LINE_NAME_OVERRIDES.get(s, s)

    return s


@dataclass
class StationResult:
    station_name: str
    lines: List[str]
    walk_minutes: int
    distance_m: int

    def format(self) -> str:
        name = self.station_name
        if not name.endswith("駅"):
            name += "駅"
        lines_str = "/".join(self.lines) if self.lines else "不明"
        return f"{name}({lines_str}) 徒歩{self.walk_minutes}分"


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def extract_postal_code7(address: str) -> Optional[str]:
    """
    住所文字列から郵便番号7桁を抽出して返す
    例: '〒980－0021仙台...' -> '9800021'
    """
    s = normalize_text(address)
    m = re.search(r"〒?\s*(\d{3})\s*[-]?\s*(\d{4})", s)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}"


def parse_distance_to_meters(distance_value: Any) -> float:
    """
    Express APIの distance は '320m' / '2.6km' / 320 / '320' などがあり得るので meters(float) に統一
    """
    if distance_value is None:
        return float("inf")

    if isinstance(distance_value, (int, float)):
        return float(distance_value)

    s = normalize_text(str(distance_value)).replace(",", "")
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(km|m)?$", s)
    if not m:
        return float("inf")

    val = float(m.group(1))
    unit = m.group(2) or "m"
    if unit == "km":
        return val * 1000.0
    return val


def geo_search_by_postal(postal7: str) -> List[Dict[str, Any]]:
    r = requests.get(
        GEO_API_URL,
        params={"method": "searchByPostal", "postal": postal7},
        timeout=REQUEST_TIMEOUT_SEC,
    )
    r.raise_for_status()
    data = r.json()
    return _as_list(data.get("response", {}).get("location"))


def geo_suggest(keyword: str, matching: str = "like") -> List[Dict[str, Any]]:
    r = requests.get(
        GEO_API_URL,
        params={"method": "suggest", "matching": matching, "keyword": keyword},
        timeout=REQUEST_TIMEOUT_SEC,
    )
    r.raise_for_status()
    data = r.json()
    return _as_list(data.get("response", {}).get("location"))


def pick_best_location(locations: List[Dict[str, Any]], raw_address: str) -> Dict[str, Any]:
    """
    候補が複数ある場合、住所に含まれる prefecture/city/town でスコアリングして一つ選ぶ
    """
    addr = normalize_text(raw_address)

    def score(loc: Dict[str, Any]) -> Tuple[int, int]:
        s = 0
        for k in ("prefecture", "city", "town"):
            v = loc.get(k)
            if v and normalize_text(v) in addr:
                s += 1
        postal_bonus = 1 if loc.get("postal") else 0
        text_len = sum(len(str(loc.get(k, ""))) for k in ("prefecture", "city", "town"))
        return (s + postal_bonus, text_len)

    return max(locations, key=score)


def geocode_address_to_xy(raw_address: str) -> Tuple[float, float]:
    """
    住所 -> (x=経度, y=緯度)
    優先順位:
      1) 郵便番号が取れれば searchByPostal（安定）
      2) 取れなければ suggest(like)（町域レベルになりやすい）
    """
    postal7 = extract_postal_code7(raw_address)
    if postal7:
        locs = geo_search_by_postal(postal7)
        if locs:
            best = pick_best_location(locs, raw_address)
            return float(best["x"]), float(best["y"])

    addr = normalize_text(raw_address)
    addr = re.sub(r"〒?\s*\d{3}[-]?\d{4}", "", addr)  # 郵便番号除去
    addr_no_digits = re.sub(r"[0-9\-]+.*$", "", addr)
    addr_no_chome = re.sub(r"[一二三四五六七八九十〇零0-9]+丁目.*$", "", addr)

    for kw in [addr_no_digits, addr_no_chome, addr]:
        kw = kw.strip()
        if len(kw) < 2:
            continue
        locs = geo_suggest(kw, matching="like")
        if locs:
            best = pick_best_location(locs, raw_address)
            return float(best["x"]), float(best["y"])

    raise ValueError("住所から緯度経度を取得できませんでした（郵便番号7桁付きで試すと改善します）。")


def express_get_near_stations(x_lng: float, y_lat: float) -> List[Dict[str, Any]]:
    r = requests.get(
        EXPRESS_API_URL,
        params={"method": "getStations", "x": x_lng, "y": y_lat},
        timeout=REQUEST_TIMEOUT_SEC,
    )
    r.raise_for_status()
    data = r.json()
    return _as_list(data.get("response", {}).get("station"))


def find_walkable_stations(
    raw_address: str,
    max_walk_min: int = 30,
    max_candidates: int = 3,
) -> List[StationResult]:
    """
    住所を入力として、徒歩max_walk_min圏内の駅（最大max_candidates件）を返す
    - 距離はAPIが返す直線距離（m/km）を利用
    - 徒歩分数は ceil(distance_m / 80)
    - 同名駅が路線ごとに重複するので駅名でまとめ、路線を / 連結できる形にする
    - 路線名は normalize_line_name() で全国向けに表記を整える
    """
    if not raw_address or not raw_address.strip():
        raise ValueError("住所が空です。")

    if max_walk_min <= 0:
        raise ValueError("徒歩上限は1以上を指定してください。")

    if max_candidates <= 0:
        raise ValueError("表示件数は1以上を指定してください。")

    x, y = geocode_address_to_xy(raw_address)
    stations_raw = express_get_near_stations(x, y)

    limit_m = max_walk_min * WALK_METERS_PER_MIN

    # (駅名, 都道府県)でまとめて路線を結合（同名駅の別県を分けるため）
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for st in stations_raw:
        name = st.get("name")
        pref = st.get("prefecture", "")
        line = normalize_line_name(st.get("line"))
        dist_m = parse_distance_to_meters(st.get("distance"))

        if not name or not line or not math.isfinite(dist_m):
            continue

        key = (str(name), str(pref))
        if key not in grouped:
            grouped[key] = {"name": str(name), "pref": str(pref), "lines": set(), "min_dist": dist_m}

        grouped[key]["lines"].add(str(line))
        grouped[key]["min_dist"] = min(grouped[key]["min_dist"], dist_m)

    results: List[StationResult] = []
    for g in grouped.values():
        d = int(round(g["min_dist"]))
        if d <= limit_m:
            walk_min = int(math.ceil(d / WALK_METERS_PER_MIN))
            results.append(
                StationResult(
                    station_name=g["name"],
                    lines=sorted(list(g["lines"])),
                    walk_minutes=walk_min,
                    distance_m=d,
                )
            )

    results.sort(key=lambda r: (r.walk_minutes, r.distance_m, r.station_name))
    return results[:max_candidates]
