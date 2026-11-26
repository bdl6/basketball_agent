"""Analysis-only detector adapter and source-video highlight export."""
from .analyzer import analyze_video
from .highlights import render_highlights

__all__ = ['analyze_video', 'render_highlights']
