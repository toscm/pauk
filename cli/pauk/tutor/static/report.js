// "Report a problem" dialog (docs/tutor.md 16.1).

import { post } from './api.js';
import { t } from './i18n.js';
import { h, showError, toast } from './ui.js';

const categories = () => [['bug', t('report.category.bug')], ['content', t('report.category.content')],
                          ['teacher', t('report.category.teacher')], ['ux', t('report.category.ux')],
                          ['idea', t('report.category.idea')]];

export function reportDialog() {
  const about = h('p', {class: 'muted small'});
  const category = h('select', {id: 'report-category'}, categories().map(([value, label]) => h('option', {value}, label)));
  const text = h('textarea', {id: 'report-text', rows: 5, required: true, maxlength: 20000});
  const context = h('input', {type: 'checkbox', id: 'report-context', checked: true});
  const send = h('button', {type: 'submit'}, t('report.send'));
  let seq = null;

  const dialog = h('dialog', {class: 'report', 'aria-labelledby': 'report-title'},
    h('form', {},
      h('h2', {id: 'report-title'}, t('report.title')),
      about,
      h('div', {class: 'field'}, h('label', {for: 'report-category'}, t('report.category')), category),
      h('div', {class: 'field'}, h('label', {for: 'report-text'}, t('report.what')), text),
      h('div', {class: 'field check'}, context, h('label', {for: 'report-context'}, t('report.context'))),
      h('div', {class: 'buttons'}, send, h('button', {type: 'button', class: 'secondary', onclick: () => dialog.close()}, t('settings.cancel')))));

  dialog.querySelector('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    send.disabled = true;
    try {
      const result = await post('learner/report', {category: category.value, text_md: text.value.trim(),
                                                    seq, include_context: context.checked});
      toast(result.stored === 'api' ? t('report.thanks_server') : t('report.thanks_local'));
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
      about.textContent = seq ? t('report.about_entry', {seq}) : t('report.about_session');
      dialog.showModal();
      text.focus();
    },
  };
}
