# Prompt 10 CSS contract correction

The frontend CSS contract test reads `static/form_builder/app.css` and found Prompt 10 classes in templates that were only defined in the new mobile CSS layer.

This correction appends the missing class definitions to `app.css` without overwriting the existing stylesheet.

Apply from the project root:

```powershell
.\tools\apply_prompt10_css_contract_fix.ps1
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```

If PowerShell blocks the script, run:

```powershell
Get-Content .\static\form_builder\prompt10_css_contract_append.css | Add-Content .\static\form_builder\app.css
```
