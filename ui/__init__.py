"""
KIS Auto Trading - UI Package
"""
from ui.styles import apply_custom_styles, render_interactive_stock_chart
from ui.views.dashboard_view import render_dashboard
from ui.views.screening_view import render_screener
from ui.views.backtest_view import render_backtest
from ui.views.settings_view import render_settings
from ui.views.infinite_view import render_infinite

__all__ = [
    "apply_custom_styles",
    "render_interactive_stock_chart",
    "render_dashboard",
    "render_screener",
    "render_backtest",
    "render_settings",
    "render_infinite",
]

