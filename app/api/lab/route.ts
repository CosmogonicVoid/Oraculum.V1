import {database,identity,body,json,failure,HttpError} from '../../../lib/server';
import {getChatGPTUser} from '../../chatgpt-auth';
import {freshReplay,applyReplay,snapshot,type ReplayState} from '../../../lib/replay';
export const dynamic='force-dynamic';
async function read(id:string){const r=await database().prepare('SELECT state, revision FROM replay_accounts WHERE user_id=?').bind(id).first<{state:string;revision:number}>();return r?{state:JSON.parse(r.state) as ReplayState,revision:r.revision}:{state:freshReplay(),revision:0};}
export async function GET(req:Request){try{const u=await getChatGPTUser(),r=u?await read(u.userId):{state:freshReplay(),revision:0};return json(snapshot(r.state,r.revision,new URL(req.url).searchParams.get('symbol')||undefined));}catch(e){return failure(e);}}
export async function POST(req:Request){try{
 const u=await identity(),input=await body(req);
 if(typeof input.requestId!=='string'||!/^[-\w]{10,80}$/.test(input.requestId)||!Number.isSafeInteger(input.revision))throw new HttpError(400,'A request ID and portfolio revision are required.');
 await database().prepare('INSERT OR IGNORE INTO replay_accounts(user_id,state,revision) VALUES(?,?,0)').bind(u.userId,JSON.stringify(freshReplay())).run();
 const r=await read(u.userId);
 if(r.state.requests.includes(input.requestId))return json(snapshot(r.state,r.revision,input.selected));
 if(input.revision!==r.revision)throw new HttpError(409,'Your challenge changed in another tab. Reload and try again.');
 let next:ReplayState;try{next=applyReplay(r.state,input);}catch(e){throw new HttpError(400,(e as Error).message);}
 next.requests=[...next.requests,input.requestId].slice(-500);
 const result=await database().prepare('UPDATE replay_accounts SET state=?,revision=revision+1 WHERE user_id=? AND revision=?').bind(JSON.stringify(next),u.userId,r.revision).run();
 if(result.meta.changes!==1)throw new HttpError(409,'Another action completed first. Reload your challenge.');
 return json(snapshot(next,r.revision+1,input.selected));
 }catch(e){return failure(e);}}
