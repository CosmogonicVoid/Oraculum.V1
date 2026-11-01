import {database,identity,body,json,failure,HttpError} from '../../../lib/server';
import {importResearch,type ResearchState} from '../../../lib/research';
export const dynamic='force-dynamic';
async function read(id:string){const r=await database().prepare('SELECT state, revision FROM research_accounts WHERE user_id=?').bind(id).first<{state:string;revision:number}>();return r?{state:JSON.parse(r.state) as ResearchState,revision:r.revision}:{state:{runs:[]} as ResearchState,revision:0};}
export async function GET(){try{const u=await identity();return json(await read(u.userId));}catch(e){return failure(e);}}
export async function POST(req:Request){try{
 const u=await identity(),input=await body(req,650000);
 if(!Number.isSafeInteger(input.revision))throw new HttpError(400,'A workspace revision is required.');
 await database().prepare('INSERT OR IGNORE INTO research_accounts(user_id,state,revision) VALUES(?,?,0)').bind(u.userId,JSON.stringify({runs:[]})).run();
 const current=await read(u.userId);if(input.revision!==current.revision)throw new HttpError(409,'Your research workspace changed. Reload before uploading again.');
 let state:ResearchState;try{state=await importResearch(current.state,input);}catch(e){throw new HttpError(400,(e as Error).message);}
 const result=await database().prepare('UPDATE research_accounts SET state=?,revision=revision+1 WHERE user_id=? AND revision=?').bind(JSON.stringify(state),u.userId,current.revision).run();
 if(result.meta.changes!==1)throw new HttpError(409,'Another import completed first. Reload your workspace.');
 return json({state,revision:current.revision+1});
 }catch(e){return failure(e);}}
