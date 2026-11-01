import Dashboard from '../dashboard';
import {getChatGPTUser} from '../chatgpt-auth';
export const dynamic='force-dynamic';
export default async function Legacy(){const user=await getChatGPTUser();return <><div style={{padding:'12px 24px',background:'#2a3028',position:'relative',zIndex:20,textAlign:'center',fontSize:12}}>Archived fictional-price prototype. Your original account is preserved. <a href="/" style={{textDecoration:'underline'}}>Open the forecast lab →</a></div><Dashboard signedIn={!!user} name={user?.fullName||'Investor'}/></>;}
