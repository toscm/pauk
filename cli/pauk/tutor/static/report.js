// "Report a problem" dialog (docs/tutor.md 16.1).

import { post } from './api.js';
import { h, showError, toast } from './ui.js';

const CATEGORIES = [['bug', 'Bug: something broke'], ['content', 'Content: wrong gloss, bad distractor, duplicate'],
                    ['teacher', 'Teacher: unfair grading, ignored a setting'], ['ux', 'UX: confusing or missing'], ['idea', 'Idea']];

export function reportDialog() {
  const about = h('p', {class: 'muted small'});
  const category = h('select', {id: 'report-category'}, CATEGORIES.map(([value, label]) => h('option', {value}, label)));
  const text = h('textarea', {id: 'report-text', rows: 5, required: true, maxlength: 20000});
  const context = h('input', {type: 'checkbox', id: 'report-context', checked: true});
  const send = h('button', {type: 'submit'}, 'Send report');
  let seq = null;

  const dialog = h('dialog', {class: 'report', 'aria-labelledby': 'report-title'},
    h('form', {},
      h('h2', {id: 'report-title'}, 'Report a problem'),
      about,
      h('div', {class: 'field'}, h('label', {for: 'report-category'}, 'Category'), category),
      h('div', {class: 'field'}, h('label', {for: 'report-text'}, 'What happened?'), text),
      h('div', {class: 'field check'}, context, h('label', {for: 'report-context'}, 'Attach the session context')),
      h('div', {class: 'buttons'}, send, h('button', {type: 'button', class: 'secondary', onclick: () => dialog.close()}, 'Cancel'))));

  dialog.querySelector('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    send.disabled = true;
    try {
      const result = await post('learner/report', {category: category.value, text_md: text.value.trim(),
                                                    seq, include_context: context.checked});
      toast(`Thanks. Report stored ${result.stored === 'api' ? 'on the server' : 'locally'}.`);
      text.value = '';
      dialog.close();
    } catch (error) {
      showError(error);
    } finally {
      send.disabled = false;
    }
  });
  document.body.append(dialog);

  return {
    open(forSeq = null) {
      seq = forSeq;
      about.textContent = seq ? `About transcript entry #${seq}.` : 'About the session in general.';
      dialog.showModal();
      text.focus();
    },
  };
}
