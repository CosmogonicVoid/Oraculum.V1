import ForecastDashboard from './forecast-dashboard';
import {getChatGPTUser} from './chatgpt-auth';
import {freshReplay,snapshot} from '../lib/replay';
export const dynamic='force-dynamic';
export default async function Home(){const user=await getChatGPTUser();return <ForecastDashboard signedIn={!!user} name={user?.fullName||'Researcher'} initial={snapshot(freshReplay())}/>;}
