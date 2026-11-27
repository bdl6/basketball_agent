from video_engine.media import inspect_video

def test_fallback_frame_rate_is_the_rate_given_to_encoder(tmp_path, monkeypatch):
    import video_engine.media as media
    source = tmp_path / 'video.mp4'; source.touch()
    monkeypatch.setattr(media, 'probe', lambda _: {'streams':[{'codec_type':'video','avg_frame_rate':'0/0',
        'r_frame_rate':'25/1','duration':'2','width':320,'height':240}], 'format':{}})
    meta = inspect_video(source)
    assert meta['fps'] == 25
    assert meta['fps_text'] == '25/1'
