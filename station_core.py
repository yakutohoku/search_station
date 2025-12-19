# station_core.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

# 無料API（APIキー不要）
GEO_API_URL = "https://geoapi.heartrails.com/api/json"
EXPRESS_API_URL = "https://express.heartrails.com/api/json"

REQUEST_TIMEOUT_SEC = 10

# 外部APIは不安定になり得るので軽いリトライを入れる
API_RETRY_COUNT = 2  # 追加リトライ回数（合計試行は 1 + API_RETRY_COUNT）
API_RETRY_BACKOFF_SEC = 0.6  # 初回待機秒（指数バックオフ）

WALK_METERS_PER_MIN = 80  # 徒歩1分=80m（簡易換算）

_SESSION = requests.Session()
_DEFAULT_HEADERS = {"User-Agent": "station-core/1.0"}

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
    "仙台市南北線": "地下鉄南北線",
    "仙台市東西線": "地下鉄東西線",

    # りんかい線
    "東京臨海高速鉄道りんかい線": "りんかい線",

    # ゆりかもめ
    "ゆりかもめ東京臨海新交通臨海線": "ゆりかもめ",
    "東京臨海新交通臨海線": "ゆりかもめ",
}

# 2) 「◯◯市◯◯線」系の“市名つき地下鉄”をやめて、基本は「地下鉄◯◯線」に寄せる
#    ※大阪だけは社内表記で「大阪メトロ」に固定
CITY_SUBWAY_PREFIX: Dict[str, str] = {
    "札幌市": "地下鉄",
    "仙台市": "地下鉄",
    "横浜市": "地下鉄",
    "名古屋市": "地下鉄",
    "京都市": "地下鉄",
    "神戸市": "地下鉄",
    "福岡市": "地下鉄",
    "大阪市": "大阪メトロ",
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
    "都営地下鉄": "都営",  # 「都営○○線」に寄せる
    "東京都交通局": "都営",  # 同上
    "大阪市高速電気軌道": "大阪メトロ",
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
_TOEI_LINE_RE = re.compile(r"^(都営)(.+線)$")
_METRO_LINE_RE = re.compile(r"^(東京メトロ)(.+線)$")
_SUBWAY_LINE_RE = re.compile(r"^(?P<prefix>.+地下鉄)(?P<rest>.+線)$")

# 6) 「〇〇市(営)地下鉄～～」を「地下鉄～～」に落とす（市名を出さない）
_CITY_SUBWAY_STRIP_RE = re.compile(r"^(?P<city>.+?市)(?:営)?地下鉄\s*(?P<rest>.+)$")


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _get_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    外部API呼び出しは一時的な失敗が起き得るので、
    - 軽いリトライ
    - JSONパース確認
    - API側 error フィールド検知
    をまとめて行う。
    """
    last_exc: Optional[BaseException] = None
    total_attempts = 1 + API_RETRY_COUNT

    for attempt in range(1, total_attempts + 1):
        try:
            r = _SESSION.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT_SEC,
                headers=_DEFAULT_HEADERS,
            )
            r.raise_for_status()

            try:
                data = r.json()
            except ValueError as e:
                raise ValueError(f"API応答がJSONではありません: {url}") from e

            if isinstance(data, dict) and data.get("error"):
                raise ValueError(f"APIエラー: {data.get('error')}")

            if not isinstance(data, dict):
                raise ValueError(f"API応答が想定外の型です: {type(data)}")

            return data

        except (requests.RequestException, ValueError) as e:
            last_exc = e
            if attempt < total_attempts:
                time.sleep(API_RETRY_BACKOFF_SEC * (2 ** (attempt - 1)))
                continue
            raise RuntimeError(f"API呼び出しに失敗しました: {url}") from last_exc

    raise RuntimeError(f"API呼び出しに失敗しました: {url}") from last_exc


def normalize_text(s: str) -> str:
    return (s or "").strip().translate(_ZEN2HAN)


def normalize_line_name(line: str) -> str:
    """
    HeartRails Express が返す路線名の「見た目」を全国向けに整える。

    やっていること：
      1) 全角/半角・空白の整理
      2) 代表的な事業者名の置換（JR/近鉄/名鉄/都営/東京メトロなど）
      3) 市営地下鉄っぽい '◯◯市◯◯線' を '地下鉄◯◯線'（大阪は大阪メトロ）に寄せる（対象都市のみ）
      4) “よく出る系”の通称寄せ（ゆりかもめ/りんかい線 など）
      5) 最後に overrides で確定補正
      6) 仕上げに「〇〇市(営)地下鉄～～」は「地下鉄～～」へ（市名を出さない）
    """
    if not line:
        return ""

    s = normalize_text(line)

    # 余計な空白を整理
    s = re.sub(r"\s+", " ", s).strip()

    # まず「確度の高い」置換
    for src, dst in COMMON_REPLACES.items():
        s = s.replace(src, dst)

    # 「◯◯市◯◯線」→「地下鉄◯◯線」寄せ（対象都市のみ）
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

    # 「〇〇市(営)地下鉄～～」は「地下鉄～～」に統一（市名を出さない）
    # ※「大阪メトロ」は対象外（"地下鉄" を含まないため）
    m_strip = _CITY_SUBWAY_STRIP_RE.match(s)
    if m_strip:
        s = f"地下鉄{m_strip.group('rest')}"

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
    表記ゆれ（全角m/km、空白、カンマなど）も吸収する。
    """
    if distance_value is None:
        return float("inf")

    if isinstance(distance_value, (int, float)):
        return float(distance_value)

    s = normalize_text(str(distance_value)).replace(",", "")
    # 全角の単位ゆれを軽く吸収
    s = s.replace("ｍ", "m").replace("ｋｍ", "km").replace("ＫＭ", "km").replace("Ｋm", "km").replace("㎞", "km")

    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(km|m)?$", s, flags=re.IGNORECASE)
    if not m:
        return float("inf")

    val = float(m.group(1))
    unit = (m.group(2) or "m").lower()
    if unit == "km":
        return val * 1000.0
    return val


def geo_search_by_postal(postal7: str) -> List[Dict[str, Any]]:
    data = _get_json(GEO_API_URL, {"method": "searchByPostal", "postal": postal7})
    return _as_list(data.get("response", {}).get("location"))


def geo_suggest(keyword: str, matching: str = "like") -> List[Dict[str, Any]]:
    data = _get_json(GEO_API_URL, {"method": "suggest", "matching": matching, "keyword": keyword})
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
      2) 取れなければ suggest(exact -> like)（曖昧さを少し下げる）
    """
    postal7 = extract_postal_code7(raw_address)
    if postal7:
        locs = geo_search_by_postal(postal7)
        if locs:
            best = pick_best_location(locs, raw_address)
            try:
                return float(best["x"]), float(best["y"])
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError("郵便番号検索の結果から緯度経度を取得できませんでした。") from e

    addr = normalize_text(raw_address)
    addr = re.sub(r"〒?\s*\d{3}[-]?\d{4}", "", addr)  # 郵便番号除去
    addr_no_digits = re.sub(r"[0-9\-]+.*$", "", addr)
    addr_no_chome = re.sub(r"[一二三四五六七八九十〇零0-9]+丁目.*$", "", addr)

    candidates = [addr_no_digits, addr_no_chome, addr]
    for kw in candidates:
        kw = kw.strip()
        if len(kw) < 2:
            continue

        # まず exact を試し、だめなら like
        for matching in ("exact", "like"):
            locs = geo_suggest(kw, matching=matching)
            if locs:
                best = pick_best_location(locs, raw_address)
                try:
                    return float(best["x"]), float(best["y"])
                except (KeyError, TypeError, ValueError):
                    continue

    raise ValueError("住所から緯度経度を取得できませんでした（郵便番号7桁付きで試すと改善します）。")


def express_get_near_stations(x_lng: float, y_lat: float) -> List[Dict[str, Any]]:
    data = _get_json(EXPRESS_API_URL, {"method": "getStations", "x": x_lng, "y": y_lat})
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
