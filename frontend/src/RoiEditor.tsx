import { useRef, useState } from 'react';
import type { Rectangle, RoiState } from './api';

export function sourcePoint(x:number,y:number,rect:{left:number;top:number;width:number;height:number},width:number,height:number) {
  const scale = Math.min(rect.width/width,rect.height/height);
  const left = rect.left+(rect.width-width*scale)/2;
  const top = rect.top+(rect.height-height*scale)/2;
  return {x:Math.round(Math.max(0,Math.min(width,(x-left)/scale))),y:Math.round(Math.max(0,Math.min(height,(y-top)/scale)))};
}

export function RoiEditor({src,value,disabled,onConfirm}:{src:string;value:RoiState;disabled:boolean;onConfirm:(roi:Rectangle,net:Rectangle)=>void}) {
  const [roi,setRoi] = useState<Rectangle|null>(value.roi);
  const [net,setNet] = useState<Rectangle|null>(value.net_roi);
  const [mode,setMode] = useState<'roi'|'net'>('roi');
  const [editing,setEditing] = useState(!value.confirmed);
  const [ready,setReady] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const start = useRef<{x:number;y:number}|null>(null);
  const update = (box:Rectangle) => mode==='roi'?setRoi(box):setNet(box);
  const valid = (box:Rectangle|null) => box && [box.x1,box.y1,box.x2,box.y2].every(Number.isFinite) && box.x1>=0 && box.y1>=0 && box.x2>box.x1 && box.y2>box.y1 && box.x2<=value.width && box.y2<=value.height;
  const inside = roi && net && roi.x1<=net.x1 && roi.y1<=net.y1 && roi.x2>=net.x2 && roi.y2>=net.y2;
  const enough = roi && roi.x2-roi.x1>=Math.max(64,value.width*.08) && roi.y2-roi.y1>=Math.max(96,value.height*.12);
  const enabled = editing && !disabled;
  return <article className='roi-editor result' aria-label='确认识别区域'>
    <h3>{value.confirmed?'识别区域':'先确认两个识别区域'}</h3>
    <p>蓝框：投篮分析区，覆盖投篮、球的飞行和篮筐。橙框：篮网区域，紧贴白色篮网。先暂停视频，再选择区域并在画面上拖动框选。</p>
    {value.warning && <p>{value.warning}</p>}
    <div className='roi-preview' style={{aspectRatio:`${value.width}/${value.height}`}}>
      <video ref={video} src={src} preload='metadata' playsInline aria-label='区域设置视频'
        onLoadedMetadata={()=>{setReady(true);if(video.current) video.current.currentTime=value.preview_time_seconds || 0;}} />
      <svg viewBox={`0 0 ${value.width} ${value.height}`} aria-label='区域框选画布' role='img'
        style={{pointerEvents:enabled&&ready?'auto':'none'}}
        onPointerDown={e=>{
          if(e.button!==0 || !enabled || !ready) return;
          video.current?.pause();
          start.current=sourcePoint(e.clientX,e.clientY,e.currentTarget.getBoundingClientRect(),value.width,value.height);
          e.currentTarget.setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={e=>{
          if(!start.current || !enabled) return;
          const p=sourcePoint(e.clientX,e.clientY,e.currentTarget.getBoundingClientRect(),value.width,value.height);
          update({x1:Math.min(start.current.x,p.x),y1:Math.min(start.current.y,p.y),x2:Math.max(start.current.x,p.x),y2:Math.max(start.current.y,p.y)});
        }} onPointerUp={()=>{start.current=null;}} onPointerCancel={()=>{start.current=null;}}>
        {[{box:roi,color:'#6bbcff',label:'投篮分析区'},{box:net,color:'#ffaf60',label:'篮网区域'}].map(({box,color,label})=>box&&<g key={label}>
          <rect x={box.x1} y={box.y1} width={Math.max(0,box.x2-box.x1)} height={Math.max(0,box.y2-box.y1)} fill={color+'20'} stroke={color} strokeWidth='3' vectorEffect='non-scaling-stroke'/>
          <text x={box.x1+6} y={Math.max(22,box.y1+22)} fill={color} fontSize={Math.max(16,value.width/48)}>{label}</text>
        </g>)}
      </svg>
    </div>
    <div className='roi-controls'>
      <button type='button' disabled={!ready || disabled} onClick={()=>{const v=video.current;if(v){if(v.paused) void v.play().catch(()=>{});else v.pause();}}}>播放 / 暂停</button>
      <label>预览时间<input aria-label='预览时间' type='range' min='0' max={Math.max(0,value.duration_seconds-.1)} step='.1' defaultValue={value.preview_time_seconds||0} disabled={!ready || disabled}
        onChange={e=>{if(video.current){video.current.pause();video.current.currentTime=Number(e.target.value);}}}/></label>
    </div>
    {!editing?<button type='button' disabled={disabled} onClick={()=>setEditing(true)}>修改区域并重新识别</button>:<>
      <div className='roi-controls' role='group' aria-label='选择框选区域'>
        <button type='button' disabled={disabled} aria-pressed={mode==='roi'} onClick={()=>setMode('roi')}>框选投篮分析区</button>
        <button type='button' disabled={disabled} aria-pressed={mode==='net'} onClick={()=>setMode('net')}>框选篮网区域</button>
      </div>
      <div className='roi-coordinates'>
        {([{name:'投篮分析区',box:roi,set:setRoi},{name:'篮网区域',box:net,set:setNet}]).map(({name,box,set})=><fieldset key={name} disabled={disabled}>
          <legend>{name} · 原视频像素</legend>
          {(['x1','y1','x2','y2'] as const).map(key=><label key={key}>{key}<input type='number' aria-label={`${name} ${key}`} min='0' max={key.startsWith('x')?value.width:value.height}
            value={box?.[key]??''} onChange={e=>set({...box||{x1:0,y1:0,x2:0,y2:0},[key]:Number(e.target.value)})}/></label>)}
        </fieldset>)}
      </div>
      {(!valid(roi)||!valid(net)||!inside||!enough)&&<p>请设置足够大的投篮分析区，并在其中框选篮网区域。</p>}
      <button type='button' className='send' disabled={disabled||!valid(roi)||!valid(net)||!inside||!enough} onClick={()=>onConfirm(roi!,net!)}>确认区域并开始识别</button>
      {value.confirmed&&<p>重新确认后，旧候选和旧集锦会被清空，并按新区域重新识别。</p>}
    </>}
  </article>;
}
