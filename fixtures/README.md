# Geography fixtures

`romania.geojson` is Romania's national border from **Natural Earth
1:10m Admin 0 Countries, v5.1.2**, simplified with PostGIS
`ST_SimplifyPreserveTopology(..., 0.005)` (degrees), in EPSG:4326.

Source: https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_10m_admin_0_countries.geojson

License: **public domain**. Natural Earth permits all uses without restriction:
https://www.naturalearthdata.com/about/terms-of-use/

The three illustrative operational areas use the original map display squares
(not administrative boundaries). Each is intersected with this vendored border.
Subregions are numbered west-to-east, south-to-north in a 2-column, 3-row grid.
If clipping removes cells, the largest remaining part is bisected until six
non-empty parts remain. Codes and UUIDs are deterministic.

`contracts/examples/regions.json` contains an offline display-geometry snapshot
from the seed for contract examples and demo/mock maps.

Run `python -m fixtures.geography` from the backend container to re-seed geometry
without deleting any history. Bootstrap also runs it after migrations and seeds.
Meters have stored EPSG:4326 points; existing rows initially use their asset's
representative point. `fixtures.meters.seed_meters` preserves existing meter IDs,
codes and links and fills each of the 18 subregions to exactly eight meters
(144 total), using deterministic IDs/codes and typed synthetic clients. It refuses
to remove meters if a subregion already has more than eight. New segments without
assets receive a deterministic LINE_SEGMENT asset. Threshold defaults are inserted
only when absent, preserving manager configuration. Bootstrap runs this seed;
`python -m fixtures.meters` can safely rerun it without resetting any history.
Issues use their actual location.
Files use linked meter/asset/client locations when available. Documents without
a client location, and unlinked files, use their parent region's representative
point. Boundary ties use the first subregion code (`ST_Covers`, not `ST_Contains`).
Locations outside all operational areas remain unassigned, rather than being
silently moved to an unrelated area.

The seed corrects four known synthetic Dobrogea asset points that the original
positive offsets placed offshore, moving them to representative points of a
small onshore intersection nearby. Their IDs, links and historical readings
are unchanged. Other out-of-area locations are never relocated.
