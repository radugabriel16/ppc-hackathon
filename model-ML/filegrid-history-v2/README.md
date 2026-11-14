# FileGrid — istoric v2, fără modele și fără video-uri

Această versiune înlocuiește propunerea anterioară de date. Nu schimbă vechiul
pachet și nu antrenează/rulează niciun model.

## Decizia de structură

- 3 regiuni: Muntenia, Banat, Dobrogea.
- 6 segmente în fiecare regiune: 18 în total.
- Exact 7 contoare pe segment: 126 în total.
- 4 citiri pe zi, fiecare reprezentând energia unui interval UTC de 6 ore.
- 2024-11-14 inclusiv → 2026-11-14 exclusiv, 730 zile, 367.920 citiri.
- Fără transmisii omise în această versiune. Consumul mic nu este dată lipsă.
- Istoricul avariilor este metadată sintetică; nu se generează filme sau fișiere
  fictive pentru a justifica incidentele.

## Tabele

| Tabel | Conținut |
| --- | --- |
| regiuni | Cele 3 regiuni |
| segmente | Cele 18 segmente, legate de regiuni |
| contoare | Cele 126 contoare, legate de segmente |
| stats_contor | Citirile individuale, fără filtrare sau agregare |
| stats_avarii | Tabela auxiliară: UN rând per incident, cu segment și timestamp-uri |
| avarii_contoare | Ce contoare au fost afectate de incident |
| avarii_video | Legături între incident și fișierele reale; goală în istoricul sintetic |

Numele `stats_avarii` nu înseamnă total general. Din incidente se pot calcula
numărul pe zi/lună, recența și durata. Un total fără dată și segment nu ajunge.

Pentru analiza incidentelor, modelul viitor poate citi numai `stats_avarii`,
fără acces la filmări. Pentru corelarea cu consumul va citi și `stats_contor`,
folosind `contoare.segment_id`. Pentru afectarea precisă există avarii_contoare.

Relația este incident 1 → N fișiere video. Mai multe filmări despre același
incident nu înseamnă mai multe avarii. `avarii_video.file_id` trebuie conectat
prin FK la catalogul real de fișiere al backendului în timpul integrării.
Nu am creat acel catalog sau un storage de fișiere în această demonstrație.

## Ce se întâmplă la uploadul real

1. Angajatul introduce metadatele incidentului și filmarea.
2. Backendul validează segmentul, timpii și accesul și stochează fișierul.
3. În aceeași tranzacție de metadate, creează incidentul în stats_avarii și
   legătura spre fișier în avarii_video (sau adaugă filmarea unui incident existent).
4. Confirmă succesul numai după salvarea ambelor relații. Storage-ul extern
   și DB nu devin o singură tranzacție; aplicația păstrează mecanismul STAGING/READY.

Nu există o etapă separată de „confirmare avarie”. Validarea tehnică nu este
confirmare de business. Tabela auxiliară reprezintă incidentul cunoscut.
`source=UPLOAD` este pentru înregistrările reale; istoricul de aici are
`source=SYNTHETIC` și poate exista legitim fără o filmare.

`occurred_at` este momentul incidentului; `reported_at` este momentul introducerii
în sistem. Nu trebuie confundate. `restored_at` înseamnă alimentare restabilită,
iar `repair_completed_at` finalizarea intervenției. Timestamp-urile necunoscute
la capătul istoricului rămân NULL; nu inventăm că incidentul s-a rezolvat.

## Cum este simulat consumul

Fiecare contor are un profil persistent LOW/NORMAL/HIGH, cu probabilități
15%/70%/15%, și tip RESIDENTIAL/COMMERCIAL/INDUSTRIAL. Proporțiile sunt probabilistice,
nu cote exacte. Intervalele numerice sunt parametri de demo, nu statistici reale.

Se combină consumul de bază, efecte netede de iarnă/vară, weekendul, o variație
corelată regional, o variație individuală persistentă și o tendință lentă.
Energia zilei se distribuie în patru intervale cu ponderi specifice tipului
de client. Există intervale rare exagerate și perioade de consum redus.

`demo_base_daily_kwh` și `consumption_profile` sunt configurație sintetică;
nu trebuie confundate cu caracteristici măsurate și nu se dau automat unui model.
Nu exportăm vulnerabilitatea ascunsă sau probabilitatea simulatorului ca predictori.

## Cum sunt simulate avariile

Probabilitatea zilnică depinde de o vulnerabilitate latentă per segment, evoluția
ei, episoade regionale sezoniere și consumul agregat deja observat în zilele
precedente. Nu există regula deterministă „consum mare → avarie”. Evenimentele
sunt aleatoare; există anomalii fără incident și incidente fără avertisment evident.

Incidentul afectează între 2 și 7 contoare din segment. Momentul variază în cursul
zilei; durata simulează 1–12 ore. Energia contoarelor afectate scade cu fracția de
interval întrerupt, presupunând consum uniform în interiorul celor 6 ore.
Aceasta este o aproximație explicită, nu reconstrucția unor măsurători fine.
Pentru suprapunere completă energia devine zero. La sfârșitul întreruperii revine
profilul normal, fără compensarea artificială a energiei nelivrate.

Intervenția ulterioară poate fi TEMPORARY sau PERMANENT. Simulatorul modifică
vulnerabilitatea numai după momentul intervenției. Aceasta este o ipoteză de
simulare, nu o concluzie despre efectul real al reparațiilor.

Patru citiri/zi permit studierea consumului mediu; nu măsoară vârfurile instantanee
și nu demonstrează suprasarcina fizică. Nu există un model de flux de putere aici.

## Rulare și reproducere

Doar Python 3.12+ și biblioteca standard; fără pip sau alte servicii:

```bash
python generate.py --out data --seed 42
python verify.py --data data
```

Arhiva livrată include deja `data/`. Pentru o regenerare alegeți un director nou:

```bash
python generate.py --out data-new --seed 42
python verify.py --data data-new
```

Scriptul refuză înlocuirea unui history.sqlite existent. Același seed și aceiași
parametri reproduc conținutul CSV. Nu modificați doar un CSV fără regenerarea
întregului set: ar rupe consistența dintre consumuri și incidente.

## Baza de date livrată și importul PostgreSQL

`data/history.sqlite` este baza populată pentru inspecție locală, independentă de
aplicație. Cheile și relațiile sunt verificate. CSV-urile sunt alternativa de import.

`schema_postgres.sql` și `import_postgres.psql` sunt propuneri pentru o bază
PostgreSQL NOUĂ și GOALĂ. Dacă baza colegilor există ulterior, integrați numele,
ID-urile, FK-urile și migrațiile înainte de import. Nu executați schema peste tabele
existente și nu importați UUID-urile demo presupunând că sunt ID-uri reale.

Din directorul pachetului, după configurarea sigură a variabilei DATABASE_URL:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f import_postgres.psql
```

Importul folosește CSV-urile din `data/`; pentru alte directoare adaptați căile.
Nu am executat aceste comenzi PostgreSQL: nu există încă baza echipei. Am executat
crearea și verificarea SQLite. Importul direct nu testează API-ul de ingestie.

## Pentru modelul viitor

Un snapshot la momentul T are voie să folosească numai date cunoscute la T.
Un incident vechi, raportat abia după T, nu era încă o informație disponibilă.
Reparațiile cu repair_completed_at > T nu pot influența indicatorii de la T.
Nu folosiți source, UUID-urile, configurațiile ascunse sau etichetele viitoare
pentru a construi un rezultat aparent bun. Nu am antrenat modele în acest pachet.

## Verificări executate

`verify.py` verifică distribuția 3×6×7, numărul citirilor, intervalele de 6 ore,
unicitatea prin constrângeri, FK-urile, asocierea contoarelor afectate cu segmentul,
și faptul că fiecare citire zero corespunde unei întreruperi complete simulate.
Rezultatele și volumele se găsesc în data/verification.json și data/manifest.json.

Datele sunt exclusiv sintetice, fără video-uri, date personale sau geometrii
inventate prezentate ca rețea reală.
