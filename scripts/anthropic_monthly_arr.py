#!/usr/bin/env python3
from pathlib import Path
import calendar
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/normalized/marts/daily_provider_economics.parquet'
OUTPUT = ROOT / 'anthropic_monthly_arr.png'

def money(x): return '—' if pd.isna(x) else f'${x:,.0f}'

def main():
    df = pd.read_parquet(SOURCE)
    df['usage_date'] = pd.to_datetime(df['usage_date']).dt.normalize()
    masks = [df[c].astype('string').str.contains('anthropic', case=False, na=False) for c in ('provider_slug','provider_name','entity_name','entity_id') if c in df]
    a = df[pd.concat(masks, axis=1).any(axis=1)].copy()
    max_date = df['usage_date'].max()
    a = a[a.usage_date < max_date].copy()
    a['estimated_revenue'] = pd.to_numeric(a['estimated_revenue'], errors='coerce').fillna(0.0)
    latest = max_date.to_period('M')
    out=[]
    for per,g in a.groupby(a.usage_date.dt.to_period('M'),sort=True):
        cal_days=calendar.monthrange(per.year,per.month)[1]; days=g.usage_date.nunique(); total=g.estimated_revenue.sum(); full=days==cal_days
        avg=total/(cal_days if full else days)
        status='Provisional (MTD Run Rate)' if per==latest else ('Complete' if full else 'Partial coverage')
        out.append({'Month':str(per),'Complete Days':int(days),'Month Total Revenue ($)':total,'Daily Avg Revenue ($)':avg,'Annualized ARR ($)':avg*365,'Status':status})
    s=pd.DataFrame(out)
    x=pd.to_datetime(s.Month); y=s['Annualized ARR ($)']/1e6; prov=s.Status.eq('Provisional (MTD Run Rate)')
    fig,ax=plt.subplots(figsize=(14,7.5),dpi=180); fig.patch.set_facecolor('white'); ax.set_facecolor('white')
    ax.plot(x,y,color='#245b9e',lw=2.4,marker='o',ms=4.5,label='Monthly ARR')
    ax.scatter(x[prov],y[prov],color='#d97706',edgecolor='white',lw=1.2,s=90,zorder=5,label='Provisional MTD run rate')
    if prov.any():
        i=prov[prov].index[-1]; ax.annotate(f'Provisional MTD\nthrough {max_date:%b %d, %Y}\n${y.loc[i]:,.1f}M ARR',xy=(x.loc[i],y.loc[i]),xytext=(-105,30),textcoords='offset points',fontsize=9,color='#92400e',bbox=dict(boxstyle='round,pad=.45',fc='#fff7ed',ec='#f59e0b'),arrowprops=dict(arrowstyle='-',color='#d97706'))
    ax.set_title('Anthropic Monthly ARR from OpenRouter Estimated Revenue',loc='left',fontsize=17,fontweight='bold',color='#172033',pad=18)
    ax.text(0,1.01,'Complete months use calendar-day revenue annualized ×365; latest month is a complete-day MTD run rate.',transform=ax.transAxes,fontsize=9.5,color='#536174',va='bottom')
    ax.set_ylabel('Annualized ARR ($M)'); ax.set_xlabel('Month'); ax.yaxis.set_major_formatter(FuncFormatter(lambda v,_: f'${v:,.0f}M')); ax.grid(axis='y',color='#e5e7eb',lw=.8); ax.grid(axis='x',visible=False); ax.spines[['top','right']].set_visible(False); ax.spines[['left','bottom']].set_color('#9ca3af'); ax.legend(frameon=False,loc='upper left',ncol=2,bbox_to_anchor=(0,.98)); fig.text(.01,.012,f'Source: {SOURCE.relative_to(ROOT)} | Max source date excluded as incomplete: {max_date.date()}',fontsize=8,color='#6b7280'); fig.autofmt_xdate(rotation=35,ha='right'); fig.tight_layout(rect=(0,.035,1,.95)); fig.savefig(OUTPUT,dpi=220,bbox_inches='tight',facecolor='white'); plt.close(fig)
    print(f'Source: {SOURCE}\nAnthropic rows: {len(a):,}; source max date excluded: {max_date.date()}; first retained date: {a.usage_date.min().date()}')
    print(s.to_string(index=False,formatters={'Month Total Revenue ($)':money,'Daily Avg Revenue ($)':money,'Annualized ARR ($)':money})); print(f'\nChart saved: {OUTPUT}')
if __name__=='__main__': main()
