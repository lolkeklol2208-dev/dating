// Semi-implicit spring integration, with bounded substeps for slow devices.
export function springStep(position, velocity, target, elapsed){
 const steps=Math.max(1,Math.ceil(Math.min(elapsed,.05)/.008));
 const dt=Math.min(elapsed,.05)/steps;
 for(let i=0;i<steps;i++){velocity+=(-185*(position-target)-24*velocity)*dt;position+=velocity*dt;}
 return [position,velocity];
}
export function spring(from,to,render,complete=()=>{}){
 if(matchMedia('(prefers-reduced-motion: reduce)').matches){render(to);complete();return ()=>{};}
 let x=from,v=0,last=performance.now(),cancelled=false,frame;
 function tick(now){if(cancelled)return;[x,v]=springStep(x,v,to,(now-last)/1000);last=now;render(x);
  if(Math.abs(x-to)<.3&&Math.abs(v)<.3){render(to);complete();return;}frame=requestAnimationFrame(tick);}
 frame=requestAnimationFrame(tick);return ()=>{cancelled=true;cancelAnimationFrame(frame);};
}
