# Prompt 4-1 / 4-2 changed files

Implements conditional logic for dynamic forms.

## Added

- `form_builder/conditional_models.py`
  - `ConditionalRule` model with source field, operator, value, action, target field/section.
- `form_builder/conditional_services.py`
  - Server-side evaluator for conditional rules.
  - Runtime payload builder for frontend UX.
- `form_builder/conditional_forms.py`
  - Builder form for configuring rules without JSON editing.
- `form_builder/conditional_builder_views.py`
  - List/create/edit/delete UI for conditional rules.
- `form_builder/migrations/0012_conditional_rules.py`
  - Adds `ConditionalRule` table.
- `templates/form_builder/settings/conditional_rule_list.html`
- `templates/form_builder/settings/conditional_rule_form.html`
- `templates/form_builder/partials/conditional_logic_script.html`
- `form_builder/tests/test_conditional_rules.py`

## Updated

- `form_builder/apps.py`
  - Loads conditional extension models.
- `form_builder/attachment_entry_views.py`
  - Enforces conditional `require` rules server-side on create/save/validate/review.
  - Passes rule payload to templates.
- `form_builder/urls.py`
  - Adds builder routes for conditional rules.
- `templates/form_builder/entry_create.html`
- `templates/form_builder/entry_edit.html`
- `templates/form_builder/partials/entry_form_fields.html`
  - Adds frontend conditional behavior and data attributes.

## Rule format

Rules are stored in `ConditionalRule` rows:

- `source_field`
- `operator`: `equals`, `not_equals`, `is_empty`, `is_not_empty`
- `value`
- `action`: `show`, `hide`, `require`
- `target_field` or `target_section`

Frontend show/hide/required state is UX only. The authoritative validation happens in `conditional_services.apply_conditional_rules_to_form`.

## Commands

```powershell
poetry run python manage.py migrate
poetry run python manage.py check
poetry run python manage.py test form_builder
poetry run pre-commit run --all-files
```
