// HTTP access to the session host. The page lives at /s/<sid>/, so
// every path is relative to it. Learner key from `#k=`, observer key
// from `?observer=`.

import { t } from './i18n.js';

const search = new URLSearchParams(location.search);
export const observerKey = search.get('observer');
export const learnerKey = new URLSearchParams(location.hash.slice(1)).get('k');

export class HostError extends Error {
  constructor(status, code, message, data = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

export async function call(method, path, body) {
  const headers = observerKey ? {Authorization: `Bearer ${observerKey}`} : {'X-Pauk-Key': learnerKey || ''};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch(`api/${path}`, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)});
  } catch {
    throw new HostError(0, 'network', t('app.unreachable'));
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = data.error || {};
    throw new HostError(response.status, error.code || `http_${response.status}`,
                        error.message || data.detail || response.statusText, data);
  }
  return data;
}

export const get = (path) => call('GET', path);
export const post = (path, body = {}) => call('POST', path, body);
export const patch = (path, body) => call('PATCH', path, body);

export function eventsUrl(after) {
  return `api/learner/events?k=${encodeURIComponent(learnerKey || '')}&after=${after}`;
}
