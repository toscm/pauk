// Markdown rendering: marked -> DOMPurify -> KaTeX auto-render.
// Math is cut out before marked runs, so `_` and `*` inside formulas
// are not turned into emphasis, and put back as plain text afterwards.

import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12.0.2/lib/marked.esm.js';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.es.mjs';
import renderMathInElement from 'https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.mjs';

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node.getAttribute('href')) {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
});

const MATH = /\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^\s$](?:[^$\n]*?[^\s$])?\$/g;

const KATEX = {
  delimiters: [
    {left: '$$', right: '$$', display: true},
    {left: '\\[', right: '\\]', display: true},
    {left: '\\(', right: '\\)', display: false},
    {left: '$', right: '$', display: false},
  ],
  throwOnError: false,
};

function escapeHtml(text) {
  return text.replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);
}

function toHtml(text, inline) {
  const maths = [];
  const source = String(text ?? '').replace(MATH, (m) => `MATHPH${maths.push(m) - 1}END`);
  const html = inline ? marked.parseInline(source) : marked.parse(source, {breaks: true});
  return DOMPurify.sanitize(html.replace(/MATHPH(\d+)END/g, (_, i) => escapeHtml(maths[Number(i)])));
}

// A rendered element (div for blocks, span for inline markdown).
export function md(text, inline = false) {
  const el = document.createElement(inline ? 'span' : 'div');
  el.className = inline ? 'md-inline' : 'md';
  el.innerHTML = toHtml(text, inline);
  renderMathInElement(el, KATEX);
  return el;
}

// Plain text of inline markdown, for places that cannot hold HTML (<option>).
export function plain(text) {
  const el = document.createElement('div');
  el.innerHTML = toHtml(text, true);
  return el.textContent;
}
