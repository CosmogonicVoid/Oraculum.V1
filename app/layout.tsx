import type { Metadata } from 'next';
import './globals.css';
export const metadata:Metadata={title:'Oraculum — Forecast. Test. Learn.',description:'A forecast research lab with a ₹1 lakh virtual investing challenge, real historical NSE data, and a dated forecast record. No live feed is connected.'};
export default function RootLayout({children}:Readonly<{children:React.ReactNode}>){return <html lang="en"><body>{children}</body></html>;}
