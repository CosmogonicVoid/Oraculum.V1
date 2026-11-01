import {identity,readAccount,json,failure} from '../../../lib/server';
export async function GET(){try{const u=await identity();return json(await readAccount(u.userId));}catch(e){return failure(e);}}
