# CVR Årsværk Checker

Finder virksomheder, hvor det **gennemsnitlige årsværk i de seneste 6 måneder er steget med mindst +1,00**
sammenlignet med de 6 måneder umiddelbart før, og hvor det **seneste månedlige årsværk højst er 15,00**.
Data hentes fra [cvr.dev](https://docs.cvr.dev) (endpointet *Antal ansatte og årsværk*).

Kræver kun Python 3.10 eller nyere – ingen ekstra pakker, ingen database, ingen frontend.

## Daglig brug

### 1. Læg CVR-numrene i en fil

Enten en tekstfil med ét CVR-nummer pr. linje:

```
12345678
87654321
```

…eller en CSV-fil fra Excel, hvor en kolonne hedder noget med "cvr" (fx `CVR-nummer`).
Uden en sådan overskrift bruges første kolonne. Separatoren (`;`, tab eller `,`) aflæses
af første linje, og felter i anførselstegn håndteres korrekt.

* Mellemrum, `DK`-præfiks (`DK-1234 5678`), `12.345.678` og Excels `12345678.0` renses automatisk.
* Dubletter fjernes, og tomme celler springes over.
* Ugyldige numre (ikke 8 cifre) kommer med i resultatet som `FEJL`.
* Linjer der starter med `#` ignoreres.

### 2. Sæt API-nøglen (kun på din egen computer)

Nøglen læses fra miljøvariablen `CVR_DEV_API_KEY` og skrives aldrig i filer, log eller output.

macOS / Linux:

```bash
export CVR_DEV_API_KEY="din-nøgle"
```

Windows PowerShell:

```powershell
$env:CVR_DEV_API_KEY = "din-nøgle"
```

Læg aldrig nøglen i en fil i projektet. I Claude Code-cloudmiljøet er nøglen allerede
tilknyttet miljøet, så her skal intet sættes.

### 3. Kør værktøjet

Fra projektmappen:

```bash
python3 -m cvr_aarsvaerk_checker mine_cvr_numre.txt
```

(På Windows: `python -m cvr_aarsvaerk_checker mine_cvr_numre.txt`)

Undervejs vises fremdriften, fx `[ 12/980] 12345678  hentet  MATCH`.
1.000 CVR-numre tager typisk 5–10 minutter.

### 4. Åbn resultaterne i Excel

Hver kørsel får sin egen mappe, fx `resultater/2026-10-06_141500/`:

| Fil | Indhold |
|---|---|
| `matches.csv` | Kun virksomheder med status `MATCH` (vækst ≥ +1,00 og seneste årsværk ≤ 15,00), største stigning først |
| `alle_resultater.csv` | Alle virksomheder, uanset status |

Filerne bruger semikolon og decimalkomma, så de åbner direkte i dansk Excel.

### Hvis kørslen afbrydes

Kør bare samme kommando igen. Råsvar fra cvr.dev gemmes i `data/raa_svar/`, og svar der er
højst 7 dage gamle genbruges i stedet for at blive hentet igen – det sparer API-forbrug.

Afbryder du selv med Ctrl+C, skrives resultatfilerne stadig for det, der nåede at blive
behandlet. Var kørslen startet med `--opdater`, så kør igen **uden** `--opdater` – ellers
hentes (og betales) de allerede gemte svar en gang til.

## Valgmuligheder

| Valg | Betydning |
|---|---|
| `--offline` | Lav **ingen** API-kald; analysér kun gemte råsvar (uanset alder) |
| `--opdater` | Ignorér gemte råsvar og hent alt på ny |
| `--cache-dage N` | Genbrug gemte råsvar der er højst N dage gamle (default 7) |
| `--output-mappe STI` | Hvor resultater gemmes (default `resultater/`) |
| `--cache-mappe STI` | Hvor råsvar gemmes (default `data/raa_svar/`) |
| `--navne-mappe STI` | Hvor hentede virksomhedsnavne gemmes (default `data/navne/`) |
| `--pause SEK` | Pause efter hvert API-kald (default 0,2 sek.) |
| `--timeout SEK` | Timeout pr. API-kald (default 30 sek.) |
| `--max-genforsoeg N` | Genforsøg ved 429/5xx/netværksfejl (default 5) |

`python3 -m cvr_aarsvaerk_checker --help` viser det hele.

## Kolonner i resultatfilerne

| Kolonne | Forklaring |
|---|---|
| `cvr_nummer` | CVR-nummeret |
| `virksomhedsnavn` | Virksomhedens navn fra CVR (tom ved `FEJL`) |
| `seneste_registrerede_maaned` | Virksomhedens seneste måned med månedsdata (ÅÅÅÅ-MM) |
| `periode_a_start` / `periode_a_slut` | De 6 måneder før Periode B |
| `gennemsnit_aarsvaerk_periode_a` | Gennemsnitligt årsværk i Periode A |
| `periode_b_start` / `periode_b_slut` | De 6 seneste måneder |
| `gennemsnit_aarsvaerk_periode_b` | Gennemsnitligt årsværk i Periode B |
| `absolut_aendring` | Gennemsnit B − gennemsnit A |
| `procent_aendring` | Ændring i procent af gennemsnit A (kun information; tom hvis A = 0) |
| `seneste_aarsvaerk` | Årsværk i virksomhedens seneste måned (bruges i størrelsesfilteret ≤ 15,00) |
| `seneste_aarsvaerk_periode` | Måneden for `seneste_aarsvaerk` (ÅÅÅÅ-MM) |
| `status` | `MATCH`, `IKKE_MATCH`, `UTILSTRÆKKELIGE_DATA` eller `FEJL` |
| `note` | Forklaring ved `UTILSTRÆKKELIGE_DATA` og `FEJL` |

Tal vises med 2 decimaler. Afrunding sker **kun** i visningen.

## Analysemetoden

For hvert CVR-nummer:

1. Kun poster med `rapporteringsinterval = "måned"` bruges (ikke kvartals- eller årsdata).
2. Slutpunktet er virksomhedens **seneste registrerede måned** – ikke dagens dato.
3. De 12 kalendermåneder, der slutter i den måned, er de eneste der bruges.
   **Periode A** = de 6 første, **Periode B** = de 6 seneste. Ældre historik ignoreres.
4. **MATCH** hvis `sum(B) − sum(A) ≥ 6`, hvilket er præcis det samme som
   `gennemsnit B − gennemsnit A ≥ 1,00`. Alt regnes eksakt (decimaltal og brøker), så fx en reel
   ændring på 0,996 er `IKKE_MATCH`, selvom den vises som 1,00. Præcis +1,00 er `MATCH`.
   Der er ingen øvre grænse for væksten.
5. **Størrelsesfilter:** `MATCH` kræver desuden, at virksomhedens seneste månedlige `aarsvaerk`
   (seneste registrerede måned = sidste måned i Periode B) er **≤ 15,00**. Præcis 15,00 er tilladt;
   over 15,00 giver `IKKE_MATCH` med en forklaring i `note`. Værdien afrundes ikke før beslutningen
   (15,0001 er over grænsen). Filteret ændrer ikke 6-mod-6-beregningen. Mangler den seneste værdi
   eller er den ugyldig, giver punkt 3 allerede `UTILSTRÆKKELIGE_DATA`.

| Status | Betyder |
|---|---|
| `MATCH` | Stigning på mindst +1,00 årsværk **og** seneste månedlige årsværk ≤ 15,00 |
| `IKKE_MATCH` | Stigning under +1,00 (eller fald), eller seneste månedlige årsværk over 15,00 |
| `UTILSTRÆKKELIGE_DATA` | En af de 12 måneder mangler, findes flere gange, eller har tom/ugyldig `aarsvaerk` (ugyldig = ikke et tal eller negativ). Der søges **ikke** længere tilbage. Intervalkoder bruges aldrig som erstatning. `0` er en gyldig værdi. Ekstremt høje værdier (≥ 1.000.000) analyseres normalt, men får en advarsel i `note`. |
| `FEJL` | Opslaget eller behandlingen kunne ikke gennemføres: API-fejl, 429/5xx efter genforsøg, ugyldigt svar, ugyldigt CVR-nummer eller anden teknisk fejl |

## API-forbrug og fejlhåndtering

* Ét opslag pr. CVR-nummer (endpointet tager kun ét nummer ad gangen).
* Virksomhedsnavnet findes ikke i svaret for ansatte og årsværk. Det hentes derfor fra cvr.dev's
  endpoint med rå CVR-data, 10 CVR-numre pr. kald (ca. +10 % kald), og gemmes i `data/navne/` i
  90 dage, så det ikke hentes igen. Navnet påvirker aldrig status eller beregninger; kan det ikke
  hentes, står der `virksomhedsnavn mangler` i `note`.
* Før første opslag testes nøglen med cvr.dev's gratis test-endpoint. Er nøglen ugyldig
  (401), mangler abonnementet (402), eller dækker abonnementet ikke endpointet (403),
  stoppes kørslen med det samme, før der bruges forbrug.
* 429 og 5xx genforsøges med exponential backoff (2, 4, 8, 16, 32 sek.). Sender API'et en
  `Retry-After`-header, bruges den.
* Fejler 5 opslag i træk efter alle genforsøg, stoppes kørslen (API'et er formentlig nede).
* Kan råsvar ikke gemmes (fx fuld disk), stoppes kørslen, så der ikke betales for opslag,
  der går tabt.
* Når kørslen stoppes, laves der ingen flere API-kald, men resten af CVR-numrene analyseres
  stadig ud fra gemte råsvar. Kun dem uden gemt svar markeres `FEJL` ("ikke behandlet").
  Resultatfilerne skrives altid, og en ny kørsel genbruger de gemte svar.
* Redirects følges ikke, så API-nøglen aldrig sendes til en anden adresse.

## Projektstruktur

```
cvr_aarsvaerk_checker/
  __main__.py      # gør det muligt at køre: python -m cvr_aarsvaerk_checker
  cli.py           # kommandolinje og selve kørslen
  indlaesning.py   # læs, rens, validér og fjern dubletter i CVR-numre
  api.py           # cvr.dev-klient (retries, backoff, timeout) og cache af råsvar
  analyse.py       # analysemetoden (ren beregning, ingen netværk)
  navne.py         # virksomhedsnavne (hentes 10 ad gangen og gemmes)
  output.py        # CSV-filer til Excel
tests/             # pytest – laver aldrig rigtige API-kald
eksempel_cvr_numre.txt
```

## For udviklere

```bash
python3 -m pip install -e ".[dev]"
pytest          # tests (netværk er blokeret i tests)
ruff check .    # lint
mypy            # typecheck
```
