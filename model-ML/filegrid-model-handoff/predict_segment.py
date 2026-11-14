"""Run the trained model against the demo SQLite database; never fits a model."""
import argparse
import json
from pathlib import Path

import pandas as pd

from filegrid_forecast.core import History
from filegrid_forecast.service import ForecastService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', type=Path, required=True,
                        help='Path to data/history.sqlite')
    parser.add_argument('--manifest', type=Path,
                        help='Defaults to manifest.json next to history.sqlite')
    parser.add_argument('--segment', required=True, help='Segment UUID or demo code, e.g. SEG-013')
    parser.add_argument('--origin', help='FIRST forecast day, YYYY-MM-DD, UTC; default endExclusive')
    parser.add_argument('--model', type=Path,
                        default=Path(__file__).resolve().parent / 'model/forecast_3d.joblib')
    parser.add_argument('--include-meters', action='store_true')
    parser.add_argument('--out', type=Path, help='Optional output JSON file')
    args = parser.parse_args()
    manifest_path = args.manifest or args.history.parent / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    history = History.from_sqlite(
        args.history,
        pd.Timestamp(manifest['startInclusive'], tz='UTC'),
        pd.Timestamp(manifest['endExclusive'], tz='UTC'),
    )
    service = ForecastService(args.model)
    result = service.predict_segment(history, args.segment, origin=args.origin,
                                     include_meters=args.include_meters)
    output = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output + '\n')
    print(output)


if __name__ == '__main__':
    main()
