# Energieplanner gebouw

Streamlit-app voor consultants om gebouwvraag, elektriciteitsverbruik, PV, warmtebronnen, opslag en netbelasting te simuleren.

## Lokaal starten

```bash
python3 -m pip install -r requirements.txt
streamlit run app.py
```

## Verplichte deploymentbestanden

- `app.py`: Streamlit-entrypoint.
- `requirements.txt`: Python-dependencies voor Streamlit Cloud.
- `Weatherdata 2008-2021.xlsx`: weerdata die de simulatie gebruikt.
- `src/`: modelcode.

## Niet meedeployen

Lokale meetdata, notebooks, `.DS_Store`, app-launchers, exports en caches horen niet in de repo. Deze zijn opgenomen in `.gitignore`.

## Checks vóór deploy

```bash
python3 -m py_compile app.py src/load/total.py src/load/profiles.py src/load/gebouwmodel.py
MPLCONFIGDIR=/tmp/energieplanner-mpl MPLBACKEND=Agg python3 tests/smoke_test.py
```

## Streamlit Cloud

- Main file path: `app.py`
- Python dependencies: `requirements.txt`
- Na grote state/schema-wijzigingen: gebruik in Streamlit Cloud eventueel `Reboot app` of `Clear cache`.
- Als een oude browser- of projectstate ongeldige waarden bevat, normaliseert de app invoerwaarden bij start en bij projectimport.
