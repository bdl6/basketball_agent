import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { RoiEditor, sourcePoint } from './RoiEditor';

test('pointer coordinates account for letterboxing and clamp to source', () => {
  const rect = {left:10,top:20,width:500,height:500};
  expect(sourcePoint(260,270,rect,1000,500)).toEqual({x:500,y:250});
  expect(sourcePoint(0,0,rect,1000,500)).toEqual({x:0,y:0});
  expect(sourcePoint(999,999,rect,1000,500)).toEqual({x:1000,y:500});
});

test('requires both regions and submits source pixel coordinates', () => {
  const confirm = vi.fn();
  render(<RoiEditor src='/video' value={{width:1000,height:600,duration_seconds:10,roi:null,net_roi:null,confirmed:false}} disabled={false} onConfirm={confirm}/>);
  expect(screen.getByRole('button',{name:'确认区域并开始识别'})).toBeDisabled();
  for (const [name,value] of [['投篮分析区 x1',0],['投篮分析区 y1',0],['投篮分析区 x2',1000],['投篮分析区 y2',600],['篮网区域 x1',400],['篮网区域 y1',200],['篮网区域 x2',500],['篮网区域 y2',300]] as const)
    fireEvent.change(screen.getByLabelText(name),{target:{value:String(value)}});
  fireEvent.click(screen.getByRole('button',{name:'确认区域并开始识别'}));
  expect(confirm).toHaveBeenCalledWith({x1:0,y1:0,x2:1000,y2:600},{x1:400,y1:200,x2:500,y2:300});
});
