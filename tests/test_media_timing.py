import subprocess
import numpy as np
import pytest
from basketball_detect.pipeline import AnalysisResult
from basketball_detect.render import render_video
from basketball_detect.media import inspect_video, probe


def test_fallback_frame_rate_is_the_rate_given_to_encoder(tmp_path, monkeypatch):
    import basketball_detect.media as media
    source = tmp_path / 'video.mp4'; source.touch()
    monkeypatch.setattr(media, 'probe', lambda _: {'streams':[{'codec_type':'video','avg_frame_rate':'0/0',
        'r_frame_rate':'25/1','duration':'2','width':320,'height':240}], 'format':{}})
    meta = inspect_video(source)
    assert meta['fps'] == 25
    assert meta['fps_text'] == '25/1'


@pytest.mark.parametrize('video_offset,audio_offset', [(1,0),(0,1)])
def test_export_rebases_audio_against_first_video_frame(tmp_path, video_offset, audio_offset):
    source = tmp_path / 'offset.mp4'
    cmd=['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=gray:s=320x240:r=25:d=2',
         '-f','lavfi','-i',r'aevalsrc=sin(2*PI*if(lt(t\,1)\,440\,880)*t):s=8000:d=3',
         '-vf',f'setpts=PTS+{video_offset}/TB','-af',f'asetpts=PTS+{audio_offset}/TB',
         '-fps_mode','passthrough','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)]
    subprocess.run(cmd,check=True,capture_output=True)
    dest=tmp_path/'annotated.mp4'
    render_video(source,AnalysisResult(),dest)
    decoded=subprocess.run(['ffmpeg','-v','error','-i',str(dest),'-map','0:a:0','-f','f32le','-ac','1','-ar','8000','pipe:1'],
                           check=True,capture_output=True).stdout
    samples=np.frombuffer(decoded,dtype='<f4')
    if video_offset:
        part=samples[1600:5600]
        hz=np.fft.rfftfreq(len(part),1/8000)[np.argmax(abs(np.fft.rfft(part)))]
        assert hz == pytest.approx(880,abs=10)
    else:
        assert np.sqrt(np.mean(samples[800:4000]**2)) < .01
        assert np.sqrt(np.mean(samples[9600:12000]**2)) > .1
