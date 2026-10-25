// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#ifdef ARDUINO
#include <pgmspace.h>
#endif

namespace platinum {
namespace web {
static const char Page[]
#ifdef ARDUINO
    PROGMEM
#endif
    = R"PLATINUM_HTML(<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="referrer" content="no-referrer">
<title>Platinum gateway</title>
<style>
:root{font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#202834;background:#f4f5f7;font-synthesis:none;--muted:#68717e;--line:#dfe3e8;--accent:#375b9a;--accent-light:#edf2fb}
*{box-sizing:border-box}body{margin:0}button,input{font:inherit}button,input[type=password]{border:1px solid var(--line);border-radius:9px}button{background:#fff;color:#263344;padding:10px 15px;cursor:pointer;font-weight:600;min-height:42px}button:hover:not(:disabled){background:#f0f3f7}button.primary{background:var(--accent);color:white;border-color:var(--accent)}button.primary:hover:not(:disabled){background:#28487f}button:disabled{opacity:.45;cursor:default}button:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid #92b3ed;outline-offset:3px}a{color:var(--accent)}.wrap{max-width:1000px;margin:auto;padding:38px 24px 50px}.top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:28px}h1{font-size:30px;letter-spacing:-.035em;font-weight:650;margin:0}.connection{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted);padding-top:9px;white-space:nowrap}.dot{height:8px;width:8px;border-radius:50%;background:#9ca3ad}.connection.connected .dot{background:#27865a}.connection.working .dot{background:#ba7c21}.auth{display:flex;gap:10px;align-items:end;padding:20px;background:#fff;border:1px solid var(--line);border-radius:14px;margin-bottom:20px}.field{flex:1;min-width:0}.field label{display:block;font-size:13px;font-weight:650;margin-bottom:7px}.field input{width:100%;padding:11px 12px;background:#fafbfc;min-height:43px}.auth-controls{display:flex;gap:8px}.notice{font-size:14px;line-height:1.5;border-radius:10px;padding:12px 15px;margin:0 0 20px;background:var(--accent-light);border:1px solid #d4def0;color:#304c79}.notice.error{background:#fff2ed;border-color:#f0d3c5;color:#8b3827}.notice:empty{display:none}.room{margin-bottom:22px}.room-heading{font-size:16px;font-weight:650;display:flex;align-items:center;gap:10px;margin:0 0 10px 3px}.room-count{font-size:12px;color:var(--muted);font-weight:400}.shade-list{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}.shade{display:grid;grid-template-columns:minmax(150px,1fr) minmax(230px,1.5fr) auto;gap:25px;align-items:center;padding:21px 23px}.shade+.shade{border-top:1px solid var(--line)}.shade-name{font-size:15px;font-weight:650;overflow-wrap:anywhere;margin:0}.shade-controls{min-width:0}.range-heading{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);gap:10px;margin-bottom:8px}.range-value{font-weight:650;color:#354a69;font-variant-numeric:tabular-nums}.range{display:block;width:100%;margin:0;height:24px;accent-color:var(--accent);cursor:pointer}.range:disabled{opacity:.5;cursor:default}.ends{display:flex;justify-content:space-between;margin-top:3px;color:#9299a2;font-size:11px}.shade-actions{display:flex;align-items:center;gap:7px;flex-wrap:wrap;max-width:220px}.shade-actions button{font-size:12px;padding:9px 12px;min-height:37px}.shade-actions .apply{min-width:78px}.secondary-actions{display:flex;gap:7px;flex-basis:100%;justify-content:flex-end}.secondary-actions button{border-color:transparent;background:transparent;color:var(--muted);padding:4px 8px;min-height:30px;font-weight:500}.empty{text-align:center;padding:57px 20px;background:#fff;border:1px dashed #d3d9e1;border-radius:14px;color:var(--muted);font-size:14px;line-height:1.7}.settings{margin-top:30px;border-top:1px solid var(--line);padding-top:18px}.settings summary{font-size:14px;font-weight:650;cursor:pointer;padding:4px 0;width:fit-content}.settings-body{max-width:620px;padding-top:12px}.setting{display:flex;justify-content:space-between;align-items:center;gap:25px;padding:13px 0}.setting-label{font-size:14px;font-weight:550}.switch{appearance:none;flex:none;width:42px;height:24px;border-radius:20px;background:#b6bdc7;position:relative;cursor:pointer;margin:0}.switch:before{content:"";position:absolute;left:3px;top:3px;width:18px;height:18px;border-radius:50%;background:#fff;box-shadow:0 1px 3px #0002;transition:transform .15s}.switch:checked{background:var(--accent)}.switch:checked:before{transform:translateX(18px)}.switch:disabled{opacity:.5;cursor:default}.settings-footer{display:flex;align-items:center;gap:16px;margin-top:9px}.settings-warning{font-size:12px;line-height:1.5;color:#8b3827;margin:0;max-width:370px}.hidden{display:none!important}
@media(max-width:720px){.wrap{padding:25px 16px 35px}.top{margin-bottom:22px;gap:10px}h1{font-size:26px}.connection{font-size:12px}.shade{grid-template-columns:1fr 1.45fr;gap:16px;padding:19px}.shade-actions{grid-column:1/-1;max-width:none;justify-content:flex-end}.secondary-actions{flex-basis:auto}.auth{padding:16px;flex-wrap:wrap}.auth-controls{padding-top:0}.field{flex-basis:100%}.settings-footer{align-items:flex-start}}
@media(max-width:430px){.shade{grid-template-columns:1fr;gap:14px}.shade-actions{justify-content:flex-start}.secondary-actions{margin-left:auto}.connection{padding-top:7px}.top{flex-wrap:wrap}.auth-controls{width:100%}.auth-controls .primary{flex:1}.settings-footer{flex-direction:column;gap:10px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<div class="wrap">
<header class="top"><h1>Platinum gateway</h1><div class="connection" id="connection"><span class="dot" aria-hidden="true"></span><span id="connection-text">Not connected</span></div></header>
<form class="auth" id="auth-form">
  <div class="field"><label for="token">Access token</label><input id="token" type="password" placeholder="Enter your API token" autocomplete="off" spellcheck="false" autocapitalize="none" required></div>
  <div class="auth-controls"><button class="primary" id="connect" type="submit">Connect</button><button class="hidden" id="disconnect" type="button">Disconnect</button></div>
</form>
<p class="notice" id="notice" role="status" aria-live="polite"></p>
<main id="rooms" aria-label="Shades by room"><div class="empty">Connect to view shades.</div></main>
<details class="settings hidden" id="settings"><summary>Gateway services</summary><form class="settings-body" id="settings-form">
  <label class="setting" for="tcp-setting"><span class="setting-label">Original app (TCP 522)</span><input class="switch" type="checkbox" id="tcp-setting"></label>
  <label class="setting" for="http-setting"><span class="setting-label">Web interface and API</span><input class="switch" type="checkbox" id="http-setting"></label>
  <div class="settings-footer"><button type="submit" id="save-settings" disabled>Save settings</button><p class="settings-warning hidden" id="settings-warning">Saving will disconnect this page and disable the API. Re-enable HTTP over USB to reconnect.</p></div>
</form></details>
</div>
<script>
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const ui = {form:$('auth-form'),token:$('token'),connect:$('connect'),disconnect:$('disconnect'),connection:$('connection'),connectionText:$('connection-text'),notice:$('notice'),rooms:$('rooms'),settings:$('settings'),settingsForm:$('settings-form'),tcp:$('tcp-setting'),http:$('http-setting'),save:$('save-settings'),warning:$('settings-warning')};
  let token = '', connected = false, connecting = false, actionPending = false;
  let pollTimer = null, polling = false, pollCount = 0, failures = 0, session = 0;
  let shades = [], services = {tcp522:false,http:true,web:true};
  let settingsDirty = false, settingsSaving = false, expectedOperation = '', lastOperation = '';
  const drafts = new Map();

  function notice(message = '', error = false) {
    ui.notice.textContent = message;
    ui.notice.classList.toggle('error', error);
  }
  function connection(text, working = false) {
    ui.connectionText.textContent = text;
    ui.connection.classList.toggle('connected', connected && !working);
    ui.connection.classList.toggle('working', working);
  }
  function controlAvailability() {
    ui.rooms.querySelectorAll('[data-control]').forEach(element => {
      element.disabled = !connected || actionPending || element.dataset.allowed !== 'true';
    });
    ui.tcp.disabled = ui.http.disabled = !connected || settingsSaving;
    ui.save.disabled = !connected || !settingsDirty || settingsSaving;
  }
  function stopPolling() {
    if (pollTimer !== null) window.clearInterval(pollTimer);
    pollTimer = null;
  }
  function disconnect(message) {
    ++session; stopPolling(); token = ''; connected = connecting = false;
    actionPending = settingsSaving = false; expectedOperation = '';
    ui.token.value = ''; ui.token.required = true; ui.token.disabled = false;
    ui.token.placeholder = 'Enter your API token';
    ui.connect.disabled = false; ui.connect.textContent = 'Connect';
    ui.disconnect.classList.add('hidden'); connection('Not connected');
    controlAvailability(); if (message) notice(message);
  }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 6000);
    try {
      const headers = {'Authorization':'Bearer ' + token, 'Accept':'application/json'};
      if (options.body !== undefined) headers['Content-Type'] = 'application/json';
      const response = await fetch(path, {method:options.method || 'GET',headers,
        body:options.body === undefined ? undefined : JSON.stringify(options.body),
        cache:'no-store',credentials:'omit',redirect:'error',signal:controller.signal});
      let value;
      try { value = await response.json(); } catch (_) { throw new Error('The gateway returned an unreadable response.'); }
      if (!response.ok) {
        if (response.status === 401) throw new Error('The access token was not accepted.');
        if (response.status === 409) throw new Error('The gateway could not accept this request. Check that control is enabled and no other action is running.');
        throw new Error('The gateway rejected this request (' + response.status + ').');
      }
      return value;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('The gateway did not reply in time. Check its state before sending the command again.');
      if (error instanceof TypeError) throw new Error('The gateway is unreachable. Check the connection before sending the command again.');
      throw error;
    } finally { window.clearTimeout(timer); }
  }
  function textElement(tag, className, text) {
    const element = document.createElement(tag); element.className = className;
    element.textContent = text; return element;
  }
  function hasFeature(shade, bit) {
    return Number.isInteger(shade.features) && (shade.features & (1 << bit)) !== 0;
  }
  function positionLabel(value) { return Math.round(value * 100 / 255) + '% open'; }
  function actionButton(label, accessible, allowed, callback, className = '') {
    const button = textElement('button', className, label);
    button.type = 'button'; button.setAttribute('aria-label', accessible);
    button.dataset.control = 'true'; button.dataset.allowed = String(allowed);
    button.addEventListener('click', callback); return button;
  }
  function renderShades() {
    // Preserve an in-progress range interaction and its keyboard focus on refresh.
    if (ui.rooms.contains(document.activeElement) && document.activeElement.type === 'range') return;
    const fragment = document.createDocumentFragment(), grouped = new Map();
    for (const shade of shades) {
      if (!Number.isInteger(shade.id) || shade.id < 0 || shade.id >= 100) continue;
      const key = String(shade.room_id);
      if (!grouped.has(key)) grouped.set(key, {name:String(shade.room || 'Room'),shades:[]});
      grouped.get(key).shades.push(shade);
    }
    if (!grouped.size) {
      fragment.append(textElement('div', 'empty', 'No shades configured.'));
    }
    for (const room of grouped.values()) {
      const section = document.createElement('section'); section.className = 'room';
      const heading = textElement('h2', 'room-heading', room.name);
      heading.append(textElement('span', 'room-count', String(room.shades.length)));
      const list = document.createElement('div'); list.className = 'shade-list';
      for (const shade of room.shades) {
        const shadeName = String(shade.name || 'Shade'), row = document.createElement('article'); row.className = 'shade';
        const title = document.createElement('div'); title.append(textElement('h3','shade-name',shadeName));
        const reported = Number.isInteger(shade.position) && shade.position >= 0 && shade.position <= 255 ? shade.position : null;
        const primary = shade.enabled === true && hasFeature(shade,4);
        const controls = document.createElement('div'); controls.className = 'shade-controls';
        const rangeHeading = textElement('div','range-heading','Set position');
        const initial = drafts.has(shade.id) ? drafts.get(shade.id) : reported === null ? 128 : reported;
        const valueLabel = textElement('span','range-value',positionLabel(initial)); rangeHeading.append(valueLabel);
        const range = document.createElement('input'); range.type = 'range'; range.min = '0'; range.max = '255'; range.step = '1'; range.value = String(initial); range.className = 'range';
        range.setAttribute('aria-label',shadeName + ' requested position'); range.setAttribute('aria-valuetext',positionLabel(initial)); range.dataset.control = 'true'; range.dataset.allowed = String(primary);
        range.addEventListener('input',() => { const value = Number(range.value); drafts.set(shade.id,value); valueLabel.textContent = positionLabel(value); range.setAttribute('aria-valuetext',positionLabel(value)); });
        const ends = document.createElement('div'); ends.className = 'ends'; ends.append(textElement('span','','Closed'),textElement('span','','Open'));
        controls.append(rangeHeading,range,ends);
        const actions = document.createElement('div'); actions.className = 'shade-actions';
        actions.append(actionButton('Set', 'Set requested position for ' + shadeName, primary, () => sendAction('/api/positions',{shade:shade.id,position:Number(range.value)},shade.id),'primary apply'));
        actions.append(actionButton('Close', 'Close ' + shadeName, primary, () => sendAction('/api/positions',{shade:shade.id,position:0},shade.id)));
        actions.append(actionButton('Open', 'Open ' + shadeName, primary, () => sendAction('/api/positions',{shade:shade.id,position:255},shade.id)));
        if (hasFeature(shade,1) || hasFeature(shade,12)) {
          const extra = document.createElement('div'); extra.className = 'secondary-actions';
          if (hasFeature(shade,12)) extra.append(actionButton('Jog','Jog ' + shadeName,true,() => sendAction('/api/jog',{shade:shade.id},shade.id)));
          if (hasFeature(shade,1)) extra.append(actionButton('Sync','Sync ' + shadeName,true,() => sendAction('/api/sync',{shade:shade.id},shade.id)));
          actions.append(extra);
        }
        row.append(title,controls,actions); list.append(row);
      }
      section.append(heading,list); fragment.append(section);
    }
    ui.rooms.replaceChildren(fragment); controlAvailability();
  }
  async function refreshShades(current = session) {
    const response = await api('/api/shades'); if (current !== session) return;
    if (!Array.isArray(response.shades)) throw new Error('The gateway returned an unreadable shade list.');
    shades = response.shades; renderShades();
  }
  function applySettings(value) {
    services = {tcp522:value.tcp522 === true,http:value.http === true,web:value.web === true};
    if (!settingsDirty) { ui.tcp.checked = services.tcp522; ui.http.checked = services.http; }
    ui.warning.classList.toggle('hidden',ui.http.checked);
    ui.settings.classList.remove('hidden'); controlAvailability();
  }
  function requestId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return 'web-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2,14);
  }
  function operationMessage(status) {
    if (status === 'failed') return 'The command did not complete. Check the gateway and shade before trying again.';
    if (status === 'cancelled' || status === 'rejected') return 'The command was cancelled or rejected. Check the gateway before trying again.';
    return 'Request accepted.';
  }
  const terminal = status => ['simulated','failed','completed_unverified','completed','cancelled','rejected'].includes(status);
  async function sendAction(path, body, shadeId) {
    if (!connected || actionPending) return;
    const current = session, id = requestId(); actionPending = true; expectedOperation = id;
    controlAvailability(); connection('Sending request',true); notice('Sending your request…');
    try {
      const response = await api(path,{method:'POST',body:{...body,request_id:id}}); if (current !== session) return;
      const operation = response.operation || {}, status = operation.status || response.status || 'submitted';
      expectedOperation = String(operation.id || response.request_id || id);
      actionPending = !terminal(status); drafts.delete(shadeId);
      notice(operationMessage(status),status === 'failed'); connection(actionPending ? 'Action in progress' : 'Connected',actionPending);
      await refreshShades(current);
    } catch (error) {
      if (current !== session) return;
      actionPending = false; expectedOperation = ''; connection('Connected'); notice(error.message,true);
    } finally { if (current === session) controlAvailability(); }
  }
  async function poll() {
    if (!connected || polling || settingsSaving) return;
    const current = session; polling = true;
    try {
      const response = await api('/api/status'); if (current !== session) return;
      failures = 0; ++pollCount;
      if (response.services && !settingsDirty) applySettings(response.services);
      const operation = response.operation || {}, key = String(operation.id || '') + ':' + String(operation.status || '');
      if (expectedOperation && String(operation.id) === expectedOperation) {
        actionPending = !terminal(operation.status); notice(operationMessage(operation.status),operation.status === 'failed');
        connection(actionPending ? 'Action in progress' : 'Connected',actionPending);
        if (!actionPending) expectedOperation = '';
      } else if (operation.id && ['submitted','running','queued'].includes(operation.status)) {
        actionPending = true; connection('Action in progress',true);
      } else if (terminal(operation.status)) {
        if (actionPending && expectedOperation) notice('The gateway is ready. Check the last requested positions before sending another command.');
        actionPending = false; expectedOperation = ''; connection('Connected');
      }
      controlAvailability();
      if (key !== lastOperation || pollCount % 5 === 0) { lastOperation = key; await refreshShades(current); }
    } catch (error) {
      if (current !== session) return;
      if (++failures >= 3) { disconnect(); notice('Connection lost. Reconnect and check the last request before sending another command.',true); }
    } finally { polling = false; }
  }
  ui.form.addEventListener('submit',async event => {
    event.preventDefault(); if (connecting) return;
    const entered = ui.token.value.trim(); if (!entered && !token) return;
    stopPolling(); ++session; const current = session;
    token = entered || token; ui.token.value = ''; connecting = true; connected = false;
    ui.connect.disabled = true; connection('Connecting',true); notice(); controlAvailability();
    try {
      await refreshShades(current); const settings = await api('/api/settings'); if (current !== session) return;
      settingsDirty = false; connected = true; failures = pollCount = 0; expectedOperation = ''; actionPending = false;
      applySettings(settings); connection('Connected'); ui.token.required = false;
      ui.token.placeholder = 'Connected'; ui.connect.textContent = 'Refresh';
      ui.disconnect.classList.remove('hidden'); renderShades(); notice();
      pollTimer = window.setInterval(poll,2000); await poll();
    } catch (error) { if (current === session) { disconnect(); notice(error.message,true); } }
    finally { if (current === session) { connecting = false; ui.connect.disabled = false; } }
  });
  ui.disconnect.addEventListener('click',() => {
    disconnect('Disconnected.'); shades = []; drafts.clear();
    ui.rooms.replaceChildren(textElement('div','empty','Connect to view shades.'));
    ui.settings.classList.add('hidden');
  });
  function settingsChanged() {
    settingsDirty = ui.tcp.checked !== services.tcp522 || ui.http.checked !== services.http;
    ui.warning.classList.toggle('hidden',ui.http.checked); controlAvailability();
  }
  ui.tcp.addEventListener('change',settingsChanged); ui.http.addEventListener('change',settingsChanged);
  ui.settingsForm.addEventListener('submit',async event => {
    event.preventDefault(); if (!connected || settingsSaving || !settingsDirty) return;
    const current = session, next = {tcp522:ui.tcp.checked,http:ui.http.checked,web:services.web};
    settingsSaving = true; controlAvailability();
    try {
      await api('/api/settings',{method:'PATCH',body:next}); if (current !== session) return;
      settingsDirty = false; applySettings(next);
      if (!next.http) { disconnect('Web interface and API disabled. Re-enable HTTP over USB to reconnect.'); connection('HTTP disabled'); }
      else notice('Gateway service settings saved.');
    } catch (error) { if (current === session) notice(error.message,true); }
    finally { if (current === session) { settingsSaving = false; controlAvailability(); } }
  });
  window.addEventListener('pagehide',() => { token = ''; stopPolling(); });
  window.addEventListener('pageshow',event => { if (event.persisted) disconnect('Reconnect to continue.'); });
})();
</script>
</body>
</html>)PLATINUM_HTML";
}  // namespace web
}  // namespace platinum
