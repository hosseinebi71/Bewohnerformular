# Bewohnerformular - Professional Schedule Step

Dieses Paket baut auf dem Outbox-Sending-Schritt auf und fuegt eine professionelle Zeitplan-Verwaltung hinzu.

Neu:
- Zeitplan-Uebersicht unter `/einstellungen/zeitplaene/`
- Zeitplan anlegen / bearbeiten / pausieren / aktivieren
- Tages- und Wochenrhythmus
- Verarbeitung faelliger Zeitplaene
- Management Command: `python manage.py process_schedules --limit-per-schedule 100`

Zeitplaene erzeugen keine neuen Bewohnerdaten. Sie nehmen nur bereits freigegebene Eintraege mit erzeugtem PDF und stellen sie in den Ausgangskorb.

Nach dem Kopieren:
```powershell
python manage.py makemigrations form_builder
python manage.py migrate
python manage.py runserver
```

Fuer diesen Schritt werden keine neuen Model-Felder benoetigt. `makemigrations` sollte normalerweise `No changes detected` melden.
