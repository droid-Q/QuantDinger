import pytest

from app.routes.ai_chat import (
    _agent_response_language_name,
    _build_system_prompt,
    _fallback_agent_intent,
    _format_kline_time_utc,
    _normalize_agent_intent,
    _summarize_klines,
)


def test_kline_timestamp_is_exposed_as_readable_utc():
    bars = [
        {
            "time": 1_784_217_600 + index * 3600,
            "open": 100 + index,
            "high": 102 + index,
            "low": 99 + index,
            "close": 101 + index,
            "volume": 1000 + index,
        }
        for index in range(5)
    ]

    summary = _summarize_klines(bars, "1H")

    assert summary["latest_time"] == bars[-1]["time"]
    assert summary["latest_time_utc"].endswith("+00:00")
    assert summary["latest_time_utc"].startswith("2026-")


def test_kline_timestamp_formatter_accepts_milliseconds_and_iso_strings():
    assert _format_kline_time_utc(1_784_217_600_000) == "2026-07-16T16:00:00+00:00"
    assert _format_kline_time_utc("2026-07-16T16:00:00Z") == "2026-07-16T16:00:00+00:00"


def test_agent_response_language_follows_every_ui_locale():
    expected = {
        "ar-SA": "Arabic",
        "de-DE": "German",
        "en-US": "English",
        "fr-FR": "French",
        "ja-JP": "Japanese",
        "ko-KR": "Korean",
        "ru-RU": "Russian",
        "th-TH": "Thai",
        "vi-VN": "Vietnamese",
        "zh-CN": "Simplified Chinese",
        "zh-TW": "Traditional Chinese",
    }

    for locale, language_name in expected.items():
        assert _agent_response_language_name(locale) == language_name
        prompt = _build_system_prompt(locale, {}, "general", False, json_response=False)
        assert f"Reply in {language_name}." in prompt


@pytest.mark.parametrize(
    ("locale", "message"),
    [
        ("ja-JP", "この銘柄のチャートインジケーターを作成してください"),
        ("ko-KR", "이 종목에 실행 가능한 차트 지표를 만들어 주세요"),
        ("de-DE", "Erstelle einen ausführbaren Indikator für dieses Symbol"),
        ("fr-FR", "Crée un indicateur exécutable pour ce symbole"),
        ("ru-RU", "Создай исполняемый индикатор для этого инструмента"),
        ("vi-VN", "Tạo chỉ báo có thể chạy cho mã này"),
        ("th-TH", "สร้างอินดิเคเตอร์ที่ใช้งานได้สำหรับสินทรัพย์นี้"),
        ("ar-SA", "أنشئ مؤشرًا قابلاً للتنفيذ لهذا الرمز"),
    ],
)
def test_agent_fallback_executes_indicator_workflow_in_ui_languages(locale, message):
    plan = _fallback_agent_intent(
        message,
        False,
        {"market": "Crypto", "symbol": "BTC/USDT"},
        locale,
    )

    assert plan["intent"] == "strategy_build"
    assert plan["should_execute"] is True
    assert plan["target_type"] == "indicator"
    assert plan["workflow"] == "indicator_ide"


def test_agent_intent_preserves_strategy_instrument_context():
    context = {
        "market": "Crypto",
        "symbol": "SOL/USDT",
        "timeframe": "4H",
        "exchange_id": "okx",
        "market_type": "swap",
        "instrument_id": "SOL-USDT-SWAP",
    }
    fallback = _fallback_agent_intent(
        "Create a runnable Python strategy",
        False,
        context,
        "en-US",
    )
    normalized = _normalize_agent_intent(
        {
            "intent": "strategy_build",
            "target_type": "script",
            "workflow": "script_strategy",
            "should_execute": True,
            "entities": {},
        },
        "Create a runnable Python strategy",
        False,
        context,
        "en-US",
    )

    for plan in (fallback, normalized):
        assert plan["entities"]["timeframe"] == "4H"
        assert plan["entities"]["exchange_id"] == "okx"
        assert plan["entities"]["market_type"] == "swap"
        assert plan["entities"]["instrument_id"] == "SOL-USDT-SWAP"
