"""Best-effort translation opt-out; cannot repair already translated React nodes."""

TRANSLATION_GUARD_HTML = """
<script>
(() => {
  const root = document.documentElement;
  root.lang = 'ko';
  root.setAttribute('translate', 'no');
  root.classList.add('notranslate');
  for (const container of [document.body, document.getElementById('root')]) {
    if (container) {
      container.setAttribute('translate', 'no');
      container.classList.add('notranslate');
    }
  }
  let meta = document.head.querySelector('meta[name="google"]');
  if (!meta) {
    meta = document.createElement('meta');
    meta.name = 'google';
    document.head.appendChild(meta);
  }
  meta.content = 'notranslate';
})();
</script>
"""


def install_translation_guard(st):
    # Only this trusted constant executes; provider/user content must not enter it.
    st.html(TRANSLATION_GUARD_HTML, unsafe_allow_javascript=True)
