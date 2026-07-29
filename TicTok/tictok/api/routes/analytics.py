"""全体解析のroute。集計そのものは ``tictok.analytics`` にあり、ここは窓(日数)を渡すだけ。"""

import asyncio
import time
from fastapi import HTTPException
from tictok import analytics
from fastapi import APIRouter
from tictok.api import runtime

router = APIRouter()


def _analytics_since(days: int) -> float:
    """期間フィルタ(直近days日)をstarted_atの下限epochへ。0以下は全期間。"""
    return (time.time() - days * 86400) if days and days > 0 else 0.0


ANALYTICS_INDEX_METRICS = {"joins", "comments", "diamonds", "likes", "follows"}


@router.get("/api/analytics/summary")
async def analytics_summary(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_summary, _analytics_since(days))


@router.get("/api/analytics/time-index")
async def analytics_time_index(metric: str = "joins", days: int = 0) -> dict:
    if metric not in ANALYTICS_INDEX_METRICS:
        raise HTTPException(status_code=422, detail=f"未対応の指標です: {metric}")
    return await asyncio.to_thread(runtime.storage.analytics_time_index, metric, _analytics_since(days))


@router.get("/api/analytics/relations")
async def analytics_relations(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_relations, _analytics_since(days))


@router.get("/api/analytics/battle-uplift")
async def analytics_battle_uplift(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_battle_uplift, _analytics_since(days))


@router.get("/api/analytics/share-uplift")
async def analytics_share_uplift(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_share_uplift, _analytics_since(days))


@router.get("/api/analytics/glove-crit-rate")
async def analytics_glove_crit_rate(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_glove_crit_rate, _analytics_since(days))


@router.get("/api/analytics/join-quality")
async def analytics_join_quality(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_join_quality, _analytics_since(days))


@router.get("/api/analytics/scale-efficiency")
async def analytics_scale_efficiency(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_scale_efficiency, _analytics_since(days))


@router.get("/api/analytics/retention")
async def analytics_retention(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_retention, _analytics_since(days))


@router.get("/api/analytics/concentration")
async def analytics_concentration(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_concentration, _analytics_since(days))


@router.get("/api/analytics/join-context")
async def analytics_join_context(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_join_context, _analytics_since(days))


@router.get("/api/analytics/battle-flow")
async def analytics_battle_flow(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_battle_flow, _analytics_since(days))


@router.get("/api/analytics/coverage")
async def analytics_coverage(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_coverage, _analytics_since(days))


@router.get("/api/analytics/entry-source")
async def analytics_entry_source(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_entry_source, _analytics_since(days))


def _analytics_gift_sku(since: float) -> dict:
    """ギフトSKU構成。reduceに要るのはsession単位payloadだけで、storage側から追加で
    引くものが無いため(gloveの単価表のような横断queryが不要)、ここで組み立てる。"""
    return analytics.reduce_gift_sku(runtime.storage._analytics_rows("gift_sku", since))


@router.get("/api/analytics/gift-sku")
async def analytics_gift_sku(days: int = 0) -> dict:
    """コインがどの価格帯のギフトから来ているか、帯ごとの反復購入率、battle内外の構成差。"""
    return await asyncio.to_thread(_analytics_gift_sku, _analytics_since(days))


def _analytics_dwell(since: float) -> dict:
    """滞在時間(Little則 W=L/λ)。収集中sessionの未flush分は_analytics_rowsが確定させる。"""
    return analytics.reduce_dwell(runtime.storage._analytics_rows("dwell", since))


@router.get("/api/analytics/dwell")
async def analytics_dwell(days: int = 0) -> dict:
    """視聴者1人あたりの平均滞在時間と入れ替わり率。同一配信者内の相対比較にのみ使える。"""
    return await asyncio.to_thread(_analytics_dwell, _analytics_since(days))


def _analytics_anomaly(since: float) -> dict:
    """配信の異常検知(session間の水準比較 + session内の水準shift)。"""
    return analytics.reduce_anomaly(runtime.storage._analytics_rows("anomaly", since))


@router.get("/api/analytics/anomaly")
async def analytics_anomaly(days: int = 0) -> dict:
    """その配信者自身の過去分布に対する逸脱。同一配信者内の相対比較のみ。"""
    return await asyncio.to_thread(_analytics_anomaly, _analytics_since(days))


def _analytics_activation(since: float) -> dict:
    """入室後の初回反応までの時間(Kaplan-Meier)と素通り率。"""
    return analytics.reduce_activation(runtime.storage._analytics_rows("activation", since))


@router.get("/api/analytics/activation")
async def analytics_activation(days: int = 0) -> dict:
    """入室→初回反応のfunnel。母集団は入室eventが記録された人に限られる。"""
    return await asyncio.to_thread(_analytics_activation, _analytics_since(days))


@router.get("/api/analytics/organic-entries")
async def analytics_organic_entries(days: int = 0) -> dict:
    return await asyncio.to_thread(runtime.storage.analytics_organic_entries, _analytics_since(days))
