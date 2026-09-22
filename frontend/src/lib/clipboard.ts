// HTTP IP deployments do not expose navigator.clipboard in every browser.
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Try the user-initiated copy fallback when browser permissions deny it.
    }
  }
  const previous = document.activeElement;
  const selection = document.getSelection();
  const ranges = selection
    ? Array.from({ length: selection.rangeCount }, (_, i) =>
        selection.getRangeAt(i),
      )
    : [];
  const field = document.createElement("textarea");
  field.value = text;
  field.readOnly = true;
  field.style.cssText = "position:fixed;left:-9999px;top:0;";
  document.body.appendChild(field);
  try {
    field.select();
    if (!document.execCommand("copy")) {
      throw new Error("浏览器未允许复制，请选中建议文字后手动复制。");
    }
  } finally {
    field.remove();
    if (previous instanceof HTMLElement)
      previous.focus({ preventScroll: true });
    selection?.removeAllRanges();
    ranges.forEach((range) => selection?.addRange(range));
  }
}
