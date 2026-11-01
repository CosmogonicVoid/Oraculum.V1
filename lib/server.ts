import { env } from 'cloudflare:workers';
import { getChatGPTUser } from '../app/chatgpt-auth';
import { freshAccount, type Account } from './trading';
export class HttpError extends Error{constructor(public status:number,message:string){super(message);}}
export function database(){if(!env.DB)throw new HttpError(503,'Account storage is unavailable. Please try again.');return env.DB;}
export async function identity(){const u=await getChatGPTUser();if(!u)throw new HttpError(401,'Sign in to create your ₹1 lakh practice portfolio.');return u;}
export async function readAccount(id:string){const row=await database().prepare('SELECT state, revision FROM accounts WHERE user_id=?').bind(id).first<{state:string;revision:number}>();return row?{account:JSON.parse(row.state) as Account,revision:row.revision}:{account:freshAccount(),revision:0};}
export async function ensureAccount(id:string){await database().prepare('INSERT OR IGNORE INTO accounts(user_id,state,revision) VALUES(?,?,0)').bind(id,JSON.stringify(freshAccount())).run();return readAccount(id);}
export async function saveAccount(id:string,account:Account,revision:number){const r=await database().prepare('UPDATE accounts SET state=?,revision=revision+1 WHERE user_id=? AND revision=?').bind(JSON.stringify(account),id,revision).run();if(r.meta.changes!==1)throw new HttpError(409,'Your portfolio changed in another tab. Refresh and preview again.');}
export async function body(req:Request,limit=8192){
 if(req.headers.get('origin')!==new URL(req.url).origin||req.headers.get('sec-fetch-site')==='cross-site')throw new HttpError(403,'Cross-site requests are not allowed.');
 if(!req.headers.get('content-type')?.startsWith('application/json'))throw new HttpError(415,'Expected JSON.');
 const reader=req.body?.getReader();if(!reader)throw new HttpError(400,'Missing request.');let bytes=0;const chunks:Uint8Array[]=[];
 while(true){const r=await reader.read();if(r.done)break;bytes+=r.value.length;if(bytes>limit){await reader.cancel();throw new HttpError(413,'Request too large.');}chunks.push(r.value);}
 const all=new Uint8Array(bytes);let offset=0;for(const chunk of chunks){all.set(chunk,offset);offset+=chunk.length;}
 try{const v=JSON.parse(new TextDecoder().decode(all));if(!v||typeof v!=='object'||Array.isArray(v))throw Error();return v;}catch{throw new HttpError(400,'Invalid JSON request.');}
}
export function json(v:unknown,status=200){return Response.json(v,{status,headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});}
export function failure(e:unknown){if(e instanceof HttpError)return json({error:e.message},e.status);console.error('Account request failed');return json({error:'The request could not be completed. Please try again.'},500);}
