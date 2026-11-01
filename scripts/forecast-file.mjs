// Dependency-free local forecast CLI. Node 24+; no network or paid API calls.
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import path from 'node:path';
import {forecast,parseCSV} from '../lib/forecast.ts';
const [input,output]=process.argv.slice(2);
if(!input){console.error('Usage: node scripts/forecast-file.mjs prices.csv [work/forecast.json]');process.exit(1);}
try{
 const bars=parseCSV(readFileSync(input,'utf8'));
 const result={createdAt:new Date().toISOString(),source:path.basename(input),dataStatus:'User-supplied, not independently verified',forecast:forecast(bars)};
 const json=JSON.stringify(result,null,2)+'\n';
 if(output){mkdirSync(path.dirname(path.resolve(output)),{recursive:true});writeFileSync(output,json);console.log(`Saved ${path.resolve(output)}`);}else process.stdout.write(json);
}catch(e){console.error(e.message);process.exit(1);}
