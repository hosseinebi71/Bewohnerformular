# v14 - Manual PDF Preview and Immediate Send

## Changed
- Removed live PDF iframe rendering from create and edit screens.
- PDF preview now opens in a new browser tab from the saved entry state.
- Create screen keeps a direct `Leeres Formular` PDF link for blank printouts.
- Edit screen offers `Speichern`, `Vorschau`, and `Schicken` without live reload overhead.

## Added
- `Sofort schicken` on the new-entry form with browser confirmation.
- `Jetzt schicken` next to every entry in the Entwuerfe list with browser confirmation.
- `Jetzt schicken` in the entry detail action panel.
- Safe saved-entry send mode for list/detail actions.

## Tested
- `python manage.py check`
- `python manage.py migrate --noinput`
- `python manage.py seed_government_demo_forms`
- Authenticated smoke checks for `/`, `/formulare/`, `/formulare/entwuerfe/`, `/einstellungen/`, create page and edit page.
- Manual POST smoke test for `Jetzt schicken` using the console email backend.
