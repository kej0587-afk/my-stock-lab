import numpy as np
import pandas as pd


def bars():
    close = np.linspace(100, 110, 80)
    return pd.DataFrame({"Open": close - .5, "High": close + 1, "Low": close - 1,
                         "Close": close, "Volume": np.arange(80) + 100},
                        index=pd.date_range("2026-06-01", periods=80, freq="B"))


def test_precision_chart_volume_has_a_separate_axis(app_module, monkeypatch):
    captured = []
    monkeypatch.setattr(app_module.st, "plotly_chart", lambda fig, **kwargs: captured.append(fig))
    monkeypatch.setattr(app_module.st, "caption", lambda *args, **kwargs: None)
    app_module.render_precision_candlestick_chart(bars(), show_patterns=False, show_liquidity=False, show_smc=False)
    fig = captured[0]
    assert fig.data[0].type == "candlestick"
    assert next(trace for trace in fig.data if trace.type == "bar").yaxis == "y2"
    assert fig.layout.yaxis.domain[0] > fig.layout.yaxis2.domain[1]


def test_app_profile_conserves_volume_and_does_not_fabricate_it(app_module):
    frame = bars()
    profile = app_module.build_liquidity_thermal_profile(frame)
    assert profile["ok"]
    assert np.isclose(sum(row["volume"] for row in profile["rows"]), frame["Volume"].sum())
    assert not app_module.build_liquidity_thermal_profile(frame.drop(columns="Volume"))["ok"]
