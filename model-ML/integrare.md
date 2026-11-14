# FileGrid — predicția consumului pe segment, următoarele 3 zile

Acesta este pachetul de inferență: încarcă modelul deja antrenat și produce estimări. Nu antrenează modele, nu modifică baza de date și nu pornește un server. Backendul FastAPI și autentificarea sunt responsabilitatea echipei de backend.

## 1. Ce se transmite colegilor

- `filegrid-model-handoff.zip`: tot acest director; model + codul necesar pentru pregătirea intrărilor și inferență + exemplu JSON.
- `filegrid-simulated-database.zip`: separat, datele simulate și SQLite, CSV-urile și schema/importul PostgreSQL.

Fișierul modelului este **`model/forecast_3d.joblib`**. Este un bundle cu estimatorul antrenat și metadate. Trebuie distribuit împreună cu `filegrid_forecast/` și `requirements.txt`: apelarea directă a estimatorului cu un ID de segment nu este suficientă. `ForecastService` pregătește intrările, estimează fiecare contor și însumează rezultatele pe segment.

Folosiți acest model de 3 zile. Modelele mai vechi pentru avarii sau consum pe o singură zi nu fac parte din integrare. Nu sunt necesare `train.csv`, `test.csv` sau rularea din nou a antrenării pentru a face predicții.

## 2. Test în terminal

Dezarhivați cele două arhive alături:

```text
shared/
  filegrid-model-handoff/
    model/forecast_3d.joblib
    filegrid_forecast/
    predict_segment.py
    requirements.txt
    INTEGRATION.md
    examples/
  filegrid-history-v2/
    data/history.sqlite
    data/manifest.json
    data/*.csv
    schema_postgres.sql
    import_postgres.psql
    ...
```

Din directorul `filegrid-model-handoff`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python predict_segment.py --history ../filegrid-history-v2/data/history.sqlite --segment SEG-013 --out result.json
```

Pentru detalierea celor 7 contoare adăugați `--include-meters`. Pentru o dată explicită adăugați `--origin 2026-11-14`. În integrare folosiți UUID-ul segmentului; codul `SEG-013` este acceptat ca scurtătură în demo.

Nu este necesară instalarea statsmodels, a unui LLM, a unui server ML sau folosirea unui GPU. Python 3.12 și versiunile din requirements sunt configurația verificată. Încărcați numai artifactul joblib livrat de echipă: formatul poate executa cod la deserializare. SHA-256 este în `checksums.json`.

## 3. Apelul Python exact

Exemplu executabil din directorul pachetului, cu baza SQLite livrată:

```python
import json
from pathlib import Path
import pandas as pd
from filegrid_forecast.core import History
from filegrid_forecast.service import ForecastService

# O singură încărcare per proces de worker, la pornire.
service = ForecastService("model/forecast_3d.joblib")

db_path = Path("../filegrid-history-v2/data/history.sqlite")
manifest = json.loads(db_path.with_name("manifest.json").read_text())
history = History.from_sqlite(
    db_path,
    pd.Timestamp(manifest["startInclusive"], tz="UTC"),
    pd.Timestamp(manifest["endExclusive"], tz="UTC"),
)

result = service.predict_segment(
    history,
    "2955b0aa-ebdf-5453-ab7d-90cc043f04f1",  # SEG-013
    origin="2026-11-14",                    # PRIMA zi de estimat
    include_meters=False,
)
print(json.dumps(result, indent=2, allow_nan=False))

# Pentru toate segmentele, în același job zilnic:
# results = service.predict_all_segments(history, origin="2026-11-14")
```

`predict_segment` primește istoricul și UUID-ul, întoarce un `dict` serializabil JSON. `predict_all_segments` întoarce o listă de 18 astfel de obiecte în demo. Nu produce 18 modele separate: același model global lucrează pentru toate contoarele.

## 4. Când sursa devine PostgreSQL

SQLite este sursa demo gata de folosit. Backendul poate importa aceleași date în PostgreSQL și poate construi `History` fără fișier SQLite:

```python
history = History.from_frames(
    meters=meters_df,
    readings=readings_df,
    start=pd.Timestamp("2024-11-14", tz="UTC"),
    end=pd.Timestamp("2026-11-14", tz="UTC"),
)
result = service.predict_segment(history, segment_uuid, origin="2026-11-14")
```

DataFrame-urile trebuie să aibă aceste coloane, cu ID-uri normalizate la string în ambele:

| DataFrame | Coloane obligatorii |
| --- | --- |
| `meters_df` | `id`, `external_code`, `client_type`, `segment_id`, `segment`, `region` |
| `readings_df` | `meter_id`, `interval_start`, `interval_end`, `energy_kwh`, `received_at` |

Query pentru metadate în schema demo:

```sql
SELECT c.id, c.external_code, c.client_type, c.segment_id,
       s.code AS segment, r.code AS region
FROM contoare c
JOIN segmente s ON s.id = c.segment_id
JOIN regiuni r ON r.id = s.region_id
ORDER BY c.id;
```

Query pentru citiri:

```sql
SELECT meter_id, interval_start, interval_end, energy_kwh, received_at
FROM stats_contor
WHERE interval_start >= :start AND interval_start < :end;
```

Pentru un segment puteți filtra ambele query-uri la cele 7 contoare ale lui; nu filtrați doar citirile păstrând metadatele tuturor. `energy_kwh` trebuie să fie numeric, finit și nenegativ; convertiți la float dacă driverul întoarce Decimal. `client_type`: `RESIDENTIAL`, `COMMERCIAL`, `INDUSTRIAL`.

Reguli obligatorii:

- Toate timestampurile și zilele modelului sunt UTC. `start` inclusiv, `end` exclusiv, ambele la miezul nopții.
- Sunt exact 4 intervale de 6 ore pe zi: 00–06, 06–12, 12–18, 18–24 UTC. O intrare este energia intervalului în kWh, nu index cumulativ și nu putere kW.
- Nu există duplicate `(meter_id, interval_start)`. `received_at` este momentul când intrarea a devenit disponibilă sistemului, cel puțin `interval_end`.
- Metadatele trebuie să conțină toate cele 7 contoare înregistrate pe segment în demo. Adaptorul refuză metadata pentru numai 6, ca să nu livreze un total fals complet. Numărul 7 este validarea structurii demo, nu o limită matematică a estimatorului; pentru altă topologie trebuie adaptată validarea și verificat modelul.
- Pentru o estimare sunt necesare minimum 28 de zile în intervalul declarat; ultimele 7 zile trebuie să fie complete pentru fiecare contor. Recomandăm păstrarea întregului istoric de 2 ani pentru comparația anuală și continuitatea datelor.
- Dacă lipsește comparația anuală, există fallback pe același tip de zi din săptămânile recente. Informația anuală este expusă per contor prin `annualReferenceUsed` dacă cereți `include_meters=True`.
- Lipsa citirilor unui contor nu se completează cu zero. Un total incomplet are `predictedEnergyKwh: null`, `status: INSUFFICIENT_DATA`; harta trebuie să arate lipsa datelor, nu un verde fals.

Nu furnizați date despre avarii modelului actual. Acesta folosește consumul și tipul clientului; nu estimează cauze sau probabilități de avarie.

## 5. Ce înseamnă cele 3 zile

`origin` este prima zi de prognoză. Cu istoricul livrat, ultima zi completă este 13 noiembrie 2026. `origin=2026-11-14` întoarce 14, 15 și 16 noiembrie. Dacă UI spune „următoarele 3 zile”, etichetați cu datele concrete din răspuns.

`asOf` este cutoff-ul datelor: 00:10 UTC în ziua `origin`. Citirile sosite după acest moment sunt mascate chiar dacă există în baza consultată. Aceasta este convenția actuală, pentru un job zilnic reproductibil; nu este un model intraday cu recalculări la orice oră. Predicția se referă la fiecare zi calendaristică UTC întreagă, nu la trei ferestre mobile de 24 de ore începând de la momentul apelului.

Prima zi folosește consumurile reale anterioare și referințe din perioada similară a anului trecut (aceeași zi a săptămânii în ±14 zile, corectată cu nivelul recent). A doua zi folosește și estimarea primei; a treia și estimările primelor două. Aceste estimări există doar în memoria apelului. Nu se inserează în `stats_contor` ca și cum ar fi citiri reale.

În demo, manifestul descrie istoricul fix. Când intră date reale noi, backendul trebuie să actualizeze intervalul `start/end` și `origin` la fiecare rulare, în loc să refolosească permanent `endExclusive` din manifest. Pentru o nouă zi trebuie să fie disponibile cele 4 citiri reale ale zilei precedente. Originile anterioare cutoff-ului de antrenare 2026-05-14 sunt refuzate de acest adaptor.

## 6. Outputul și semnificația câmpurilor

Răspunsul complet, produs efectiv din baza livrată: **`examples/segment-013.json`**. Cu detaliere pe contoare: **`examples/segment-013-with-meters.json`**.

Structura principală:

```json
{
  "schemaVersion": "1",
  "predictionKind": "DAILY_ENERGY_FORECAST",
  "units": "kWh/day",
  "dataSource": "SYNTHETIC_DEMO",
  "origin": "2026-11-14T00:00:00+00:00",
  "asOf": "2026-11-14T00:10:00+00:00",
  "lastCompletedDay": "2026-11-13",
  "horizonDays": 3,
  "method": "hgb_smooth",
  "modelTrainingCutoff": "2026-05-14T00:00:00+00:00",
  "uncertaintyIntervalsAvailable": false,
  "predictsOutageProbability": false,
  "segmentId": "2955b0aa-ebdf-5453-ab7d-90cc043f04f1",
  "segment": "SEG-013",
  "region": "DOBROGEA",
  "forecasts": [
    {"date":"2026-11-14","horizon":1,"predictedEnergyKwh":283.575728,"referenceEnergyKwh":274.016514,"changeVsReferencePct":3.488554,"expectedMeters":7,"eligibleMeters":7,"status":"READY"},
    {"date":"2026-11-15","horizon":2,"predictedEnergyKwh":283.492586,"referenceEnergyKwh":271.513654,"changeVsReferencePct":4.411908,"expectedMeters":7,"eligibleMeters":7,"status":"READY"},
    {"date":"2026-11-16","horizon":3,"predictedEnergyKwh":323.110340,"referenceEnergyKwh":330.695457,"changeVsReferencePct":-2.293686,"expectedMeters":7,"eligibleMeters":7,"status":"READY"}
  ],
  "modelVersion": "hgb_smooth:3a025fc48832"
}
```

- `predictedEnergyKwh`: totalul estimat al celor 7 contoare pentru acea zi; backendul nu îl mai însumează încă o dată.
- `referenceEnergyKwh`: referința sezonieră ajustată, folosită pentru comparație. Nu este capacitatea segmentului.
- `changeVsReferencePct`: `100 × (predicted/reference − 1)`. Nu este probabilitate sau scor de risc. O scădere față de referință poate totuși depăși un prag operațional mic.
- `expectedMeters`, `eligibleMeters`: câte contoare sunt înregistrate / câte au intrări suficiente pentru prognoză.
- `status`: `READY` sau `INSUFFICIENT_DATA`. JSON-ul nu conține NaN sau valori reale viitoare.
- `modelVersion`, `asOf`, `origin`: păstrați-le cu predicția pentru trasabilitate; data generării efective a jobului se poate adăuga separat ca `generatedAt`.
- `include_meters=True` adaugă `meters[]`, fiecare cu `meterId`, `meter`, `segmentId`, și 3 obiecte `forecasts[]` cu `date`, `horizon`, `predictedEnergyKwh`, `referenceEnergyKwh`, `changeVsPreviousDayPct`, `changeVsReferencePct`, `annualReferenceUsed`, `status`.

## 7. Integrarea recomandată în backend și pe hartă

1. La pornirea workerului: încărcați `ForecastService` o singură dată per proces.
2. Zilnic după cutoff-ul 00:10 UTC și verificarea citirilor: încărcați istoricul actualizat, calculați toate segmentele, salvați/cache-uiți răspunsurile. Pentru volumul demo, istoricul se încarcă o dată per job, nu o dată pentru fiecare segment.
3. Endpoint propus: `GET /api/v1/segments/{segmentId}/forecast`. Citește ultimul rezultat din cache/DB; nu recitește 2 ani și nu reantrenează la fiecare click pe hartă. Pentru hartă puteți expune și un endpoint cu toate segmentele regiunii pentru aceeași rulare.
4. Backendul verifică accesul pe segment/regiune. ID necunoscut: 404; segment cunoscut fără rezultat calculat încă: 503 sau starea explicită aleasă de echipă. Rezultat calculat cu date insuficiente: păstrați starea din JSON.
5. Frontendul afișează cele 3 zile, consumul, pragul demo și nivelul de semnalizare calculat de backend. Pentru o singură culoare pe segment, poate afișa cel mai sever nivel dintre cele 3 zile și data când apare. Afișați și `asOf` pentru a recunoaște rezultate vechi.

Propunere de tabel separat `segment_forecasts`: `id`, `segment_id`, `model_version`, `origin`, `as_of`, `target_date`, `horizon`, `predicted_energy_kwh` nullable, `reference_energy_kwh` nullable, `change_vs_reference_pct` nullable, `expected_meters`, `eligible_meters`, `status`, `generated_at`. Unicitate: `(segment_id, model_version, as_of, horizon)`. Puteți păstra alternativ payloadul întreg într-o coloană JSONB și indexa cheile de căutare.

O rulare completă produce **54 de rânduri de prognoză = 18 segmente × 3 zile**. Tabela de entități `segmente` rămâne cu 18 rânduri. La rulările următoare păstrați istoricul predicțiilor sau faceți upsert pentru aceeași cheie. Nu adăugați rândurile de prognoză în `segmente` ori `stats_contor`.

### Pragurile artificiale

Păstrați o configurație per segment, de exemplu `demo_daily_energy_limit_kwh` și pragul de atenție. Aplicați-o numai când `status=READY` și limita este pozitivă:

```python
ratio = forecast["predictedEnergyKwh"] / demo_daily_energy_limit_kwh
level = "ALERT" if ratio > 1 else "WATCH" if ratio > 0.8 else "OK"
threshold_usage_pct = 100 * ratio
```

Cu o limită DEMO de 300 kWh/zi, exemplul SEG-013 dă aproximativ 94,53%, 94,50%, 107,70%: WATCH, WATCH, ALERT. `threshold_usage_pct` este raportul consum estimat / prag artificial, nu probabilitate de avarie; nu îl limitați la 100%, fiindcă depășirea este informație utilă. Pentru date lipsă folosiți `UNKNOWN`, nu `OK`.

Un total zilnic în kWh nu demonstrează depășirea fizică a capacității în kW, curentul maxim sau un vârf scurt de consum. Prezentați pragurile ca limite operaționale de energie pentru demonstrație; determinarea supraîncărcării fizice ar necesita capacități reale și măsurători cu rezoluție potrivită.

## 8. Baza simulată și importul

Arhiva de date conține:

| Tabel | Conținut / volum |
| --- | --- |
| `regiuni` | 3 regiuni |
| `segmente` | 18 segmente, 6/regiune |
| `contoare` | 126 contoare, 7/segment |
| `stats_contor` | 367.920 citiri, 4/zi/contor, 730 zile |
| `stats_avarii` | 127 avarii simulate |
| `avarii_contoare` | 567 legături avarie–contor |
| `avarii_video` | tabel gol, fără filme fictive |

Interval: `[2024-11-14, 2026-11-14)`, UTC. `data/history.sqlite` este deja o bază SQLite utilizabilă; `data/*.csv` reprezintă aceleași tabele, nu date suplimentare care trebuie dublate. `manifest.json` descrie generarea datelor, nu versiunea modelului. `modelTrainingExecuted: false` din el se referă la generator; modelul separat livrat aici este deja antrenat.

Pentru verificare read-only în terminal:

```bash
sqlite3 ../filegrid-history-v2/data/history.sqlite '.tables'
sqlite3 ../filegrid-history-v2/data/history.sqlite 'SELECT COUNT(*) FROM stats_contor;'
```

Pentru PostgreSQL, schema și scriptul sunt propuneri livrate, nu o migrare deja executată pe backendul vostru. Într-o bază nouă goală, din directorul `filegrid-history-v2`, cu `DATABASE_URL` configurat local:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f import_postgres.psql
```

Într-o bază existentă, adaptați mai întâi migrarea la schema colegilor. Păstrați UUID-urile sursei sau remapați consecvent toate cheile străine. Dacă importați contoare cu alte UUID-uri și segmentele cu alte legături, integrarea va returna rezultate greșite sau nu va găsi segmentul. Nu importați și SQLite și CSV ca surse independente.

Aceasta este baza istoricului simulat, nu întreaga bază a aplicației: nu include utilizatori, dosare/documente, fișierele binare, coordonate/geometrii GIS pentru hartă sau filmări. Poziționarea pe hartă și celelalte module rămân în backendul aplicației. Avariile sunt livrate pentru context și funcționalitățile aplicației, dar modelul actual nu le citește.

## 9. Ce este verificat și limite

Modelul este HistGradientBoostingRegressor, metoda `hgb_smooth`. Antrenarea finală folosește primele 18 luni; pe Dobrogea, ultimele 6 luni, segment WAPE: 6,79% / 8,29% / 9,03% pentru zilele 1 / 2 / 3. Acestea sunt erori agregate pe setul simulat, nu garanții pentru fiecare predicție sau intervale de încredere. În septembrie, eroarea zilei 3 a fost aproximativ 17,13%. Raportul este în `examples/evaluation-report.json`.

Același holdout Dobrogea fusese consultat anterior în etapa modelului de o zi; nu este un test complet neatins la nivelul întregului proiect. Calitatea pe infrastructură reală nu a fost măsurată. Nu există intervale de incertitudine calibrate sau model de probabilitate de avarie în acest pachet.

Verificări efectuate pentru handoff: cele 9 teste din proiectul sursă; inferență reală pe segment; serializare JSON; egalitatea predicțiilor cu rularea existentă pe toate segmentele; checksum identic al modelului copiat. Detaliile sunt în `handoff-verification.json`. Integrarea efectivă în serverul FastAPI și importul PostgreSQL trebuie verificate de colegi în repository-ul lor.
