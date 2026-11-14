"""Small inference facade for backend workers. No training or HTTP server."""
import hashlib
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from threadpoolctl import threadpool_limits

from .core import History,FEATURES,predict_origin
from .payload import to_payload


class ForecastService:
    def __init__(self,model_path):
        path=Path(model_path)
        # Only load artifacts whose origin is trusted: joblib is executable serialization.
        self.bundle=joblib.load(path)
        if not isinstance(self.bundle,dict) or self.bundle.get('features')!=FEATURES:
            raise ValueError('Expected the forecast_3d.joblib bundle, not an older one-day/outage model')
        if self.bundle.get('horizonDays')!=3:
            raise ValueError('Incompatible forecast horizon')
        if self.bundle.get('sklearnVersion')!=sklearn.__version__:
            raise RuntimeError(f"Use scikit-learn {self.bundle.get('sklearnVersion')}; installed {sklearn.__version__}")
        self.model_version=f"{self.bundle['method']}:{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}"

    def predict_segment(self,history,segment,origin=None,include_meters=False,expected_meters=7):
        """segment: canonical UUID or unique demo code, e.g. SEG-013.

        history is a History instance built from source readings, not train.csv.
        origin is the FIRST day to forecast, default the history's exclusive end.
        """
        identifier=str(segment)
        mask=(history.meters.segment_id.astype(str)==identifier)|(history.meters.segment.astype(str)==identifier)
        indexes=np.flatnonzero(mask.to_numpy())
        if not len(indexes):
            raise KeyError(f'Unknown segment: {identifier}')
        metadata=history.meters.iloc[indexes].reset_index(drop=True)
        if metadata.segment_id.nunique()!=1:
            raise ValueError('Ambiguous segment code; use the canonical segment UUID')
        # The catalog supplies its full registered topology; handoff callers retain seven.
        if len(metadata)!=expected_meters or expected_meters<1:
            raise ValueError('Metadata must include every registered meter for the segment')
        origin=pd.Timestamp(origin) if origin is not None else history.end
        origin=origin.tz_localize('UTC') if origin.tzinfo is None else origin.tz_convert('UTC')
        if origin!=origin.normalize():
            raise ValueError('origin must be midnight UTC, e.g. 2026-11-14')
        if origin<pd.Timestamp(self.bundle['trainedTargetEndExclusive']):
            raise ValueError('This fitted model cannot be backtested before its training cutoff')
        subset=History(metadata,history.start,history.end,
                       history.slots[:,indexes,:],history.arrival[:,indexes,:])
        with threadpool_limits(limits=1):
            frame=predict_origin(subset,origin,self.bundle['method'],self.bundle['model'])
        payload=to_payload(frame,self.bundle['method'],self.bundle['trainedTargetEndExclusive'])
        entry=payload.pop('segments')[0]
        meters=payload.pop('meters')
        result=dict(payload,**entry,modelVersion=self.model_version)
        if include_meters:
            result['meters']=meters
        return result

    def predict_all_segments(self,history,origin=None):
        """Run once per segment in a daily worker; persist/cache returned dictionaries."""
        return [self.predict_segment(history,sid,origin=origin)
                for sid in history.meters.segment_id.drop_duplicates()]
