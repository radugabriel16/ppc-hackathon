from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import warnings
import sqlite3

import numpy as np
import pandas as pd

FEATURES=['lag1_ratio','lag7_ratio','mean7_ratio','mean28_ratio','trend7','cv7',
          'annual_to_recent','log_reference','weekday_sin','weekday_cos',
          'season_sin','season_cos','residential','commercial','industrial']


def nanmedian(values,axis=0):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        return np.nanmedian(values,axis=axis)


@dataclass
class History:
    meters: pd.DataFrame
    start: pd.Timestamp
    end: pd.Timestamp
    slots: np.ndarray
    arrival: np.ndarray

    @classmethod
    def from_sqlite(cls,path,start,end):
        with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
            meters=pd.read_sql_query('''SELECT c.id,c.external_code,c.client_type,c.segment_id,
                s.code AS segment,r.code AS region FROM contoare c JOIN segmente s ON s.id=c.segment_id
                JOIN regiuni r ON r.id=s.region_id ORDER BY c.id''',db)
            readings=pd.read_sql_query('SELECT meter_id,interval_start,interval_end,energy_kwh,received_at FROM stats_contor',db)
        return cls.from_frames(meters,readings,start,end)

    @classmethod
    def from_frames(cls,meters,readings,start,end):
        meters=meters.reset_index(drop=True).copy()
        r=readings.copy()
        for c in ['interval_start','interval_end','received_at']:
            r[c]=pd.to_datetime(r[c],utc=True)
        if meters.id.duplicated().any() or r.duplicated(['meter_id','interval_start']).any():
            raise ValueError('Duplicate identity or reading')
        if not ((r.interval_end-r.interval_start).dt.total_seconds()==21600).all():
            raise ValueError('Expected 6-hour intervals')
        if r.received_at.isna().any() or (r.received_at<r.interval_end).any() or (r.energy_kwh<0).any():
            raise ValueError('Invalid energy or availability timestamp')
        if ((r.interval_start.dt.hour%6)!=0).any() or (r.interval_start.dt.minute!=0).any():
            raise ValueError('Expected UTC slots at 00/06/12/18')
        days=(end-start).days
        slot=np.full((days,len(meters),4),np.nan)
        arrival=np.full(slot.shape,np.iinfo(np.int64).max,dtype=np.int64)
        index={mid:i for i,mid in enumerate(meters.id)}
        if not set(r.meter_id).issubset(index):
            raise ValueError('Unknown meter')
        d=((r.interval_start-start).dt.total_seconds()/86400).astype(int).to_numpy()
        if (d<0).any() or (d>=days).any():
            raise ValueError('Readings outside declared observation range')
        m=r.meter_id.map(index).to_numpy()
        k=(r.interval_start.dt.hour//6).to_numpy()
        slot[d,m,k]=r.energy_kwh.to_numpy()
        arrival[d,m,k]=r.received_at.astype('int64').to_numpy()
        return cls(meters,start,end,slot,arrival)

    def snapshot(self,origin):
        """Observed-only snapshot; no future energy enters any predictor."""
        origin=pd.Timestamp(origin)
        day=(origin-self.start).days
        cutoff=origin+pd.Timedelta(minutes=10)
        known=(self.arrival<=cutoff.value)&np.isfinite(self.slots)
        complete=known.sum(axis=2)==4
        energy=np.where(known,self.slots,0).sum(axis=2)
        energy[~complete]=np.nan
        energy[max(day,0):]=np.nan
        return energy

    def truth(self,day):
        if day<0 or day>=len(self.slots):
            return np.full(len(self.meters),np.nan)
        complete=np.isfinite(self.slots[day]).sum(axis=1)==4
        total=np.nansum(self.slots[day],axis=1)
        return np.where(complete,total,np.nan)


@lru_cache(maxsize=4096)
def annual_indices(start,day,length):
    target=start+pd.Timedelta(days=int(day))
    center=target-pd.DateOffset(years=1)
    return [int(((center+pd.Timedelta(days=offset))-start).days) for offset in range(-14,15)
            if (center+pd.Timedelta(days=offset)).weekday()==target.weekday()
            and 0<=((center+pd.Timedelta(days=offset))-start).days<min(day,length)]


def annual_reference(observed,start,day):
    ix=annual_indices(start,day,len(observed))
    if not ix:
        return np.full(observed.shape[1],np.nan)
    values=observed[ix]
    ref=nanmedian(values)
    ref[(np.isfinite(values).sum(axis=0)<2)|(ref<=1e-9)]=np.nan
    return ref


def level_correction(observed,start,origin_day):
    """Robust recent-vs-last-year level, fixed at origin for all three horizons."""
    ratios=[]
    for day in range(max(0,origin_day-28),origin_day):
        ref=annual_reference(observed,start,day)
        ratios.append(np.divide(observed[day],ref,out=np.full(len(ref),np.nan),where=ref>1e-9))
    stack=np.array(ratios)
    correction=nanmedian(stack)
    correction[(np.isfinite(stack).sum(axis=0)<7)|~np.isfinite(correction)|(correction<=0)]=1.
    return correction


def inputs(state,observed,start,day,correction,meters):
    recent=nanmedian(state[[day-7,day-14,day-21,day-28]])
    annual=annual_reference(observed,start,day)*correction
    reference=np.where(np.isfinite(annual),annual,recent)
    ref=np.where(reference>1e-9,reference,np.nan)
    week=state[day-7:day]
    prev=state[day-14:day-7]
    mean7=np.nanmean(week,axis=0)
    mean_old=np.nanmean(prev,axis=0)
    date=start+pd.Timedelta(days=int(day))
    frame=pd.DataFrame(dict(lag1_ratio=state[day-1]/ref,lag7_ratio=state[day-7]/ref,
        mean7_ratio=mean7/ref,mean28_ratio=np.nanmean(state[day-28:day],axis=0)/ref,
        trend7=np.divide(mean7,mean_old,out=np.full(len(ref),np.nan),where=mean_old>1e-9),
        cv7=np.divide(np.nanstd(week,axis=0),mean7,out=np.zeros(len(ref)),where=mean7>1e-9),
        annual_to_recent=annual/np.where(recent>1e-9,recent,np.nan),log_reference=np.log1p(ref),
        weekday_sin=np.sin(2*np.pi*date.weekday()/7),weekday_cos=np.cos(2*np.pi*date.weekday()/7),
        season_sin=np.sin(2*np.pi*date.dayofyear/365.25),season_cos=np.cos(2*np.pi*date.dayofyear/365.25),
        residential=(meters.client_type=='RESIDENTIAL').astype(int),
        commercial=(meters.client_type=='COMMERCIAL').astype(int),
        industrial=(meters.client_type=='INDUSTRIAL').astype(int)))
    eligible=np.isfinite(ref)&np.isfinite(week).all(axis=0)&(ref>0)
    return frame[FEATURES],ref,eligible,np.isfinite(annual)


def training_data(history,cutoff):
    chunks=[]
    targets=[]
    for day in range(28,(cutoff-history.start).days):
        origin=history.start+pd.Timedelta(days=day)
        observed=history.snapshot(origin)
        correction=level_correction(observed,history.start,day)
        x,ref,eligible,_=inputs(observed,observed,history.start,day,correction,history.meters)
        actual=history.truth(day)
        # Require the target to have arrived by the moment training ends.
        available_by_fit=(history.arrival[day]<= (cutoff+pd.Timedelta(minutes=10)).value).all(axis=1)
        use=eligible&np.isfinite(actual)&available_by_fit
        chunks.append(x.loc[use])
        targets.extend((actual[use]/ref[use]).tolist())
    return pd.concat(chunks,ignore_index=True),np.asarray(targets)


def predict_origin(history,origin,method,model=None,horizon=3,observed=None,correction=None):
    day=(origin-history.start).days
    if day<28 or day>len(history.slots):
        raise ValueError('Origin needs 28 days of history and must be within/just after observations')
    observed=history.snapshot(origin) if observed is None else observed
    state=np.vstack([observed.copy(),np.full((horizon,len(history.meters)),np.nan)])
    correction=level_correction(observed,history.start,day) if correction is None else correction
    output=[]
    for h in range(horizon):
        d=day+h
        x,ref,eligible,annual_used=inputs(state,observed,history.start,d,correction,history.meters)
        predicted=np.full(len(history.meters),np.nan)
        if eligible.any():
            if method=='seasonal_reference':
                predicted[eligible]=ref[eligible]
            elif method=='last_week':
                predicted[eligible]=state[d-7,eligible]
            else:
                predicted[eligible]=np.maximum(0,model.predict(x.loc[eligible])*ref[eligible])
        # Only estimates are inserted into this private recursive state, never history/DB.
        state[d]=predicted
        actual=history.truth(d)
        for i,meter in enumerate(history.meters.itertuples(index=False)):
            output.append(dict(origin=origin.isoformat(),as_of=(origin+pd.Timedelta(minutes=10)).isoformat(),
                date=(history.start+pd.Timedelta(days=d)).date().isoformat(),horizon=h+1,
                meter_id=meter.id,meter=meter.external_code,segment_id=meter.segment_id,
                segment=meter.segment,region=meter.region,predicted_kwh=float(predicted[i]),
                actual_kwh=float(actual[i]),reference_kwh=float(ref[i]),annual_reference_used=bool(annual_used[i]),
                eligible=bool(eligible[i]),predicted_days_in_last7=h,
                change_vs_previous_day_pct=float(100*(predicted[i]/state[d-1,i]-1)) if state[d-1,i]>1e-9 else np.nan,
                change_vs_reference_pct=float(100*(predicted[i]/ref[i]-1)) if ref[i]>1e-9 else np.nan))
    return pd.DataFrame(output)


def aggregate(frame):
    keys=['origin','as_of','date','horizon','segment_id','segment','region']
    groups=frame.groupby(keys,as_index=False)
    total=groups[['predicted_kwh','actual_kwh','reference_kwh']].sum(min_count=1)
    counts=groups.agg(expected_meters=('meter_id','size'),eligible_meters=('eligible','sum'),
                      actual_meters=('actual_kwh','count'))
    total=total.merge(counts,on=keys,validate='one_to_one')
    total['complete_prediction']=total.expected_meters==total.eligible_meters
    total.loc[~total.complete_prediction,'predicted_kwh']=np.nan
    total.loc[total.actual_meters!=total.expected_meters,'actual_kwh']=np.nan
    total['change_vs_reference_pct']=100*(total.predicted_kwh/total.reference_kwh-1)
    return total


def error_metrics(frame):
    valid=frame.predicted_kwh.notna()&frame.actual_kwh.notna()
    f=frame[valid]
    if not len(f):
        return dict(rows=0,maeKwh=None,wape=None,rmseKwh=None)
    difference=f.predicted_kwh-f.actual_kwh
    return dict(rows=len(f),maeKwh=float(difference.abs().mean()),
                wape=float(difference.abs().sum()/f.actual_kwh.sum()) if f.actual_kwh.sum()>0 else None,
                rmseKwh=float(np.sqrt((difference**2).mean())))
