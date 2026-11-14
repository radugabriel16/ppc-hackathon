"""JSON contract for a backend worker. No HTTP server and no actual labels."""
import math
import pandas as pd
from .core import aggregate


def number(value):
    return round(float(value),6) if math.isfinite(float(value)) else None


def to_payload(frame,method,training_cutoff):
    if frame.origin.nunique()!=1:
        raise ValueError('One forecast origin per payload')
    totals=aggregate(frame)
    segments=[]
    for sid,group in totals.groupby('segment_id'):
        first=group.iloc[0]
        segments.append(dict(segmentId=sid,segment=first.segment,region=first.region,
            forecasts=[dict(date=r.date,horizon=int(r.horizon),predictedEnergyKwh=number(r.predicted_kwh),
                referenceEnergyKwh=number(r.reference_kwh),changeVsReferencePct=number(r.change_vs_reference_pct),
                expectedMeters=int(r.expected_meters),eligibleMeters=int(r.eligible_meters),
                status='READY' if r.complete_prediction else 'INSUFFICIENT_DATA') for r in group.sort_values('horizon').itertuples()]))
    meters=[]
    for mid,group in frame.groupby('meter_id'):
        first=group.iloc[0]
        meters.append(dict(meterId=mid,meter=first.meter,segmentId=first.segment_id,
            forecasts=[dict(date=r.date,horizon=int(r.horizon),predictedEnergyKwh=number(r.predicted_kwh),
                referenceEnergyKwh=number(r.reference_kwh),changeVsPreviousDayPct=number(r.change_vs_previous_day_pct),
                changeVsReferencePct=number(r.change_vs_reference_pct),annualReferenceUsed=bool(r.annual_reference_used),
                status='READY' if r.eligible else 'INSUFFICIENT_DATA') for r in group.sort_values('horizon').itertuples()]))
    return dict(schemaVersion='1',predictionKind='DAILY_ENERGY_FORECAST',units='kWh/day',
        dataSource='SYNTHETIC_DEMO',origin=frame.origin.iloc[0],asOf=frame.as_of.iloc[0],
        lastCompletedDay=(pd.Timestamp(frame.origin.iloc[0])-pd.Timedelta(days=1)).date().isoformat(),
        horizonDays=int(frame.horizon.max()),method=method,modelTrainingCutoff=training_cutoff,
        uncertaintyIntervalsAvailable=False,predictsOutageProbability=False,
        segments=segments,meters=meters)
