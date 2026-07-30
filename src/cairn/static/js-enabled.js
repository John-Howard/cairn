// govuk-frontend v5+ marks JS support with govuk-frontend-supported — the CSS
// gates conditional-reveal hiding on it, so without this the reveals never
// collapse. js-enabled is kept for the older component styles.
document.body.className +=
  " js-enabled" +
  ("noModule" in HTMLScriptElement.prototype ? " govuk-frontend-supported" : "");
