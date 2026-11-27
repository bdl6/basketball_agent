"""Analysis-only detector adapter and source-video highlight export."""
from .upstream import analyze_video
from .highlights import render_highlights

__all__ = ['analyze_video', 'render_highlights']
