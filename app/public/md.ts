// Markdown to sanitized HTML with KaTeX math. Math is cut out before
// marked runs, so `_` and `*` in formulas never become emphasis.

import { marked } from 'marked';
import DOMPurify from 'dompurify';
import renderMathInElement from 'katex-auto-render';

const MATH = /\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^\s$](?:[^$\n]*?[^\s$])?\$/g;
const DELIMITERS = [
  { left: '$$', right: '$$', display: true },
  { left: '\\[', right: '\\]', display: true },
  { left: '\\(', right: '\\)', display: false },
  { left: '$', right: '$', display: false },
];

const escape = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

export function md(text: string, inline = false): HTMLElement {
  const maths: string[] = [];
  const source = String(text ?? '').replace(MATH, (m) => `MATHPH${maths.push(m) - 1}END`);
  const html = (inline ? marked.parseInline(source) : marked.parse(source, { breaks: true })) as string;
  const el = document.createElement(inline ? 'span' : 'div');
  el.className = 'md';
  el.innerHTML = DOMPurify.sanitize(html.replace(/MATHPH(\d+)END/g, (_, i) => escape(maths[Number(i)])));
  renderMathInElement(el, { delimiters: DELIMITERS, throwOnError: false });
  return el;
}
