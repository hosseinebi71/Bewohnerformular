import sys
from pathlib import Path

ROOT = Path.cwd()

PARTIAL_PATH = (
    ROOT / "form_builder" / "templates" / "form_builder" / "partials" / "entry_form_fields.html"
)
CREATE_PATH = ROOT / "form_builder" / "templates" / "form_builder" / "entry_create.html"
EDIT_PATH = ROOT / "form_builder" / "templates" / "form_builder" / "entry_edit.html"
CSS_PATH = ROOT / "form_builder" / "static" / "form_builder" / "app.css"

PARTIAL = """{% if entry_form.sectioned_bound_field_groups %}
  {% for group in entry_form.sectioned_bound_field_groups %}
    {% if group.section %}
      <fieldset class="form-section{% if group.section.is_collapsible %} is-collapsible{% endif %}"{% if group.section.is_collapsible %} data-collapsible="true"{% endif %}>
        <legend class="form-section-title">{{ group.section.title }}</legend>
        {% if group.section.description %}<p class="form-section-description">{{ group.section.description }}</p>{% endif %}
        <div class="form-grid government-form section-fields">
          {% for field in group.fields %}
            <div class="field-row">
              <label for="{{ field.id_for_label }}">{{ field.label }}{% if field.field.required %}<span>*</span>{% endif %}</label>
              {{ field }}
              {% if field.help_text %}<small>{{ field.help_text }}</small>{% endif %}
              {% for error in field.errors %}<small class="error">{{ error }}</small>{% endfor %}
            </div>
          {% endfor %}
        </div>
      </fieldset>
    {% else %}
      <div class="form-grid government-form">
        {% for field in group.fields %}
          <div class="field-row">
            <label for="{{ field.id_for_label }}">{{ field.label }}{% if field.field.required %}<span>*</span>{% endif %}</label>
            {{ field }}
            {% if field.help_text %}<small>{{ field.help_text }}</small>{% endif %}
            {% for error in field.errors %}<small class="error">{{ error }}</small>{% endfor %}
          </div>
        {% endfor %}
      </div>
    {% endif %}
  {% endfor %}
{% else %}
  <div class="form-grid government-form">
    {% for field in entry_form %}
      <div class="field-row">
        <label for="{{ field.id_for_label }}">{{ field.label }}{% if field.field.required %}<span>*</span>{% endif %}</label>
        {{ field }}
        {% if field.help_text %}<small>{{ field.help_text }}</small>{% endif %}
        {% for error in field.errors %}<small class="error">{{ error }}</small>{% endfor %}
      </div>
    {% endfor %}
  </div>
{% endif %}
"""

OLD_BLOCK = """      <div class="form-grid government-form">
        {% for field in entry_form %}
          <div class="field-row">
            <label for="{{ field.id_for_label }}">{{ field.label }}{% if field.field.required %}<span>*</span>{% endif %}</label>
            {{ field }}
            {% if field.help_text %}<small>{{ field.help_text }}</small>{% endif %}
            {% for error in field.errors %}<small class="error">{{ error }}</small>{% endfor %}
          </div>
        {% endfor %}
      </div>"""

NEW_INCLUDE = '      {% include "form_builder/partials/entry_form_fields.html" %}'

CSS = """

/* dynamic form sections */
.form-section {
  margin: 0;
  padding: 0;
  border: 0;
  border-bottom: 1px solid var(--line);
  background: #fff;
}
.form-section-title {
  width: 100%;
  padding: 16px 22px 6px;
  color: #0b1f3a;
  font-size: 16px;
  font-weight: 950;
}
.form-section-description {
  margin: 0;
  padding: 0 22px 14px;
  color: var(--muted);
}
.form-section.is-collapsible .form-section-title::after {
  content: " einklappbar";
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.section-fields {
  border-top: 1px solid #edf2f7;
}
"""


def replace_template(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Missing template: {path}")
    text = path.read_text(encoding="utf-8")
    if NEW_INCLUDE in text:
        print(f"[OK] already patched {path}")
        return
    if OLD_BLOCK not in text:
        raise SystemExit(
            f"Could not find the old flat field block in {path}. Open the file and replace the form-grid loop manually."
        )
    path.write_text(text.replace(OLD_BLOCK, NEW_INCLUDE, 1), encoding="utf-8")
    print(f"[OK] patched {path}")


def main() -> int:
    if not (ROOT / "manage.py").exists():
        print(
            "Run this from the project root, e.g. C:\\Users\\hosse\\Bewohnerformular",
            file=sys.stderr,
        )
        return 2
    PARTIAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARTIAL_PATH.write_text(PARTIAL, encoding="utf-8")
    print(f"[OK] wrote {PARTIAL_PATH}")
    replace_template(CREATE_PATH)
    replace_template(EDIT_PATH)
    if CSS_PATH.exists():
        css = CSS_PATH.read_text(encoding="utf-8")
        if "dynamic form sections" not in css:
            CSS_PATH.write_text(css.rstrip() + CSS, encoding="utf-8")
            print(f"[OK] appended CSS to {CSS_PATH}")
        else:
            print(f"[OK] CSS already present in {CSS_PATH}")
    else:
        print(f"[WARN] CSS file not found: {CSS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
