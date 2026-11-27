"""Create independent, task-private candidate MP4s in the serial worker."""
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from contracts.models import Event, EditPlan
from video_engine.highlights import render_highlights


def public_clips(state):
    return {key:{k:v for k,v in item.items() if k!='path'}
            for key,item in state.get('candidate_clips',{}).items()}


def prepare_candidates(store,jid,state,video,on_progress):
    candidates=[e for e in state['events'] or [] if e['label']!='missed']
    clips=state.setdefault('candidate_clips',{})
    for index,raw in enumerate(candidates,1):
        on_progress({'status':'rendering','message':f'正在生成候选短视频 {index}/{len(candidates)}'})
        key=hashlib.sha256(f"v1:{raw['id']}:{raw['time']}".encode()).hexdigest()[:20]
        output=store.tasks/jid/'candidates'/f'{key}.mp4'
        try:
            if not output.is_file():
                event=Event.model_validate(raw)
                event=event.model_copy(update={'evidence':{**event.evidence,'user_selected':True}})
                render_highlights(video,[event],EditPlan(),output)
            clips[raw['id']]={'status':'ready','url':f'/api/jobs/{jid}/candidates/{quote(raw["id"],safe="")}',
                'path':str(output.resolve()),'start':max(0,raw['time']-5),'anchor':raw['time']}
            text=f'候选 {index} 的独立短视频已生成，可以播放并选择是否保留。'
        except (ValueError,RuntimeError,OSError):
            clips[raw['id']]={'status':'failed','error':'候选短视频生成失败，请重试'}
            text=f'候选 {index} 的短视频生成失败，可以重试生成候选。'
        with store.connect() as db:
            db.execute('UPDATE jobs SET state=? WHERE id=?',(json.dumps(state,ensure_ascii=False),jid))
            store.message(db,jid,'status',text)
