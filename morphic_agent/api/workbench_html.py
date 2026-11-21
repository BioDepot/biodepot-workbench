"""Prototype-shaped HTML workbench for the morphic_agent walking skeleton."""

WORKBENCH_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BioDepot Workbench</title>
  <style>
    :root {
      --bg: #f4f6f7;
      --panel: #ffffff;
      --panel-alt: #eef2f3;
      --line: #ced7dc;
      --text: #1b242b;
      --muted: #60707a;
      --accent: #0f766e;
      --accent-2: #1d4ed8;
      --warn: #9a5f00;
      --bad: #b42318;
      --good: #0f766e;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
    }
    header {
      height: 54px;
      padding: 0 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 680;
      letter-spacing: 0;
    }
    .service {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--muted);
      font-size: 13px;
      min-width: 0;
    }
    .pill {
      border: 1px solid var(--line);
      background: var(--panel-alt);
      border-radius: 6px;
      min-height: 28px;
      display: inline-flex;
      align-items: center;
      padding: 0 9px;
      white-space: nowrap;
    }
    .session-user {
      max-width: min(320px, 36vw);
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .session-end {
      min-height: 28px;
      padding: 0 9px;
      color: var(--bad);
      border-color: #efb0aa;
      background: #fff7f6;
    }
    .session-end:hover {
      border-color: var(--bad);
      background: #fde8e6;
    }
    .app {
      display: grid;
      grid-template-columns: 270px minmax(460px, 1fr) 380px;
      gap: 0;
      height: calc(100vh - 54px);
      min-height: 0;
    }
    aside, main, .right {
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      border-right: 1px solid var(--line);
    }
    aside, .right {
      background: var(--panel);
      display: flex;
      flex-direction: column;
    }
    main {
      background: #fbfcfc;
      display: flex;
      flex-direction: column;
    }
    .rail {
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }
    .step {
      width: 100%;
      min-height: 38px;
      margin-bottom: 6px;
      padding: 0 10px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      border-radius: 6px;
      cursor: pointer;
      font-weight: 620;
    }
    .step.active {
      border-color: var(--text);
      background: var(--text);
      color: #fff;
    }
    .step.blocked {
      color: var(--muted);
      background: var(--panel-alt);
    }
    .dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--line);
      flex: 0 0 auto;
    }
    .step.ready .dot { background: var(--good); }
    .step.warn .dot { background: var(--warn); }
    .step small {
      display: block;
      color: inherit;
      opacity: 0.72;
      font-weight: 520;
      margin-top: 2px;
    }
    .state {
      padding: 12px;
      display: grid;
      grid-template-columns: 88px minmax(0, 1fr);
      gap: 7px 10px;
      color: var(--muted);
      font-size: 13px;
      border-bottom: 1px solid var(--line);
    }
    .state strong {
      color: var(--text);
      font-weight: 560;
      overflow-wrap: anywhere;
    }
    .conversation-manager {
      min-height: 0;
      flex: 1;
      display: flex;
      flex-direction: column;
      border-bottom: 1px solid var(--line);
    }
    .conversation-head,
    .conversation-actions {
      min-height: 38px;
      padding: 6px 10px;
      display: flex;
      align-items: center;
      gap: 6px;
      border-bottom: 1px solid var(--line);
    }
    .conversation-head strong {
      margin-right: auto;
      font-size: 13px;
    }
    .conversation-head button,
    .conversation-actions button {
      min-height: 28px;
      padding: 0 8px;
      font-size: 12px;
    }
    .conversation-filters {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 86px;
      gap: 6px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
    }
    .conversation-filters input,
    .conversation-filters select {
      min-height: 32px;
      padding: 6px 8px;
      font: 12px Inter, ui-sans-serif, system-ui, sans-serif;
    }
    .conversation-list {
      min-height: 90px;
      overflow: auto;
      flex: 1;
    }
    .conversation-item {
      width: 100%;
      min-height: 48px;
      padding: 7px 10px;
      border: 0;
      border-bottom: 1px solid #e6eaed;
      border-radius: 0;
      background: var(--panel);
      color: var(--text);
      text-align: left;
      display: block;
    }
    .conversation-item:hover { background: #f6f9fa; }
    .conversation-item.active {
      box-shadow: inset 3px 0 0 var(--accent);
      background: #eef8f6;
    }
    .conversation-title {
      display: block;
      font-weight: 650;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .conversation-meta {
      display: block;
      margin-top: 3px;
      color: var(--muted);
      font-size: 11px;
    }
    .conversation-empty {
      padding: 12px 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .conversation-actions {
      border-top: 1px solid var(--line);
      border-bottom: 0;
      flex-wrap: wrap;
    }
    .conversation-actions span {
      width: 100%;
      color: var(--muted);
      font-size: 11px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .pane {
      display: none;
      flex: 1;
      min-height: 0;
      padding: 14px;
      overflow: auto;
    }
    .pane.active {
      display: block;
    }
    .panel {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      margin-bottom: 14px;
      overflow: hidden;
    }
    .panel-head {
      height: 42px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 0 12px;
      border-bottom: 1px solid var(--line);
      font-weight: 680;
    }
    .panel-tools {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-left: auto;
      flex: 0 0 auto;
    }
    .panel-tools button {
      min-height: 28px;
      padding: 0 8px;
      font-size: 12px;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    .panel-body {
      padding: 12px;
    }
    .empty {
      color: var(--muted);
      border: 1px dashed var(--line);
      background: #fbfcfd;
      border-radius: 6px;
      padding: 12px;
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .summary-card {
      border: 1px solid var(--line);
      background: #fbfcfd;
      border-radius: 6px;
      padding: 10px;
      min-width: 0;
    }
    .summary-card h3 {
      margin: 0 0 6px;
      font-size: 13px;
      letter-spacing: 0;
    }
    .summary-card p {
      margin: 0;
      color: var(--muted);
      line-height: 1.4;
    }
    .module-list {
      display: grid;
      gap: 8px;
    }
    .module-card {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: start;
      border: 1px solid #e0e7eb;
      background: #fff;
      border-radius: 6px;
      padding: 10px;
    }
    .module-title {
      font-weight: 680;
      overflow-wrap: anywhere;
    }
    .module-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 3px;
      overflow-wrap: anywhere;
    }
    .badge {
      border: 1px solid var(--line);
      background: var(--panel-alt);
      color: var(--muted);
      border-radius: 999px;
      padding: 2px 7px;
      font-size: 12px;
      white-space: nowrap;
    }
    .detail-view {
      display: grid;
      gap: 10px;
      overflow: auto;
      min-height: 0;
    }
    .detail-section {
      border-bottom: 1px solid #e6eaed;
      padding-bottom: 10px;
    }
    .detail-section:last-child {
      border-bottom: 0;
      padding-bottom: 0;
    }
    .detail-section h3 {
      margin: 0 0 6px;
      font-size: 13px;
    }
    .detail-section ul {
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
    }
    .detail-section li {
      margin: 3px 0;
    }
    label {
      display: block;
      margin: 0 0 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 680;
      text-transform: uppercase;
    }
    textarea, input, select, pre {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      color: var(--text);
      font: 13px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    textarea, input, select {
      padding: 9px 10px;
    }
    textarea {
      min-height: 96px;
      resize: vertical;
    }
    pre {
      margin: 0;
      min-height: 170px;
      padding: 12px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .row {
      display: grid;
      grid-template-columns: minmax(130px, 210px) minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 10px 0;
      border-bottom: 1px solid #e6eaed;
    }
    .row:last-child { border-bottom: 0; }
    .row.advanced-param {
      background: #fbfcfd;
    }
    .param-group {
      border: 0;
      border-top: 1px solid var(--line);
      border-radius: 0;
      background: transparent;
      margin-bottom: 0;
      overflow: hidden;
    }
    .param-group:first-child { border-top: 0; }
    .param-group summary {
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
      background: transparent;
      border-bottom: 1px solid transparent;
      font-weight: 680;
    }
    .param-group[open] summary {
      border-bottom-color: var(--line);
    }
    .param-group-title {
      overflow-wrap: anywhere;
    }
    .param-group-meta {
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }
    .param-group-description {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
      padding: 8px 12px 0;
    }
    .param-group-body {
      padding: 0 12px;
    }
    .field-name {
      font-weight: 650;
      overflow-wrap: anywhere;
    }
    .field-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 3px;
    }
    .field-control {
      display: grid;
      gap: 7px;
      min-width: 0;
    }
    .checkbox-control {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
      font-size: 13px;
      font-weight: 600;
      text-transform: none;
      margin: 0;
    }
    .checkbox-control input[type="checkbox"] {
      width: auto;
      min-width: 16px;
      height: 16px;
    }
    .path-tools {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .path-tools button {
      min-height: 30px;
      padding: 0 9px;
      font-size: 12px;
    }
    .field-hint {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }
    button {
      min-height: 34px;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      border-radius: 6px;
      padding: 0 11px;
      font-weight: 650;
      cursor: pointer;
    }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    button.secondary {
      border-color: var(--accent-2);
      color: var(--accent-2);
    }
    .walkthrough-picker {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      min-width: 0;
    }
    #walkthroughSelect, #walkthroughActionMode {
      flex: 1 1 220px;
      width: auto;
      max-width: 100%;
      min-height: 34px;
      border: 1px solid #b45309;
      background: #fff7ed;
      color: #111827;
      border-radius: 6px;
      padding: 0 8px;
      font-weight: 650;
    }
    .walkthrough-mode {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      min-height: 34px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      white-space: nowrap;
    }
    .walkthrough-mode input {
      width: 14px;
      height: 14px;
      accent-color: var(--accent);
    }
    #quickDemoBtn {
      background: #f59e0b;
      border-color: #b45309;
      color: #111827;
      box-shadow: 0 1px 0 rgba(17, 24, 39, 0.14);
    }
    #quickDemoBtn:hover {
      background: #fbbf24;
      border-color: #92400e;
    }
    button:disabled {
      opacity: 0.52;
      cursor: not-allowed;
    }
    .gate-hint {
      flex-basis: 100%;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      min-height: 16px;
    }
    .run-section {
      margin-top: 14px;
    }
    .section-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 6px;
      text-transform: uppercase;
    }
    .log-panel {
      min-height: 150px;
      max-height: 260px;
      overflow: auto;
      background: #0f172a;
      color: #e5e7eb;
      border-color: #111827;
      font-size: 12px;
    }
    .artifact-list {
      display: grid;
      gap: 8px;
    }
    .artifact-item {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: #fbfcfd;
      display: grid;
      gap: 6px;
    }
    .artifact-name {
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .artifact-meta {
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .artifact-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .artifact-actions a {
      border: 1px solid var(--line);
      border-radius: 6px;
      color: var(--accent);
      font-weight: 700;
      min-height: 30px;
      padding: 6px 10px;
      text-decoration: none;
    }
    .message-log {
      min-height: 220px;
      max-height: 52vh;
      overflow: auto;
      border: 1px solid var(--line);
      background: #fbfcfd;
      border-radius: 6px;
      padding: 10px;
      display: grid;
      align-content: start;
      gap: 8px;
    }
    .msg {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 9px 10px;
      overflow-wrap: anywhere;
      line-height: 1.42;
    }
    .msg p {
      margin: 0 0 8px;
    }
    .msg p:last-child {
      margin-bottom: 0;
    }
    .msg ul {
      margin: 0 0 8px 18px;
      padding: 0;
    }
    .msg li {
      margin: 3px 0;
    }
    .msg code {
      font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: #e8eef1;
      border: 1px solid #d4dde2;
      border-radius: 4px;
      padding: 1px 4px;
    }
    .msg.user {
      border-color: #b7c7d8;
      background: #f4f8fb;
      white-space: pre-wrap;
    }
    .msg.agent {
      border-color: #bfd6d2;
      background: #f4faf8;
    }
    .msg.system {
      color: var(--muted);
      background: var(--panel-alt);
    }
    .msg.thinking {
      color: var(--muted);
      border-style: dashed;
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 42px;
    }
    .thinking-dots {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      flex: 0 0 auto;
    }
    .thinking-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent);
      animation: pulse 1s ease-in-out infinite;
    }
    .thinking-dot:nth-child(2) { animation-delay: 0.15s; }
    .thinking-dot:nth-child(3) { animation-delay: 0.3s; }
    @keyframes pulse {
      0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
      40% { opacity: 1; transform: translateY(-2px); }
    }
    .thinking-copy {
      min-width: 190px;
      font-weight: 620;
    }
    .thinking-verb {
      color: var(--accent);
    }
    .warn-text { color: var(--warn); }
    .bad-text { color: var(--bad); }
    .good-text { color: var(--good); }
    .helper-list {
      display: grid;
      gap: 6px;
      max-height: 120px;
      overflow: auto;
      margin-bottom: 10px;
    }
    .helper-item {
      text-align: left;
      min-height: 32px;
      font-weight: 560;
    }
    .tabs {
      display: flex;
      gap: 4px;
      min-width: 0;
      overflow-x: auto;
    }
    .tabs button {
      min-height: 28px;
      font-size: 12px;
      background: var(--panel-alt);
    }
    .tabs button.active {
      background: var(--text);
      border-color: var(--text);
      color: #fff;
    }
    .panel-workspace {
      position: fixed;
      inset: 54px 0 0 0;
      z-index: 40;
      display: flex;
      flex-direction: column;
      background: var(--bg);
      border-top: 1px solid var(--line);
    }
    .workspace-head {
      min-height: 46px;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    .workspace-title {
      font-weight: 700;
      white-space: nowrap;
    }
    .workspace-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-left: auto;
    }
    .expanded-mount {
      flex: 1;
      min-height: 0;
      overflow: auto;
      padding: 14px;
    }
    .expanded-mount > .panel {
      margin: 0;
      min-height: calc(100vh - 98px);
      display: flex;
      flex-direction: column;
    }
    .expanded-mount > .panel > .panel-body {
      flex: 1;
      min-height: 0;
    }
    .expanded-mount textarea#scriptEditor {
      min-height: calc(100vh - 220px);
    }
    .expanded-mount #messages {
      min-height: calc(100vh - 330px);
    }
    .modal {
      position: fixed;
      inset: 0;
      z-index: 80;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(15, 23, 42, 0.34);
      padding: 18px;
    }
    .modal-card {
      width: min(920px, 100%);
      max-height: min(760px, 90vh);
      display: flex;
      flex-direction: column;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: 0 18px 45px rgba(15, 23, 42, 0.22);
      overflow: hidden;
    }
    .modal-head {
      min-height: 46px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 12px;
      border-bottom: 1px solid var(--line);
      font-weight: 700;
    }
    .file-browser-body {
      padding: 12px;
      display: grid;
      gap: 10px;
      min-height: 0;
      overflow: auto;
    }
    .diagnostic-body {
      padding: 12px;
      display: grid;
      gap: 10px;
      min-height: 0;
      overflow: auto;
    }
    .review-form {
      display: grid;
      gap: 10px;
    }
    .review-form label {
      display: grid;
      gap: 4px;
      font-size: 13px;
      font-weight: 700;
    }
    .review-form .check-row {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      font-weight: 600;
    }
    .review-form textarea,
    .review-form select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: #fff;
      color: var(--text);
    }
    .diagnostic-body pre {
      max-height: 60vh;
      white-space: pre-wrap;
      overflow: auto;
    }
    .file-browser-path {
      border: 1px solid var(--line);
      background: #fbfcfd;
      border-radius: 6px;
      padding: 8px 10px;
      font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      overflow-wrap: anywhere;
    }
    .file-browser-roots {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .file-browser-roots button {
      min-height: 28px;
      font-size: 12px;
    }
    .file-browser-entries {
      display: grid;
      gap: 6px;
      min-height: 180px;
      max-height: 390px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      padding: 8px;
    }
    .file-entry {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      border: 1px solid #dbe4e8;
      background: #fff;
      border-radius: 6px;
      padding: 7px 8px;
    }
    .file-entry.selected {
      border-color: var(--accent);
      box-shadow: inset 0 0 0 1px var(--accent);
    }
    .file-entry-name {
      font-weight: 650;
      overflow-wrap: anywhere;
    }
    .file-entry-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
      overflow-wrap: anywhere;
    }
    .file-entry-actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .file-entry-actions button {
      min-height: 28px;
      padding: 0 8px;
      font-size: 12px;
    }
    .hidden { display: none; }
    details.advanced {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      overflow: hidden;
    }
    details.advanced summary {
      cursor: pointer;
      padding: 10px 12px;
      font-weight: 680;
      background: var(--panel-alt);
      border-bottom: 1px solid transparent;
    }
    details.advanced[open] summary {
      border-bottom-color: var(--line);
    }
    .advanced-body {
      display: grid;
      gap: 12px;
      padding: 12px;
      overflow: auto;
      max-height: calc(100vh - 170px);
    }
    #helperEditor {
      min-height: 100px;
      flex: 1;
    }
    .right .panel {
      border: 0;
      border-radius: 0;
      margin: 0;
      border-bottom: 1px solid var(--line);
      min-height: 0;
      display: flex;
      flex-direction: column;
    }
    .right .panel:nth-child(1) { flex: 1.1 1 0; }
    .right .panel:nth-child(2) { flex: 1 1 0; }
    .right .panel .panel-body {
      min-height: 0;
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .right pre {
      min-height: 0;
      flex: 1;
      overflow: auto;
    }
    @media (max-width: 1180px) {
      .app {
        grid-template-columns: 230px minmax(0, 1fr);
      }
      .right {
        grid-column: 1 / -1;
        border-top: 1px solid var(--line);
      }
    }
    @media (max-width: 760px) {
      header {
        height: auto;
        padding: 10px 12px;
        align-items: flex-start;
        flex-direction: column;
        gap: 8px;
      }
      .app {
        grid-template-columns: 1fr;
        height: auto;
        min-height: calc(100vh - 54px);
      }
      aside, main, .right {
        border-right: 0;
        border-bottom: 1px solid var(--line);
        overflow: visible;
      }
      .conversation-manager {
        flex: 0 0 auto;
      }
      .conversation-list {
        flex: 0 1 auto;
        max-height: 240px;
      }
      .row {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>BioDepot Workbench</h1>
    <div class="service">
      <span id="sessionUser" class="pill session-user" title="Authenticated workbench user">user unknown</span>
      <button id="clearWorkbenchBtn" class="session-end" type="button" title="Clear the current graph, chat, parameters, script, diagnostics, and run state without signing out.">Clear Workbench</button>
      <button id="logoutBtn" class="session-end" type="button" title="Clear this browser session and return to the workbench landing page.">End Session</button>
      <span id="status" class="pill">starting</span>
      <span id="service" class="pill">service</span>
    </div>
  </header>

  <div class="app">
    <aside>
      <div class="rail">
        <button class="step active ready" data-pane="chat"><span>Discuss</span><span class="dot"></span></button>
        <button class="step blocked" data-pane="plan"><span>Review Plan</span><span class="dot"></span></button>
        <button class="step blocked" data-pane="params"><span>Fill + Approve</span><span class="dot"></span></button>
        <button class="step blocked" data-pane="script"><span>Review Script</span><span class="dot"></span></button>
        <button class="step blocked" data-pane="run"><span>Run</span><span class="dot"></span></button>
      </div>
      <div class="state">
        <span>Workflow</span><strong id="workflowState">none</strong>
        <span>Plan</span><strong id="graphState">none</strong>
        <span>Params</span><strong id="paramState">waiting</strong>
        <span>Script</span><strong id="scriptState">waiting</strong>
        <span>Run Directory</span><strong id="bundleState">none</strong>
      </div>
      <section class="conversation-manager" aria-label="Conversations">
        <div class="conversation-head">
          <strong>Conversations</strong>
          <button id="newConversationBtn" type="button">New</button>
          <button id="refreshConversationsBtn" type="button" title="Refresh conversations">Refresh</button>
        </div>
        <div class="conversation-filters">
          <input id="conversationSearch" type="search" placeholder="Search" aria-label="Search conversations">
          <select id="conversationStatus" aria-label="Conversation status">
            <option value="active">Active</option>
            <option value="archived">Archived</option>
            <option value="all">All</option>
          </select>
        </div>
        <div id="conversationList" class="conversation-list"></div>
        <div class="conversation-actions">
          <span id="activeConversationLabel">No active conversation</span>
          <button id="renameConversationBtn" type="button" disabled>Rename</button>
          <button id="forkConversationBtn" type="button" disabled>Fork</button>
          <button id="archiveConversationBtn" type="button" disabled>Archive</button>
        </div>
      </section>
    </aside>

    <main>
      <section id="pane-chat" class="pane active">
        <div class="panel" data-expand-id="chat" data-expand-title="Discuss With Agent">
          <div class="panel-head">Discuss With Agent</div>
          <div class="panel-body">
            <div id="messages" class="message-log"></div>
            <div style="margin-top:10px">
              <label for="goal">Request</label>
              <textarea id="goal" placeholder="Describe the analysis you want to plan, review, and run on the Workbench server."></textarea>
              <div class="actions">
                <button id="sendBtn" class="primary">Send</button>
                <button id="explainBtn">Explain Plan</button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="pane-plan" class="pane">
        <div class="panel" data-expand-id="plan" data-expand-title="Review Plan">
          <div class="panel-head">Review Plan</div>
          <div class="panel-body">
            <div id="planEmpty" class="empty">No workflow plan has been drafted.</div>
            <div id="planContent" class="hidden">
              <div class="summary-grid">
                <div class="summary-card">
                  <h3>Workflow</h3>
                  <p id="planTitle">none</p>
                </div>
                <div class="summary-card">
                  <h3>Confidence</h3>
                  <p id="planConfidence">unverified</p>
                </div>
                <div class="summary-card">
                  <h3>Status</h3>
                  <p id="planMaterialization">waiting</p>
                </div>
                <div class="summary-card">
                  <h3>Validation</h3>
                  <p id="planValidation">none</p>
                </div>
              </div>
              <div class="panel" style="margin-bottom:12px">
                <div class="panel-head">Modules</div>
                <div class="panel-body"><div id="planModules" class="module-list"></div></div>
              </div>
              <div class="summary-grid">
                <div class="summary-card">
                  <h3>Inputs Needed</h3>
                  <p id="planInputs">none</p>
                </div>
                <div class="summary-card">
                  <h3>Expected Outputs</h3>
                  <p id="planOutputs">none</p>
                </div>
              </div>
              <div id="planBlockers" class="empty hidden"></div>
              <div class="actions">
                <button id="toParamsBtn" class="primary">Open Parameter Form</button>
                <button id="explainPlanFromPlanBtn">Ask Agent To Explain</button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="pane-params" class="pane">
        <div class="panel" data-expand-id="params" data-expand-title="Parameter Form">
          <div class="panel-head">
            <span>Parameter Form</span>
          </div>
          <div class="panel-body">
            <div id="paramForm"></div>
            <div class="actions">
              <button id="validateBtn">Validate</button>
              <button id="approveBtn" class="primary">Approve</button>
              <button id="draftRecipeBtn">Draft Recipe</button>
            </div>
          </div>
        </div>
      </section>

      <section id="pane-script" class="pane">
        <div class="panel" data-expand-id="script" data-expand-title="Review Script">
          <div class="panel-head">Review Script</div>
          <div class="panel-body">
            <div class="field">
              <span class="field-label">Execution Locale For Generated Run Directory</span>
              <div class="actions" role="group" aria-label="Execution locale for generated run directory">
                <button id="scriptExecutionLocationServerBtn" type="button" class="primary" data-execution-location="server">Workbench server</button>
                <button id="scriptExecutionLocationLocalBtn" type="button" data-execution-location="local">My local shell</button>
                <button id="scriptExecutionLocationRemoteSshBtn" type="button" data-execution-location="remote_ssh">Remote SSH</button>
                <button id="scriptExecutionLocationSchedulerBtn" type="button" data-execution-location="scheduler_temporal">Local scheduler</button>
                <button id="scriptExecutionLocationSchedulerRemoteSshBtn" type="button" data-execution-location="scheduler_remote_ssh">SSH via scheduler</button>
              </div>
              <div id="scriptExecutionLocationHint" class="field-hint">Generate Run Directory will create server-visible path bindings.</div>
            </div>
            <textarea id="scriptEditor" spellcheck="false" style="min-height:340px"></textarea>
            <div class="actions">
              <button id="generateBtn" class="primary">Generate Run Directory</button>
              <button id="reviewScriptBtn">Mark Reviewed</button>
              <button id="copyScriptBtn">Copy</button>
            </div>
          </div>
        </div>
      </section>

      <section id="pane-run" class="pane">
        <div class="panel" data-expand-id="run" data-expand-title="Run">
          <div class="panel-head">Run</div>
          <div class="panel-body">
            <div class="field">
              <span class="field-label">Execution Locale</span>
              <div class="actions" role="group" aria-label="Execution locale">
                <button id="executionLocationServerBtn" type="button" class="primary" data-execution-location="server">Workbench server</button>
                <button id="executionLocationLocalBtn" type="button" data-execution-location="local">My local shell</button>
                <button id="executionLocationRemoteSshBtn" type="button" data-execution-location="remote_ssh">Remote SSH</button>
                <button id="executionLocationSchedulerBtn" type="button" data-execution-location="scheduler_temporal">Local scheduler</button>
                <button id="executionLocationSchedulerRemoteSshBtn" type="button" data-execution-location="scheduler_remote_ssh">SSH via scheduler</button>
              </div>
              <div id="executionLocationHint" class="field-hint">Workbench server can preflight and run server-visible paths.</div>
            </div>
            <pre id="runText"></pre>
            <div class="gate-hint">Production execution runs on the selected API-managed location. My local shell is caller-managed and cannot be launched by the browser.</div>
            <div class="actions">
              <button id="preflightBtn" class="primary" aria-describedby="runGateHint">Run Preflight</button>
              <button id="executionDiagnosticBtn" aria-describedby="runGateHint">Diagnose Location</button>
              <button id="downloadBundleBtn" aria-describedby="runGateHint">Download Run Directory</button>
              <button id="localRunBtn" aria-describedby="runGateHint">Run Locally</button>
              <button id="runProductionBtn" class="hidden" aria-describedby="runGateHint">Run on Workbench Server</button>
              <div id="runGateHint" class="gate-hint"></div>
            </div>
            <div class="run-section">
              <div class="section-label">Execution Log</div>
              <pre id="executionLog" class="log-panel"></pre>
            </div>
            <div class="run-section">
              <div class="section-label">Output Manifest</div>
              <div id="artifactManifest" class="artifact-list empty">No run outputs yet.</div>
            </div>
          </div>
        </div>
      </section>
    </main>

    <div class="right">
      <div class="panel walkthrough-panel">
        <div class="panel-head">Walkthroughs</div>
        <div class="panel-body">
          <div class="walkthrough-picker">
            <label class="sr-only" for="walkthroughSelect">Workbench walkthrough</label>
            <select id="walkthroughSelect" aria-label="Workbench walkthrough">
              <optgroup label="Start Here: quick run + orientation">
                <option value="01_trimodal_quick_demo">01 Load Quick Demo: Trimodal MuData QC</option>
                <option value="00_assay_catalog">00 Assay catalog sanity check</option>
                <option value="11_visualization_catalog">11 Visualization catalog</option>
              </optgroup>
              <optgroup label="Bulk RNA-seq: simple to extended">
                <option value="02_bulk_pe_deseq2">02 Bulk paired-end RNA-seq with DESeq2</option>
                <option value="03_bulk_plots">03 Bulk RNA-seq with volcano and heatmap plots</option>
                <option value="04_slam_seq">04 SLAM-seq conversation</option>
              </optgroup>
              <optgroup label="Single-cell and perturbation">
                <option value="05_post_mex">05 STARsolo / post-MEX downstream modules</option>
                <option value="06_example_perturb_visualization">06 Example perturbation perturb-seq visualization suite</option>
              </optgroup>
              <optgroup label="Chromap chromatin workflows">
                <option value="07_chromap_atac">07 Chromap ATAC / scATAC</option>
                <option value="12_chromap_evidence_compose">12 Chromap ATAC evidence composition</option>
                <option value="08_chromap_chip">08 Chromap ChIP-seq / TagAlign</option>
                <option value="09_chromap_hic">09 Chromap Hi-C pairs</option>
                <option value="13_chromap_hic_pairs_compose">13 Chromap Hi-C suite recipe</option>
              </optgroup>
              <optgroup label="Multiomics suite surfaces">
                <option value="10_multiomics">10 Multiomics discovery</option>
                <option value="14_multiomics_mudata_builder_compose">14 Multiomics MuData builder suite recipe</option>
                <option value="15_multiomics_trimodal_report_compose">15 Multiomics trimodal report suite recipe</option>
              </optgroup>
              <optgroup label="nf-core workflow wrappers">
                <option value="16_nfcore_da_bulk_counts">16 nf-core differential abundance from bulk counts</option>
                <option value="17_nfcore_da_chromap_peak_counts">17 nf-core differential abundance from Chromap peaks</option>
                <option value="18_nfcore_atacseq_chromap_handoff">18 nf-core ATAC-seq Chromap handoff</option>
              </optgroup>
            </select>
            <label class="sr-only" for="walkthroughActionMode">Walkthrough action</label>
            <select id="walkthroughActionMode" aria-label="Walkthrough action">
              <option value="start">Start / load walkthrough</option>
              <option value="starting_prompt">Starting prompt only</option>
              <option value="prompt_guidance">Prompt guidance only</option>
            </select>
            <label class="walkthrough-mode" title="Force Start to use the configured model path, even when a deterministic local load is available.">
              <input id="walkthroughRequireLlm" type="checkbox">
              <span>Require LLM input</span>
            </label>
            <button id="quickDemoBtn">Start</button>
            <div id="walkthroughModeStatus" class="field-hint">Start/load mode is selected.</div>
            <div id="modelWalkthroughStatus" class="field-hint">Checking model availability for conversation walkthroughs.</div>
          </div>
        </div>
      </div>
      <div class="panel" data-expand-id="details" data-expand-title="Details">
        <div class="panel-head">
          <span>Details</span>
        </div>
        <div class="panel-body"><div id="detailView" class="detail-view"></div></div>
      </div>
      <div class="panel" data-expand-id="advanced" data-expand-title="Advanced">
        <div class="panel-head">Advanced</div>
        <div class="panel-body">
          <details id="advancedDetails" class="advanced">
            <summary>Raw data and helper sources</summary>
            <div class="advanced-body">
              <div>
                <label for="graphView">Workflow Graph JSON</label>
                <pre id="graphView"></pre>
              </div>
              <div>
                <label for="paramJson">Parameter JSON</label>
                <textarea id="paramJson" spellcheck="false" readonly></textarea>
              </div>
              <div>
                <div class="panel-head" style="padding:0 0 8px;height:auto;border:0">
                  <span>Helper Sources</span>
                  <button id="loadHelpersBtn">Load</button>
                </div>
                <div id="helperList" class="helper-list"></div>
                <textarea id="helperEditor" spellcheck="false" style="min-height:180px"></textarea>
                <div class="actions">
                  <button id="downloadHelpersBtn">Download Helper Sources</button>
                </div>
              </div>
              <div>
                <div class="panel-head" style="padding:0 0 8px;height:auto;border:0">
                  <span>Conversation Log</span>
                  <button id="loadThreadLogBtn">Load</button>
                </div>
                <pre id="threadLogView"></pre>
              </div>
              <div>
                <label for="rawView">Raw API Response</label>
                <pre id="rawView"></pre>
              </div>
            </div>
          </details>
        </div>
      </div>
    </div>
  </div>

  <div id="panelWorkspace" class="panel-workspace hidden" aria-label="Expanded panels">
    <div class="workspace-head">
      <span class="workspace-title">Expanded Panels</span>
      <div id="expandedTabs" class="tabs"></div>
      <div class="workspace-actions">
        <button id="expandedWindowBtn">Open Window</button>
        <button id="expandedCloseTabBtn">Close Tab</button>
        <button id="expandedCloseBtn">Close</button>
      </div>
    </div>
    <div id="expandedMount" class="expanded-mount"></div>
  </div>

  <div id="fileBrowserModal" class="modal hidden" role="dialog" aria-modal="true" aria-labelledby="fileBrowserTitle">
    <div class="modal-card">
      <div class="modal-head">
        <span id="fileBrowserTitle">Server File Browser</span>
        <button id="fileBrowserCloseBtn" type="button">Close</button>
      </div>
      <div class="file-browser-body">
        <div id="fileBrowserPath" class="file-browser-path">Choose a root.</div>
        <div id="fileBrowserRoots" class="file-browser-roots"></div>
        <div class="actions" style="margin-top:0">
          <button id="fileBrowserUpBtn" type="button">Up</button>
          <button id="fileBrowserRefreshBtn" type="button">Refresh</button>
        </div>
        <div id="fileBrowserEntries" class="file-browser-entries"></div>
        <div id="fileBrowserHint" class="field-hint">
          Server paths must be readable from the Workbench server. Browser-local files must be uploaded or mounted before the run can use them.
        </div>
        <div class="actions">
          <button id="fileBrowserUseBtn" class="primary" type="button" disabled>Use Selected Path</button>
          <button id="fileBrowserCancelBtn" type="button">Cancel</button>
        </div>
      </div>
    </div>
  </div>

  <div id="diagnosticModal" class="modal hidden" role="dialog" aria-modal="true" aria-labelledby="diagnosticTitle">
    <div class="modal-card">
      <div class="modal-head">
        <span id="diagnosticTitle">Execution Location Diagnostic</span>
        <button id="diagnosticCloseBtn" type="button">Close</button>
      </div>
      <div class="diagnostic-body">
        <pre id="diagnosticText">No diagnostic has been run.</pre>
        <div class="actions">
          <button id="diagnosticRawBtn" type="button">Show Raw</button>
          <button id="diagnosticDismissBtn" class="primary" type="button">Done</button>
        </div>
      </div>
    </div>
  </div>

  <div id="executionReviewModal" class="modal hidden" role="dialog" aria-modal="true" aria-labelledby="executionReviewTitle">
    <div class="modal-card">
      <div class="modal-head">
        <span id="executionReviewTitle">Execution Review</span>
        <button id="executionReviewCloseBtn" type="button">Close</button>
      </div>
      <div class="diagnostic-body">
        <pre id="executionReviewText">No review request has been prepared.</pre>
        <div class="review-form">
          <label for="executionReviewLocation">
            Execution Locale
            <select id="executionReviewLocation">
              <option value="server">Workbench server</option>
              <option value="local">My local shell</option>
              <option value="remote_ssh">Remote SSH</option>
              <option value="scheduler_temporal">Local Temporal scheduler</option>
              <option value="scheduler_remote_ssh">Remote SSH via Temporal scheduler</option>
            </select>
          </label>
          <label for="executionReviewRemoteHost">
            SSH Host
            <input id="executionReviewRemoteHost" type="text" placeholder="128.208.252.232">
          </label>
          <label for="executionReviewRemoteUser">
            SSH User
            <input id="executionReviewRemoteUser" type="text" placeholder="optional">
          </label>
          <label for="executionReviewRemoteWorkdir">
            Remote Bundle Path
            <input id="executionReviewRemoteWorkdir" type="text" placeholder="/tmp/morphic-bundles/trimodal_qc_report_v0">
          </label>
          <label for="executionReviewRemoteRuntime">
            Remote Runtime
            <select id="executionReviewRemoteRuntime">
              <option value="docker">Docker</option>
              <option value="podman">Podman</option>
              <option value="apptainer">Apptainer</option>
              <option value="shell">Shell</option>
            </select>
          </label>
          <label for="executionReviewRemotePathOverrides">
            Remote Path Overrides JSON
            <textarea id="executionReviewRemotePathOverrides" rows="5" spellcheck="false" placeholder='{"mudata": "/remote/data/demo_trimodal_small.h5mu"}'></textarea>
          </label>
          <label for="executionReviewNotes">
            Notes
            <textarea id="executionReviewNotes" rows="4" placeholder="Optional notes or path corrections"></textarea>
          </label>
        </div>
        <div class="actions">
          <button id="executionReviewCancelBtn" type="button">Cancel</button>
          <button id="executionReviewApproveBtn" class="primary" type="button">Approve</button>
        </div>
      </div>
    </div>
  </div>

  <div id="localRunModal" class="modal hidden" role="dialog" aria-modal="true" aria-labelledby="localRunTitle">
    <div class="modal-card">
      <div class="modal-head">
        <span id="localRunTitle">Run Locally</span>
        <button id="localRunCloseBtn" type="button">Close</button>
      </div>
      <div class="diagnostic-body">
        <pre id="localRunText">Generate a run directory first.</pre>
        <div class="actions">
          <button id="localRunDownloadBtn" type="button">Download Bundle</button>
          <button id="localRunCopyDockerBtn" type="button">Copy Docker Command</button>
          <button id="localRunCopyApptainerBtn" type="button">Copy Apptainer Command</button>
          <button id="localRunDoneBtn" class="primary" type="button">Done</button>
        </div>
      </div>
    </div>
  </div>

  <div id="serverRunModal" class="modal hidden" role="dialog" aria-modal="true" aria-labelledby="serverRunTitle">
    <div class="modal-card">
      <div class="modal-head">
        <span id="serverRunTitle">Preflight Passed</span>
        <button id="serverRunCloseBtn" type="button">Close</button>
      </div>
      <div class="diagnostic-body">
        <pre id="serverRunText">Run is available.</pre>
        <div class="actions">
          <button id="serverRunLaterBtn" type="button">Not Now</button>
          <button id="serverRunNowBtn" class="primary" type="button">Run Now</button>
        </div>
      </div>
    </div>
  </div>

  <script>
    const CLIENT_SESSION_KEY = "morphicWorkbenchSessionId";
    const ACTIVE_CONVERSATION_KEY = "morphicWorkbenchConversationId";

    function loadClientSessionId() {
      try {
        let value = window.localStorage.getItem(CLIENT_SESSION_KEY);
        if (!value) {
          const randomId = window.crypto && window.crypto.randomUUID
            ? window.crypto.randomUUID()
            : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
          value = `browser-${randomId}`;
          window.localStorage.setItem(CLIENT_SESSION_KEY, value);
        }
        return value;
      } catch (error) {
        return `browser-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
      }
    }

    const state = {
      graph: null,
      graphId: "",
      runId: "",
      params: {},
      approved: false,
      script: "",
      scriptFresh: false,
      reviewed: false,
      bundlePath: "",
      helperScripts: [],
      helperIndex: -1,
      lastResponse: null,
      lastPreflight: null,
      lastExecution: null,
      lastDiagnostic: null,
      lastExecutionReview: null,
      pendingExecutionReview: null,
      recipeDraft: null,
      executionLocation: "server",
      bundleExecutionLocation: "",
      remoteSsh: {
        remote_host: "",
        remote_user: "",
        remote_workdir: "",
        remote_port: "",
        remote_container_runtime: "docker",
        remote_path_overrides: {},
        remote_check: true
      },
      clientSessionId: loadClientSessionId(),
      threadId: "",
      activeConversation: null,
      conversations: [],
      conversationSearchTimer: null,
      walkthroughRequestEdited: false,
      activeWalkthroughDemoMode: false,
      activeWalkthroughId: "",
      modelStatus: {available: false, checking: true, error: "Model probe has not completed."},
      fileBrowser: {
        target: null,
        mode: "replace",
        currentPath: "",
        parentPath: "",
        selectedPath: "",
        roots: []
      }
    };
    const $ = (id) => document.getElementById(id);

    function detectAppBasePath() {
      const pathname = window.location.pathname || "/";
      for (const base of ["/workbench-dev", "/workbench-test", "/workbench", "/tutorials-dev", "/tutorials-test", "/tutorials"]) {
        if (pathname === base || pathname.startsWith(`${base}/`)) return base;
      }
      return "";
    }

    const appBasePath = detectAppBasePath();

    function appPath(path) {
      if (!path || /^https?:\/\//.test(path)) return path;
      if (!appBasePath || !path.startsWith("/")) return path;
      return `${appBasePath}${path}`;
    }

    function decodeBase64UrlJson(encoded) {
      const normalized = String(encoded || "").replace(/-/g, "+").replace(/_/g, "/");
      const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
      return JSON.parse(decodeURIComponent(Array.from(atob(padded), (char) => {
        return `%${char.charCodeAt(0).toString(16).padStart(2, "0")}`;
      }).join("")));
    }

    function workbenchHandoffFromLocation() {
      const searchParams = new URLSearchParams(window.location.search || "");
      let encoded = searchParams.get("workbench");
      if (!encoded) {
        const hash = window.location.hash || "";
        if (!hash.startsWith("#")) return null;
        const hashParams = new URLSearchParams(hash.slice(1));
        encoded = hashParams.get("workbench");
      }
      if (!encoded) return null;
      const payload = decodeBase64UrlJson(encoded);
      return payload && payload.schema === "morphic.workbench_handoff/v0" ? payload : null;
    }

    function clearWorkbenchHandoffFromLocation() {
      const searchParams = new URLSearchParams(window.location.search || "");
      const hadQueryHandoff = searchParams.has("workbench");
      if (hadQueryHandoff) searchParams.delete("workbench");
      const nextSearch = searchParams.toString();
      const nextPath = `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}`;
      if (hadQueryHandoff || window.location.hash.includes("workbench=")) {
        window.history.replaceState(null, "", nextPath);
      }
    }

    function workbenchLandingPath() {
      return appBasePath ? `${appBasePath}/` : "/";
    }

    function endSession() {
      try {
        window.localStorage.removeItem(CLIENT_SESSION_KEY);
        window.localStorage.removeItem(ACTIVE_CONVERSATION_KEY);
      } catch (error) {
        // localStorage can be unavailable in hardened browser contexts.
      }
      document.cookie = "morphic_session=; Max-Age=0; Path=/; SameSite=Lax";
      if (appBasePath) document.cookie = `morphic_session=; Max-Age=0; Path=${appBasePath}; SameSite=Lax`;
      document.cookie = "morphic_session=; Max-Age=0; Path=/workbench; SameSite=Lax";
      window.location.assign(workbenchLandingPath());
    }

    function setStatus(text, tone = "") {
      $("status").textContent = text;
      $("status").className = `pill ${tone}`.trim();
    }

    function renderSessionInfo(payload) {
      const context = (payload && payload.request_context) || {};
      const user = context.email || context.user || "anonymous";
      const provider = context.auth_provider || "local";
      const label = user === "anonymous" ? "anonymous session" : user;
      $("sessionUser").textContent = label;
      $("sessionUser").title = `${label} via ${provider}`;
    }

    function loadSessionInfo() {
      return fetch(appPath("/api/session"), {
        headers: {"X-Morphic-Session": state.clientSessionId}
      }).then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
        }
        renderSessionInfo(payload);
        return payload;
      });
    }

    function storedConversationId() {
      try {
        return window.localStorage.getItem(ACTIVE_CONVERSATION_KEY) || "";
      } catch (error) {
        return "";
      }
    }

    function persistConversationId(conversationId) {
      try {
        if (conversationId) window.localStorage.setItem(ACTIVE_CONVERSATION_KEY, conversationId);
        else window.localStorage.removeItem(ACTIVE_CONVERSATION_KEY);
      } catch (error) {
        // Conversation resume remains available for the current page when storage is unavailable.
      }
    }

    function setActiveConversation(conversation) {
      state.activeConversation = conversation || null;
      state.threadId = conversation?.thread_id || conversation?.conversation_id || "";
      persistConversationId(conversation?.conversation_id || "");
      const active = Boolean(conversation);
      $("activeConversationLabel").textContent = active ? conversation.title : "No active conversation";
      $("activeConversationLabel").title = active ? conversation.conversation_id : "";
      $("renameConversationBtn").disabled = !active;
      $("forkConversationBtn").disabled = !active;
      $("archiveConversationBtn").disabled = !active;
      $("archiveConversationBtn").textContent = conversation?.status === "archived" ? "Restore" : "Archive";
      renderConversationList();
    }

    function conversationTime(value) {
      const date = new Date(value || "");
      return Number.isNaN(date.getTime()) ? "" : date.toLocaleString([], {dateStyle: "short", timeStyle: "short"});
    }

    function renderConversationList() {
      const list = $("conversationList");
      list.innerHTML = "";
      if (!state.conversations.length) {
        const empty = document.createElement("div");
        empty.className = "conversation-empty";
        empty.textContent = "No matching conversations.";
        list.appendChild(empty);
        return;
      }
      for (const conversation of state.conversations) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `conversation-item${conversation.conversation_id === state.activeConversation?.conversation_id ? " active" : ""}`;
        const title = document.createElement("span");
        title.className = "conversation-title";
        title.textContent = conversation.title;
        const meta = document.createElement("span");
        meta.className = "conversation-meta";
        meta.textContent = `${conversation.turn_count} turns / ${conversation.run_count} runs${conversationTime(conversation.updated_at) ? ` / ${conversationTime(conversation.updated_at)}` : ""}`;
        button.append(title, meta);
        button.addEventListener("click", () => openConversation(conversation.conversation_id).catch(showConversationError));
        list.appendChild(button);
      }
    }

    function showConversationError(error) {
      showRaw(error.payload || {error: String(error)});
      setStatus("conversation error", "bad-text");
    }

    async function refreshConversations(options = {}) {
      const params = new URLSearchParams({
        status: $("conversationStatus").value || "active",
        query: $("conversationSearch").value.trim(),
        limit: "100"
      });
      const payload = await requestJson(`/api/conversations?${params.toString()}`);
      state.conversations = payload.conversations || [];
      renderConversationList();
      if (options.resume) {
        const requested = storedConversationId();
        if (requested && state.conversations.some((item) => item.conversation_id === requested)) {
          await openConversation(requested);
        }
      }
      return payload;
    }

    function restoreConversationCanvas(payload) {
      const conversation = payload.conversation;
      clearWorkbenchCanvas();
      setActiveConversation(conversation);
      const turns = payload.turns || [];
      const graphTurn = [...turns].reverse().find((turn) => turn.payload?.workflow_graph);
      if (graphTurn?.payload?.workflow_graph) {
        loadGraph(graphTurn.payload.workflow_graph, graphTurn.payload.params_json?.params || null);
      }
      $("messages").innerHTML = "";
      for (const turn of turns) {
        const turnPayload = turn.payload || {};
        const text = turn.role === "user"
          ? turn.goal
          : (turnPayload.assistant_message || turnPayload.summary || turnPayload.run_blocker || "Recorded response");
        if (text) addMessage(turn.role === "user" ? "user" : "agent", text);
      }
      if (!turns.length) addMessage("system", "New conversation.");
      const latestRun = (payload.runs || [])[0];
      if (latestRun) {
        state.runId = latestRun.run_id || "";
        const bundle = latestRun.bundle || {};
        state.bundlePath = bundle.bundle_path || latestRun.bundle_path || "";
        state.bundleExecutionLocation = latestRun.execution_location?.location_id || latestRun.execution_location?.kind || "";
        if (state.bundlePath) {
          $("bundleState").textContent = state.bundlePath;
          markStep("run", "ready");
        }
      }
      renderThreadLog({turns});
      updateRunControls();
      switchPane("chat");
    }

    async function openConversation(conversationId) {
      setStatus("loading conversation");
      const payload = await requestJson(`/api/conversations/${encodeURIComponent(conversationId)}?turn_limit=200&run_limit=25`);
      restoreConversationCanvas(payload);
      setStatus("ready", "good-text");
      return payload;
    }

    async function createConversation() {
      setStatus("creating conversation");
      const payload = await requestJson("/api/conversations", {title: "New conversation"});
      await refreshConversations();
      await openConversation(payload.conversation.conversation_id);
    }

    async function renameConversation() {
      const conversation = state.activeConversation;
      if (!conversation) return;
      const title = window.prompt("Conversation title", conversation.title);
      if (title === null || !title.trim()) return;
      const payload = await requestJson(
        `/api/conversations/${encodeURIComponent(conversation.conversation_id)}`,
        {title: title.trim()},
        "PATCH"
      );
      setActiveConversation(payload.conversation);
      await refreshConversations();
    }

    async function archiveOrRestoreConversation() {
      const conversation = state.activeConversation;
      if (!conversation) return;
      const nextStatus = conversation.status === "archived" ? "active" : "archived";
      if (nextStatus === "archived" && !window.confirm(`Archive "${conversation.title}"?`)) return;
      const payload = await requestJson(
        `/api/conversations/${encodeURIComponent(conversation.conversation_id)}`,
        {status: nextStatus},
        "PATCH"
      );
      if (nextStatus === "archived" && $("conversationStatus").value === "active") {
        clearWorkbenchCanvas();
      } else {
        setActiveConversation(payload.conversation);
      }
      await refreshConversations();
    }

    async function forkConversation() {
      const conversation = state.activeConversation;
      if (!conversation) return;
      const payload = await requestJson(
        `/api/conversations/${encodeURIComponent(conversation.conversation_id)}/fork`,
        {include_history: true}
      );
      $("conversationStatus").value = "active";
      await refreshConversations();
      await openConversation(payload.conversation.conversation_id);
    }

    function adoptConversation(payload) {
      const conversation = payload?.conversation;
      if (!conversation) return;
      setActiveConversation(conversation);
      refreshConversations().catch(showConversationError);
    }

    function normalizeMessage(text) {
      return String(text || "").replace(/\s+/g, " ").trim().toLowerCase();
    }

    function escapeHtml(text) {
      return String(text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function renderInlineMarkdown(text) {
      return escapeHtml(text)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
    }

    function renderMarkdown(text) {
      const lines = String(text || "").trim().split("\n");
      let html = "";
      let paragraph = [];
      let list = [];
      const flushParagraph = () => {
        if (!paragraph.length) return;
        html += `<p>${paragraph.map((line) => renderInlineMarkdown(line)).join("<br>")}</p>`;
        paragraph = [];
      };
      const flushList = () => {
        if (!list.length) return;
        html += `<ul>${list.map((line) => `<li>${renderInlineMarkdown(line)}</li>`).join("")}</ul>`;
        list = [];
      };
      for (const rawLine of lines) {
        const line = rawLine.trimEnd();
        if (!line.trim()) {
          flushParagraph();
          flushList();
          continue;
        }
        const bullet = line.match(/^\s*[-*]\s+(.+)$/);
        if (bullet) {
          flushParagraph();
          list.push(bullet[1]);
        } else {
          flushList();
          paragraph.push(line);
        }
      }
      flushParagraph();
      flushList();
      return html;
    }

    function addMessage(role, text) {
      const messageText = text || "";
      if (role === "agent") {
        const normalized = normalizeMessage(messageText);
        const prior = Array.from($("messages").querySelectorAll(".msg.agent"));
        if (prior.some((node) => normalizeMessage(node.textContent) === normalized)) return;
      }
      const node = document.createElement("div");
      node.className = `msg ${role}`;
      if (role === "agent") node.innerHTML = renderMarkdown(messageText);
      else node.textContent = messageText;
      $("messages").appendChild(node);
      $("messages").scrollTop = $("messages").scrollHeight;
      return node;
    }

    const THINKING_PHRASES = [
      ["Reticulating", "the local context"],
      ["Munging", "recipe hints"],
      ["Crosswalking", "modules"],
      ["Unsnarling", "constraints"],
      ["Triangling", "the request"],
      ["Composing", "a response"],
      ["Checking", "tool coverage"],
      ["Threading", "the plan"]
    ];

    function addThinkingMessage() {
      const node = document.createElement("div");
      node.className = "msg agent thinking";
      node.setAttribute("role", "status");
      node.setAttribute("aria-live", "polite");
      const dots = document.createElement("span");
      dots.className = "thinking-dots";
      dots.innerHTML = '<span class="thinking-dot"></span><span class="thinking-dot"></span><span class="thinking-dot"></span>';
      const label = document.createElement("span");
      label.className = "thinking-copy";
      const render = (index) => {
        const [verb, detail] = THINKING_PHRASES[index % THINKING_PHRASES.length];
        label.innerHTML = `<span class="thinking-verb">${escapeHtml(verb)}</span> ${escapeHtml(detail)}...`;
      };
      render(0);
      let index = 1;
      node._thinkingTimer = window.setInterval(() => {
        render(index);
        index += 1;
      }, 850);
      node.append(dots, label);
      $("messages").appendChild(node);
      $("messages").scrollTop = $("messages").scrollHeight;
      return node;
    }

    function removeThinkingMessage(node) {
      if (node && node._thinkingTimer) window.clearInterval(node._thinkingTimer);
      if (node && node.parentNode) node.parentNode.removeChild(node);
    }

    function showRaw(payload) {
      state.lastResponse = payload;
      $("rawView").textContent = JSON.stringify(payload, null, 2);
      renderDetails(payload);
    }

    function switchPane(name) {
      document.querySelectorAll(".pane").forEach((pane) => pane.classList.toggle("active", pane.id === `pane-${name}`));
      document.querySelectorAll(".step").forEach((step) => step.classList.toggle("active", step.dataset.pane === name));
    }

    const expandedPanelState = {
      tabs: [],
      activeId: "",
      placeholder: null,
    };

    function expandablePanel(id) {
      return Array.from(document.querySelectorAll("[data-expand-id]")).find((panel) => panel.dataset.expandId === id) || null;
    }

    function panelTitle(panelOrId) {
      const panel = typeof panelOrId === "string" ? expandablePanel(panelOrId) : panelOrId;
      return panel?.dataset.expandTitle || "Panel";
    }

    function restoreExpandedPanel() {
      if (!expandedPanelState.activeId || !expandedPanelState.placeholder) return;
      const panel = expandablePanel(expandedPanelState.activeId);
      if (panel && expandedPanelState.placeholder.parentNode) {
        expandedPanelState.placeholder.parentNode.insertBefore(panel, expandedPanelState.placeholder);
        expandedPanelState.placeholder.remove();
      }
      expandedPanelState.activeId = "";
      expandedPanelState.placeholder = null;
      $("expandedMount").innerHTML = "";
    }

    function renderExpandedTabs() {
      const tabs = $("expandedTabs");
      tabs.innerHTML = "";
      for (const id of expandedPanelState.tabs) {
        const button = document.createElement("button");
        button.textContent = panelTitle(id);
        button.className = id === expandedPanelState.activeId ? "active" : "";
        button.addEventListener("click", () => activateExpandedPanel(id));
        tabs.appendChild(button);
      }
    }

    function activateExpandedPanel(id) {
      if (expandedPanelState.activeId === id) {
        $("panelWorkspace").classList.remove("hidden");
        renderExpandedTabs();
        return;
      }
      restoreExpandedPanel();
      const panel = expandablePanel(id);
      if (!panel) return;
      const placeholder = document.createComment(`expanded-panel:${id}`);
      panel.parentNode.insertBefore(placeholder, panel);
      $("expandedMount").appendChild(panel);
      expandedPanelState.activeId = id;
      expandedPanelState.placeholder = placeholder;
      $("panelWorkspace").classList.remove("hidden");
      renderExpandedTabs();
    }

    function openPanelTab(id) {
      if (!expandedPanelState.tabs.includes(id)) expandedPanelState.tabs.push(id);
      activateExpandedPanel(id);
    }

    function closeExpandedTab(id = expandedPanelState.activeId) {
      if (!id) return;
      const index = expandedPanelState.tabs.indexOf(id);
      if (id === expandedPanelState.activeId) restoreExpandedPanel();
      if (index >= 0) expandedPanelState.tabs.splice(index, 1);
      if (expandedPanelState.tabs.length) activateExpandedPanel(expandedPanelState.tabs[Math.max(0, index - 1)]);
      else $("panelWorkspace").classList.add("hidden");
      renderExpandedTabs();
    }

    function closeExpandedWorkspace() {
      restoreExpandedPanel();
      expandedPanelState.tabs = [];
      $("panelWorkspace").classList.add("hidden");
      renderExpandedTabs();
    }

    function syncSnapshotControls(source, clone) {
      const sourceControls = source.querySelectorAll("textarea, input, select");
      const cloneControls = clone.querySelectorAll("textarea, input, select");
      sourceControls.forEach((control, index) => {
        const cloneControl = cloneControls[index];
        if (!cloneControl) return;
        if (control.tagName === "TEXTAREA") {
          cloneControl.textContent = control.value;
          cloneControl.value = control.value;
        } else if (control.tagName === "SELECT") {
          Array.from(cloneControl.options).forEach((option) => {
            option.selected = option.value === control.value;
          });
        } else if (control.type === "checkbox" || control.type === "radio") {
          if (control.checked) cloneControl.setAttribute("checked", "checked");
          else cloneControl.removeAttribute("checked");
        } else {
          cloneControl.setAttribute("value", control.value);
        }
      });
      const sourceDetails = source.querySelectorAll("details");
      const cloneDetails = clone.querySelectorAll("details");
      sourceDetails.forEach((details, index) => {
        const cloneDetailsNode = cloneDetails[index];
        if (!cloneDetailsNode) return;
        if (details.open) cloneDetailsNode.setAttribute("open", "open");
        else cloneDetailsNode.removeAttribute("open");
      });
    }

    function openPanelWindow(id = expandedPanelState.activeId) {
      const panel = expandablePanel(id);
      if (!panel) return;
      const clone = panel.cloneNode(true);
      syncSnapshotControls(panel, clone);
      clone.querySelectorAll(".panel-tools").forEach((node) => node.remove());
      const opened = window.open("", "_blank", "width=1220,height=900");
      if (!opened) {
        setStatus("window blocked", "bad-text");
        return;
      }
      const styleText = document.querySelector("style")?.textContent || "";
      opened.document.write(`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${escapeHtml(panelTitle(panel))}</title><style>${styleText} body{padding:14px}.panel{margin:0}.panel-body{max-height:none}.right .panel{border:1px solid var(--line);border-radius:6px}</style></head><body><div class="msg system">Snapshot from BioDepot Workbench. Edits here are not connected to the active session.</div>${clone.outerHTML}</body></html>`);
      opened.document.close();
      opened.opener = null;
    }

    function initPanelExpansion() {
      document.querySelectorAll(".panel[data-expand-id]").forEach((panel) => {
        const head = Array.from(panel.children).find((child) => child.classList?.contains("panel-head"));
        if (!head || head.querySelector(".panel-tools")) return;
        const tools = document.createElement("span");
        tools.className = "panel-tools";
        const tabButton = document.createElement("button");
        tabButton.type = "button";
        tabButton.dataset.panelAction = "tab";
        tabButton.textContent = "Tab";
        tabButton.title = `Expand ${panelTitle(panel)} as an in-page tab.`;
        tabButton.addEventListener("click", (event) => {
          event.stopPropagation();
          openPanelTab(panel.dataset.expandId);
        });
        const windowButton = document.createElement("button");
        windowButton.type = "button";
        windowButton.dataset.panelAction = "window";
        windowButton.textContent = "Window";
        windowButton.title = `Open ${panelTitle(panel)} in a separate browser window snapshot.`;
        windowButton.addEventListener("click", (event) => {
          event.stopPropagation();
          openPanelWindow(panel.dataset.expandId);
        });
        tools.append(tabButton, windowButton);
        head.appendChild(tools);
      });
    }

    function markStep(name, stateName) {
      const step = document.querySelector(`.step[data-pane="${name}"]`);
      if (!step) return;
      step.classList.remove("blocked", "ready", "warn");
      if (stateName) step.classList.add(stateName);
    }

    function updateRunControls() {
      const hasGraph = Boolean(state.graphId);
      const hasBundle = Boolean(state.bundlePath);
      const hasScript = Boolean(state.script || $("scriptEditor").value);
      const bundleLocaleMismatch = Boolean(state.bundleExecutionLocation && state.bundleExecutionLocation !== state.executionLocation);
      const passed = state.lastPreflight && (state.lastPreflight.status === "preflight_passed" || state.lastPreflight.executable_ready === true);
      const localExecution = state.executionLocation === "local";
      const remoteExecution = state.executionLocation === "remote_ssh";
      const schedulerExecution = state.executionLocation === "scheduler_temporal";
      const schedulerRemoteExecution = state.executionLocation === "scheduler_remote_ssh";
      const productionReady = Boolean(!localExecution && passed && hasBundle && state.reviewed);
      const preflightReady = Boolean(hasGraph && hasBundle && hasScript && state.reviewed && !bundleLocaleMismatch);
      const blockers = [];
      if (!hasBundle) blockers.push("Generate a run directory first.");
      if (bundleLocaleMismatch) blockers.push("Regenerate the run directory for the selected execution locale.");
      if (!hasScript) blockers.push("Generate a script first.");
      if (!state.reviewed) blockers.push("Mark the generated script as reviewed.");
      if (!passed) blockers.push("Run preflight after the run directory is ready.");
      if (localExecution) blockers.push("My local shell is caller-managed; the browser cannot start the final script.");
      const preflightBlockers = [];
      if (!hasGraph) preflightBlockers.push("Draft a workflow plan first.");
      if (hasGraph && !hasBundle) preflightBlockers.push("Generate a run directory first.");
      if (hasGraph && hasBundle && bundleLocaleMismatch) preflightBlockers.push("Regenerate the run directory for the selected execution locale.");
      if (hasGraph && !hasScript) preflightBlockers.push("Generate a script first.");
      if (hasGraph && hasBundle && hasScript && !state.reviewed) preflightBlockers.push("Mark the generated script as reviewed before preflight.");
      $("preflightBtn").disabled = !preflightReady;
      $("preflightBtn").title = preflightReady
        ? "Run checks against the reviewed run directory."
        : preflightBlockers.join(" ");
      $("executionDiagnosticBtn").disabled = !hasGraph;
      $("executionDiagnosticBtn").title = hasGraph
        ? "Explain whether the selected execution locale can run this bundle and what is missing."
        : "Draft a workflow plan first.";
      $("downloadBundleBtn").disabled = !hasBundle;
      $("downloadBundleBtn").title = hasBundle ? "Download the full generated run directory as a zip bundle." : "Generate a run directory first.";
      $("localRunBtn").disabled = !hasBundle;
      $("localRunBtn").classList.toggle("primary", localExecution && hasBundle);
      $("localRunBtn").title = hasBundle
        ? "Offer local Docker and Apptainer commands for the downloaded run directory."
        : "Generate a run directory first.";
      $("runProductionBtn").classList.toggle("hidden", !passed || localExecution);
      $("runProductionBtn").textContent = schedulerRemoteExecution ? "Run on SSH Scheduler" : (schedulerExecution ? "Run on Local Scheduler" : (remoteExecution ? "Run on Remote SSH" : "Run on Workbench Server"));
      $("runProductionBtn").disabled = !productionReady;
      $("runProductionBtn").classList.toggle("primary", productionReady);
      $("runProductionBtn").title = productionReady
        ? (schedulerRemoteExecution ? "Stage the generated run directory into scheduler storage and submit it to the Temporal SSH Docker workflow." : (schedulerExecution ? "Stage the generated run directory into scheduler storage and submit it to the local Temporal scheduler." : (remoteExecution ? "Copy the generated run directory to the SSH host and run the selected container launcher." : "Run the generated run directory on the Workbench server after passing preflight.")))
        : blockers.join(" ");
      if (productionReady) {
        $("runGateHint").textContent = schedulerRemoteExecution ? "Scheduler-managed Remote SSH execution is available for the selected destination." : (schedulerExecution ? "Local scheduler execution is available." : (remoteExecution ? "Remote SSH execution is available for the selected destination." : "Run on Workbench Server is available. Workbench server is selected."));
      } else if (localExecution && hasBundle) {
        $("runGateHint").textContent = "My local shell is selected. The browser cannot start run.sh, Docker, or Apptainer; use Run Locally and start the bundle manually.";
      } else if (passed) {
        $("runGateHint").textContent = `${schedulerRemoteExecution ? "Run on SSH Scheduler" : (schedulerExecution ? "Run on Local Scheduler" : (remoteExecution ? "Run on Remote SSH" : "Run on Workbench Server"))} is disabled: ${blockers.join(" ")}`;
      } else if (!preflightReady && preflightBlockers.length) {
        $("runGateHint").textContent = `Run Preflight is disabled: ${preflightBlockers.join(" ")}`;
      } else if (preflightReady) {
        $("runGateHint").textContent = `Run Preflight is ready. ${schedulerRemoteExecution ? "Run on SSH Scheduler" : (schedulerExecution ? "Run on Local Scheduler" : (remoteExecution ? "Run on Remote SSH" : "Run on Workbench Server"))} appears after preflight passes.`;
      } else {
        $("runGateHint").textContent = "";
      }
      $("executionLocationHint").textContent = localExecution
        ? "Warning: My local shell is caller-managed. The browser cannot automatically start the final script; download or copy the bundle and run it manually."
        : remoteExecution
          ? "Remote SSH copies the bundle to the configured destination and runs the selected container launcher there."
          : schedulerExecution
            ? "Local scheduler stages the bundle into Temporal scheduler storage and runs the recipe container through the scheduler worker."
            : schedulerRemoteExecution
              ? "SSH via scheduler stages the bundle into scheduler storage, then runs it on the configured SSH Docker host through Temporal."
            : "Workbench server can preflight and run paths visible to the API service.";
      $("scriptExecutionLocationHint").textContent = localExecution
        ? "Warning: local bundles include run.sh and container launchers, but the browser cannot start them automatically. You must run the final script manually."
        : remoteExecution
          ? "Generate Run Directory will create remote-visible path bindings. Use the review dialog to set SSH destination and path overrides."
          : schedulerExecution
            ? "Generate Run Directory will stage server-readable inputs into the bundle and create scheduler-local path bindings."
            : schedulerRemoteExecution
              ? "Generate Run Directory will stage server-readable inputs into the bundle for scheduler-managed SSH execution."
            : "Generate Run Directory will create server-visible path bindings.";
      document.querySelectorAll("[data-execution-location]").forEach((button) => {
        button.classList.toggle("primary", (button.dataset.executionLocation || "server") === state.executionLocation);
      });
      $("runGateHint").title = $("runGateHint").textContent;
    }

    function normalizeExecutionLocation(locationId) {
      const text = String(locationId || "server").trim();
      return ["server", "local", "remote_ssh", "scheduler_temporal", "scheduler_remote_ssh"].includes(text) ? text : "server";
    }

    function executionLocationRequest() {
      if (state.executionLocation === "scheduler_temporal") return {location_id: "scheduler_temporal"};
      if (state.executionLocation === "scheduler_remote_ssh") {
        return {
          location_id: "scheduler_remote_ssh",
          metadata: {
            remote_host: state.remoteSsh.remote_host || "",
            remote_user: state.remoteSsh.remote_user || "",
            remote_workdir: state.remoteSsh.remote_workdir || "",
            remote_port: state.remoteSsh.remote_port || "",
            remote_container_runtime: state.remoteSsh.remote_container_runtime || "docker",
            remote_path_overrides: state.remoteSsh.remote_path_overrides || {},
            remote_check: state.remoteSsh.remote_check !== false
          }
        };
      }
      if (state.executionLocation !== "remote_ssh") return state.executionLocation;
      return {
        location_id: "remote_ssh",
        metadata: {
          remote_host: state.remoteSsh.remote_host || "",
          remote_user: state.remoteSsh.remote_user || "",
          remote_workdir: state.remoteSsh.remote_workdir || "",
          remote_container_runtime: state.remoteSsh.remote_container_runtime || "docker",
          remote_path_overrides: state.remoteSsh.remote_path_overrides || {},
          remote_check: state.remoteSsh.remote_check !== false
        }
      };
    }

    function parseRemotePathOverrides(text) {
      const value = String(text || "").trim();
      if (!value) return {};
      const parsed = JSON.parse(value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Remote path overrides must be a JSON object keyed by binding id.");
      }
      return parsed;
    }

    function applyRemoteSshMetadata(metadata = {}) {
      if (!metadata || typeof metadata !== "object") return;
      state.remoteSsh.remote_host = String(metadata.remote_host || state.remoteSsh.remote_host || "");
      state.remoteSsh.remote_user = String(metadata.remote_user || state.remoteSsh.remote_user || "");
      state.remoteSsh.remote_workdir = String(metadata.remote_workdir || state.remoteSsh.remote_workdir || "");
      state.remoteSsh.remote_port = String(metadata.remote_port || state.remoteSsh.remote_port || "");
      state.remoteSsh.remote_container_runtime = String(metadata.remote_container_runtime || state.remoteSsh.remote_container_runtime || "docker");
      if (metadata.remote_path_overrides && typeof metadata.remote_path_overrides === "object" && !Array.isArray(metadata.remote_path_overrides)) {
        state.remoteSsh.remote_path_overrides = metadata.remote_path_overrides;
      }
      if (metadata.remote_check !== undefined) state.remoteSsh.remote_check = Boolean(metadata.remote_check);
    }

    function remoteReviewFields() {
      const overrides = parseRemotePathOverrides($("executionReviewRemotePathOverrides").value);
      return {
        remote_host: $("executionReviewRemoteHost").value.trim(),
        remote_user: $("executionReviewRemoteUser").value.trim(),
        remote_workdir: $("executionReviewRemoteWorkdir").value.trim(),
        remote_container_runtime: $("executionReviewRemoteRuntime").value || "docker",
        remote_path_overrides: overrides,
        remote_check: true
      };
    }

    function syncRemoteReviewFieldsFromState() {
      $("executionReviewRemoteHost").value = state.remoteSsh.remote_host || "";
      $("executionReviewRemoteUser").value = state.remoteSsh.remote_user || "";
      $("executionReviewRemoteWorkdir").value = state.remoteSsh.remote_workdir || "";
      $("executionReviewRemoteRuntime").value = state.remoteSsh.remote_container_runtime || "docker";
      $("executionReviewRemotePathOverrides").value = JSON.stringify(state.remoteSsh.remote_path_overrides || {}, null, 2);
    }

    function setRemoteReviewFieldsVisible() {
      const show = ["remote_ssh", "scheduler_remote_ssh"].includes($("executionReviewLocation").value);
      [
        "executionReviewRemoteHost",
        "executionReviewRemoteUser",
        "executionReviewRemoteWorkdir",
        "executionReviewRemoteRuntime",
        "executionReviewRemotePathOverrides"
      ].forEach((id) => {
        const label = $(id).closest("label");
        if (label) label.classList.toggle("hidden", !show);
      });
    }

    function setExecutionLocation(locationId) {
      const next = normalizeExecutionLocation(locationId);
      const previousLocation = state.executionLocation;
      state.executionLocation = next;
      state.lastPreflight = null;
      state.lastExecution = null;
      state.lastDiagnostic = null;
      state.lastExecutionReview = null;
      clearExecutionOutputs();
      if (previousLocation !== state.executionLocation && state.bundlePath && state.bundleExecutionLocation !== state.executionLocation) {
        state.reviewed = false;
        $("scriptState").textContent = "stale";
        $("runText").textContent = "Execution locale changed. Generate the run directory again so manifests/path_bindings.json matches the selected locale.";
        markStep("script", "warn");
        markStep("run", "blocked");
      }
      updateRunControls();
      renderDetails();
    }

    function requestJson(path, body = null, method = "POST") {
      const payload = body && typeof body === "object" && !Array.isArray(body)
        ? {client_session_id: state.clientSessionId, ...body}
        : body;
      const options = body ? {
        method,
        headers: {
          "Content-Type": "application/json",
          "X-Morphic-Session": state.clientSessionId
        },
        body: JSON.stringify(payload)
      } : {headers: {"X-Morphic-Session": state.clientSessionId}};
      return fetch(appPath(path), options).then(async (response) => {
        const text = await response.text();
        let payload = null;
        try {
          payload = JSON.parse(text);
        } catch (parseError) {
          payload = null;
        }
        if (!response.ok) {
          const snippet = String(text || "").trim().slice(0, 200);
          const detail = payload && typeof payload === "object" ? (payload.detail || payload.error) : "";
          const error = new Error(detail || (snippet ? `HTTP ${response.status}: ${snippet}` : `HTTP ${response.status}`));
          error.payload = payload !== null ? payload : {error: snippet};
          throw error;
        }
        if (payload === null) {
          throw new Error(`HTTP ${response.status}: response was not JSON`);
        }
        return payload;
	      });
	    }

    async function requestJsonStream(path, body, onEvent) {
      const payload = body && typeof body === "object" && !Array.isArray(body)
        ? {client_session_id: state.clientSessionId, ...body}
        : body;
      const response = await fetch(appPath(path), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Morphic-Session": state.clientSessionId
        },
        body: JSON.stringify(payload)
      });
      const contentType = response.headers.get("content-type") || "";
      if (!response.ok) {
        const errorPayload = contentType.includes("application/json") ? await response.json() : {error: await response.text()};
        const error = new Error(errorPayload.detail || errorPayload.error || errorPayload.run_blocker || `HTTP ${response.status}`);
        error.payload = errorPayload;
        throw error;
      }
      if (!response.body || !contentType.includes("application/x-ndjson")) {
        return response.json();
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalPayload = null;
      while (true) {
        const {value, done} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (onEvent) onEvent(event);
          if (event.event === "result") finalPayload = event.payload;
        }
      }
      if (buffer.trim()) {
        const event = JSON.parse(buffer);
        if (onEvent) onEvent(event);
        if (event.event === "result") finalPayload = event.payload;
      }
      if (!finalPayload) throw new Error("Production run ended without a result payload.");
      return finalPayload;
    }

    function formatBytes(value) {
      const bytes = Number(value || 0);
      if (!Number.isFinite(bytes)) return "";
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    function clearExecutionOutputs() {
      $("executionLog").textContent = "";
      renderArtifactManifest(null);
    }

    function appendExecutionLog(stream, text) {
      const prefix = stream && stream !== "stdout" ? `[${stream}] ` : "";
      $("executionLog").textContent += `${prefix}${text || ""}`;
      $("executionLog").scrollTop = $("executionLog").scrollHeight;
    }

    function renderArtifactManifest(manifest) {
      const container = $("artifactManifest");
      container.innerHTML = "";
      const files = (manifest && manifest.files) || [];
      if (!files.length) {
        container.classList.add("empty");
        container.textContent = "No produced files recorded yet.";
        return;
      }
      container.classList.remove("empty");
      for (const file of files) {
        const item = document.createElement("div");
        item.className = "artifact-item";
        const name = document.createElement("div");
        name.className = "artifact-name";
        name.textContent = file.relative_path || file.name || file.path || "artifact";
        const meta = document.createElement("div");
        meta.className = "artifact-meta";
        meta.textContent = [
          file.description || file.artifact_type || "Output file produced by the run.",
          file.artifact_type ? `type: ${file.artifact_type}` : "",
          formatBytes(file.size_bytes),
          file.viewer ? `viewer: ${file.viewer}` : "no viewer",
          file.path
        ].filter(Boolean).join(" / ");
        const actions = document.createElement("div");
        actions.className = "artifact-actions";
        if (file.view_url) {
          const view = document.createElement("a");
          view.href = appPath(file.view_url);
          view.target = "_blank";
          view.rel = "noopener noreferrer";
          view.textContent = "View";
          actions.appendChild(view);
        }
        if (file.download_url) {
          const download = document.createElement("a");
          download.href = appPath(file.download_url);
          download.textContent = "Download";
          actions.appendChild(download);
        }
        item.append(name, meta, actions);
        container.appendChild(item);
      }
    }

    function executionTargetLine(payload) {
      const location = payload.execution_location || {};
      const dispatch = payload.execution_dispatch || {};
      const locationId = normalizeExecutionLocation(location.location_id || location.kind || state.executionLocation);
      if (locationId === "remote_ssh") {
        const host = dispatch.remote_host || location.metadata?.remote_host || "";
        const workdir = dispatch.remote_workdir || location.metadata?.remote_workdir || "";
        return [
          "Execution target: Remote SSH",
          host ? `host ${host}` : "",
          workdir ? `bundle ${workdir}` : "",
        ].filter(Boolean).join(" / ");
      }
      if (locationId === "scheduler_remote_ssh") {
        const host = dispatch.remote_host || location.metadata?.remote_host || "";
        const workdir = dispatch.remote_workdir || location.metadata?.remote_workdir || "";
        return [
          "Execution target: SSH via Temporal scheduler",
          host ? `host ${host}` : "",
          workdir ? `remote workdir ${workdir}` : "",
        ].filter(Boolean).join(" / ");
      }
      if (locationId === "scheduler_temporal") return "Execution target: Local Temporal scheduler";
      if (locationId === "local") return "Execution target: My local shell";
      return "Execution target: shared Workbench server";
    }

    function renderExecutionPayload(payload) {
      state.lastExecution = payload;
      state.runId = payload.run_id || state.runId || "";
      showRaw(payload);
      const result = payload.execution_result || {};
      const manifest = payload.artifact_manifest || result.artifact_manifest || {files: []};
      if (!$("executionLog").textContent.trim()) {
        if (result.stdout_tail) appendExecutionLog("stdout", result.stdout_tail.endsWith("\n") ? result.stdout_tail : `${result.stdout_tail}\n`);
        if (result.stderr_tail) appendExecutionLog("stderr", result.stderr_tail.endsWith("\n") ? result.stderr_tail : `${result.stderr_tail}\n`);
      }
      renderArtifactManifest(manifest);
      const fileCount = manifest.file_count ?? (manifest.files || []).length;
      const targetLine = executionTargetLine(payload);
      const targetLabel = targetLine.replace(/^Execution target: /, "");
      $("runText").textContent = [
        `Execution: ${payload.status || result.status || "unknown"}`,
        targetLine,
        payload.execution_id ? `Execution id: ${payload.execution_id}` : "",
        `Files produced: ${fileCount}`,
        fileCount ? "Use the Output Manifest below to view or download produced files." : "No produced files were recorded for this run.",
      ].filter(Boolean).join("\n");
      addMessage("agent", `${targetLabel} run ${payload.status}. ${fileCount} produced file${fileCount === 1 ? "" : "s"} recorded.`);
      updateRunControls();
      setStatus(payload.status === "failed" ? "run failed" : "run complete", payload.status === "failed" ? "bad-text" : "good-text");
    }

    function shortList(items, fallback = "none", limit = 4) {
      const values = (items || []).filter(Boolean).map((item) => String(item));
      if (!values.length) return fallback;
      if (values.length <= limit) return values.join(", ");
      return `${values.slice(0, limit).join(", ")} + ${values.length - limit} more`;
    }

    function artifactLabel(item) {
      if (!item) return "";
      return [item.name, item.artifact_type].filter(Boolean).join(" / ");
    }

    function validationLabel(graph) {
      const validation = graph?.latest_validation || {};
      if (!validation || !validation.status) return "none";
      const parts = [
        validation.status,
        validation.comparator_kind || validation.validation_kind,
        validation.fixture_id,
      ].filter(Boolean);
      return parts.join(" / ");
    }

    function renderPlan(graph) {
      if (!graph) {
        $("planEmpty").classList.remove("hidden");
        $("planContent").classList.add("hidden");
        return;
      }
      $("planEmpty").classList.add("hidden");
      $("planContent").classList.remove("hidden");
      $("planTitle").textContent = graph.title || graph.graph_id || "Workflow draft";
      $("planConfidence").textContent = graph.confidence_tier || "unclassified";
      $("planMaterialization").textContent = graph.materialization_status || "draft";
      $("planValidation").textContent = validationLabel(graph);
      $("planInputs").textContent = shortList((graph.inputs || []).map(artifactLabel), "none declared", 8);
      $("planOutputs").textContent = shortList((graph.outputs || []).map(artifactLabel), "none declared", 8);
      const modules = $("planModules");
      modules.innerHTML = "";
      for (const node of graph.nodes || []) {
        const card = document.createElement("div");
        card.className = "module-card";
        const body = document.createElement("div");
        const title = document.createElement("div");
        title.className = "module-title";
        title.textContent = node.label || node.module_id || node.id || "Module";
        const meta = document.createElement("div");
        meta.className = "module-meta";
        meta.textContent = node.module_id || node.id || "";
        body.append(title, meta);
        const badge = document.createElement("span");
        badge.className = "badge";
        badge.textContent = node.confidence_tier || "module";
        card.append(body, badge);
        modules.appendChild(card);
      }
      const blockers = [graph.run_blocker, ...(state.lastResponse?.planner_state?.blockers || [])].filter(Boolean);
      $("planBlockers").classList.toggle("hidden", !blockers.length);
      $("planBlockers").textContent = blockers.length ? `Blockers: ${blockers.join("; ")}` : "";
    }

    function detailSection(title, items) {
      const section = document.createElement("div");
      section.className = "detail-section";
      const heading = document.createElement("h3");
      heading.textContent = title;
      section.appendChild(heading);
      const list = document.createElement("ul");
      for (const item of items.filter(Boolean)) {
        const li = document.createElement("li");
        li.textContent = item;
        list.appendChild(li);
      }
      section.appendChild(list);
      return section;
    }

    function renderDetails(payload = null) {
      const view = $("detailView");
      view.innerHTML = "";
      const current = payload || state.lastResponse || {};
      const statusItems = [
        `Status: ${current.status || "ready"}`,
        state.runId ? `Run: ${state.runId}` : "",
        current.model ? `Model: ${current.model.provider || "provider"} / ${current.model.name || "model"}` : "",
        current.proposed_action?.action ? `Next action: ${current.proposed_action.action}` : "",
      ];
      view.appendChild(detailSection("Current", statusItems));
      if (state.graph) {
        const graph = state.graph;
        view.appendChild(detailSection("Plan", [
          `Workflow: ${graph.title || graph.graph_id}`,
          `Modules: ${shortList((graph.nodes || []).map((node) => node.label || node.module_id || node.id), "none")}`,
          `Inputs: ${shortList((graph.inputs || []).map(artifactLabel), "none")}`,
          `Outputs: ${shortList((graph.outputs || []).map(artifactLabel), "none")}`,
          `Confidence: ${graph.confidence_tier || "unclassified"}`,
          `Validation: ${validationLabel(graph)}`,
        ]));
        const blockers = [graph.run_blocker, ...(state.lastResponse?.planner_state?.blockers || [])].filter(Boolean);
        if (blockers.length) view.appendChild(detailSection("Blockers", blockers));
      } else {
        view.appendChild(detailSection("Plan", ["No workflow plan drafted."]));
      }
      if (state.bundlePath || state.scriptFresh || state.reviewed) {
        view.appendChild(detailSection("Run Directory", [
          state.bundlePath ? `Run directory: ${state.bundlePath}` : "",
          state.bundleExecutionLocation ? `Bundle locale: ${executionLocationLabel(state.bundleExecutionLocation)}` : "",
          state.scriptFresh ? "Script generated" : "",
          state.reviewed ? "Script reviewed" : "",
          state.lastPreflight ? `Preflight: ${state.lastPreflight.status || "checked"}` : "",
        ]));
      }
      if (state.recipeDraft) {
        view.appendChild(detailSection("Drafts", [
          `Recipe draft: ${state.recipeDraft.graph_id || "available"}`,
          "Review the raw draft in Advanced. Generate Run Directory renders the runnable script and run directory.",
        ]));
      }
    }

    function graphFields(graph) {
      const schema = graph?.params_schema || {};
      if (Array.isArray(schema.fields) && schema.fields.length) return schema.fields;
      const defaults = graph?.execution?.default_params || {};
      const seen = new Set();
      const fields = [];
      for (const item of [...(graph?.inputs || []), ...(graph?.outputs || [])]) {
        if (!item?.name || seen.has(item.name)) continue;
        seen.add(item.name);
        fields.push({
          name: item.name,
          label: item.name,
          type: "path",
          required: item.required !== false,
          artifact_type: item.artifact_type,
          default: defaults[item.name]
        });
      }
      for (const [name, value] of Object.entries(defaults)) {
        if (seen.has(name)) continue;
        fields.push({name, label: name, type: typeof value === "number" ? "integer" : "string", required: false, default: value});
      }
      return fields;
    }

    function fieldChoices(field) {
      if (Array.isArray(field?.choices)) return field.choices;
      if (Array.isArray(field?.enum)) return field.enum;
      return [];
    }

    function fieldIsStructured(field) {
      return field?.type === "array" || field?.type === "object";
    }

    function fieldIsDirectoryLike(field) {
      const text = [field?.path_kind, field?.artifact_type, field?.path_role, field?.name, field?.label, field?.description]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return field?.path_kind === "directory"
        || text.includes("directory")
        || text.includes("folder")
        || text.includes("outdir")
        || text.includes("_dir")
        || text.includes("index")
        || text.includes("base");
    }

    function fieldAcceptPattern(field) {
      const text = [field?.name, field?.label, field?.artifact_type, field?.description]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (field?.structured_artifact?.kind === "samplesheet" || text.includes("samplesheet") || text.includes("sample sheet")) return ".csv,.tsv,.txt";
      if (text.includes("fasta") || text.includes("faidx")) return ".fa,.fasta,.fna,.fa.gz,.fasta.gz,.fna.gz";
      if (text.includes("gtf")) return ".gtf,.gtf.gz";
      if (text.includes("gff")) return ".gff,.gff3,.gff.gz,.gff3.gz";
      if (text.includes("bed")) return ".bed,.bed.gz";
      if (text.includes("fastq")) return ".fastq,.fq,.fastq.gz,.fq.gz";
      if (text.includes("bam")) return ".bam";
      if (text.includes("h5ad")) return ".h5ad";
      if (text.includes("h5mu") || text.includes("mudata")) return ".h5mu";
      return "";
    }

    function paramGroups(graph, fields) {
      const schema = graph?.params_schema || {};
      const byName = new Map(fields.filter((field) => field?.name).map((field) => [field.name, field]));
      const assigned = new Set();
      const groups = [];
      for (const group of Array.isArray(schema.groups) ? schema.groups : []) {
        const groupFields = [];
        for (const name of group.fields || []) {
          const field = byName.get(name);
          if (!field) continue;
          groupFields.push(field);
          assigned.add(field.name);
        }
        if (!groupFields.length) continue;
        groups.push({
          id: group.id || group.title || `group_${groups.length + 1}`,
          title: group.title || group.id || "Parameters",
          description: group.description || "",
          advanced: Boolean(group.advanced),
          fields: groupFields
        });
      }
      const remaining = fields.filter((field) => field?.name && !assigned.has(field.name));
      const normal = remaining.filter((field) => !field.advanced);
      const advanced = remaining.filter((field) => field.advanced);
      if (normal.length) {
        groups.push({id: "parameters", title: "Parameters", description: "", advanced: false, fields: normal});
      }
      if (advanced.length) {
        groups.push({id: "advanced_parameters", title: "Advanced Parameters", description: "", advanced: true, fields: advanced});
      }
      return groups;
    }

    function initialParams(graph, existing = {}) {
      const out = {};
      for (const field of graphFields(graph)) {
        if (existing[field.name] !== undefined) out[field.name] = existing[field.name];
        else if (field.default !== undefined) out[field.name] = field.default;
        else if (field.template !== undefined) out[field.name] = field.template;
        else out[field.name] = "";
      }
      return out;
    }

    function syncParamsFromForm() {
      const next = {};
      document.querySelectorAll("[data-param-name]").forEach((input) => {
        const name = input.dataset.paramName;
        const type = input.dataset.paramType;
        let value = input.type === "checkbox" ? input.checked : input.value;
        if (type === "array" || type === "object") {
          const text = String(value || "");
          value = text.trim() ? JSON.parse(text) : (type === "array" ? [] : {});
        } else if (type === "integer") {
          value = String(value).trim() ? Number.parseInt(value, 10) : "";
        } else if (type === "number") {
          value = String(value).trim() ? Number.parseFloat(value) : "";
        } else if (type === "boolean") {
          value = Boolean(value);
        }
        next[name] = value;
      });
      state.params = next;
      $("paramJson").value = JSON.stringify(state.params, null, 2);
      return next;
    }

    function syncParamsFromJson() {
      state.params = JSON.parse($("paramJson").value || "{}");
      renderParamForm();
      return state.params;
    }

    function currentParams() {
      return syncParamsFromForm();
    }

    function markParamsEdited() {
      state.approved = false;
      state.scriptFresh = false;
      state.reviewed = false;
      state.lastPreflight = null;
      state.lastDiagnostic = null;
      $("paramState").textContent = "edited";
      $("scriptState").textContent = "stale";
      markStep("params", "warn");
      markStep("script", "blocked");
      markStep("run", "blocked");
      updateRunControls();
    }

    function fieldLooksPathLike(field) {
      const text = [field.name, field.label, field.artifact_type, field.description, field.path_kind, field.path_role]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return field.type === "path"
        || text.includes("path")
        || text.includes("file")
        || text.includes("dir")
        || text.includes("directory")
        || text.includes("prefix")
        || text.includes("fastq")
        || text.includes("bam")
        || text.includes("fasta")
        || text.includes("gtf")
        || text.includes("h5ad")
        || text.includes("h5mu")
        || text.includes("mudata")
        || text.includes("coldata")
        || text.includes("reads");
    }

    function insertTextAtCursor(input, text) {
      const start = Number.isInteger(input.selectionStart) ? input.selectionStart : input.value.length;
      const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : input.value.length;
      input.value = `${input.value.slice(0, start)}${text}${input.value.slice(end)}`;
      input.focus();
      const nextCursor = start + text.length;
      if (input.setSelectionRange) input.setSelectionRange(nextCursor, nextCursor);
      input.dispatchEvent(new Event("input", {bubbles: true}));
    }

    function setControlPathValue(input, path) {
      if (!input || !path) return;
      if (state.fileBrowser.mode === "insert" || input.tagName === "TEXTAREA") {
        const insertValue = (input.dataset.paramType === "array" || input.dataset.paramType === "object")
          ? JSON.stringify(path)
          : path;
        insertTextAtCursor(input, insertValue);
      } else {
        input.value = path;
        input.dispatchEvent(new Event("input", {bubbles: true}));
        input.focus();
      }
    }

    function useBrowserLocalFiles(input, files, options = {}) {
      const selected = Array.from(files || []).map((file) => file.webkitRelativePath || file.name).filter(Boolean);
      if (!selected.length) return;
      let value = selected.length === 1 ? selected[0] : selected;
      if (options.directory) {
        const roots = [...new Set(selected.map((path) => String(path).split("/")[0]).filter(Boolean))];
        value = roots.length === 1 ? roots[0] : roots;
      }
      if (input.tagName === "TEXTAREA") {
        insertTextAtCursor(input, JSON.stringify(value, null, 2));
      } else {
        input.value = Array.isArray(value) ? value.join(", ") : value;
        input.dispatchEvent(new Event("input", {bubbles: true}));
        input.focus();
      }
      setStatus("local file selected", "warn-text");
    }

    function fileBrowserEmpty(text) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = text;
      return empty;
    }

    function selectFileBrowserPath(path) {
      state.fileBrowser.selectedPath = path || "";
      $("fileBrowserUseBtn").disabled = !state.fileBrowser.selectedPath;
      document.querySelectorAll(".file-entry").forEach((entry) => {
        entry.classList.toggle("selected", entry.dataset.path === state.fileBrowser.selectedPath);
      });
    }

    function renderFileBrowser(payload) {
      state.fileBrowser.currentPath = payload.path || "";
      state.fileBrowser.parentPath = payload.parent || "";
      state.fileBrowser.roots = payload.roots || [];
      state.fileBrowser.selectedPath = payload.selected_path || "";
      $("fileBrowserPath").textContent = state.fileBrowser.currentPath || "Choose a server root.";
      $("fileBrowserUseBtn").disabled = !state.fileBrowser.selectedPath;
      $("fileBrowserUpBtn").disabled = !state.fileBrowser.parentPath;

      const roots = $("fileBrowserRoots");
      roots.innerHTML = "";
      for (const root of state.fileBrowser.roots) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = root.label || root.path;
        button.title = root.path;
        button.addEventListener("click", () => loadServerFileBrowser(root.path));
        roots.appendChild(button);
      }

      const entries = $("fileBrowserEntries");
      entries.innerHTML = "";
      if (payload.truncated) entries.appendChild(fileBrowserEmpty("Showing the first 500 entries. Narrow the directory if needed."));
      for (const entry of payload.entries || []) {
        const row = document.createElement("div");
        row.className = "file-entry";
        row.dataset.path = entry.path;
        if (entry.path === state.fileBrowser.selectedPath) row.classList.add("selected");
        const body = document.createElement("div");
        const name = document.createElement("div");
        name.className = "file-entry-name";
        name.textContent = entry.name || entry.path;
        const meta = document.createElement("div");
        meta.className = "file-entry-meta";
        meta.textContent = [entry.kind || "file", entry.size_bytes ? formatBytes(entry.size_bytes) : "", entry.path].filter(Boolean).join(" / ");
        body.append(name, meta);
        const actions = document.createElement("div");
        actions.className = "file-entry-actions";
        if (entry.is_dir) {
          const open = document.createElement("button");
          open.type = "button";
          open.textContent = "Open";
          open.addEventListener("click", () => loadServerFileBrowser(entry.path));
          actions.appendChild(open);
        }
        const select = document.createElement("button");
        select.type = "button";
        select.textContent = "Select";
        select.addEventListener("click", () => selectFileBrowserPath(entry.path));
        actions.appendChild(select);
        row.addEventListener("dblclick", () => {
          if (entry.is_dir) loadServerFileBrowser(entry.path);
          else selectFileBrowserPath(entry.path);
        });
        row.append(body, actions);
        entries.appendChild(row);
      }
      if (!(payload.entries || []).length) entries.appendChild(fileBrowserEmpty("No visible entries in this directory."));
    }

    async function loadServerFileBrowser(path = "") {
      $("fileBrowserEntries").innerHTML = "";
      $("fileBrowserEntries").appendChild(fileBrowserEmpty("Loading..."));
      const query = path ? `?path=${encodeURIComponent(path)}` : "";
      try {
        const payload = await requestJson(`/api/files/browse${query}`);
        renderFileBrowser(payload);
        setStatus("browsing files");
      } catch (error) {
        if (path) {
          setStatus("choose a root", "warn-text");
          await loadServerFileBrowser("");
          return;
        }
        $("fileBrowserEntries").innerHTML = "";
        $("fileBrowserEntries").appendChild(fileBrowserEmpty(error.message || "File browser request failed."));
        showRaw(error.payload || {error: String(error)});
        setStatus("browse blocked", "bad-text");
      }
    }

    function openServerFileBrowser(input, mode = "replace") {
      state.fileBrowser.target = input;
      state.fileBrowser.mode = mode;
      state.fileBrowser.selectedPath = "";
      $("fileBrowserModal").classList.remove("hidden");
      const startPath = mode === "replace" ? String(input.value || "").trim() : "";
      loadServerFileBrowser(startPath);
    }

    function closeServerFileBrowser() {
      $("fileBrowserModal").classList.add("hidden");
      state.fileBrowser.target = null;
      state.fileBrowser.selectedPath = "";
    }

    function useSelectedServerPath() {
      if (!state.fileBrowser.target || !state.fileBrowser.selectedPath) return;
      setControlPathValue(state.fileBrowser.target, state.fileBrowser.selectedPath);
      closeServerFileBrowser();
      setStatus("path selected", "good-text");
    }

    function appendPathTools(field, input, control) {
      const structured = field.type === "array" || field.type === "object";
      const pathLike = fieldLooksPathLike(field);
      if (!structured && !pathLike) return;
      const tools = document.createElement("div");
      tools.className = "path-tools";
      const directoryLike = fieldIsDirectoryLike(field);

      const serverButton = document.createElement("button");
      serverButton.type = "button";
      serverButton.textContent = structured ? "Insert Server Path" : "Browse Server";
      serverButton.title = "Browse paths that are visible to the Workbench server.";
      serverButton.addEventListener("click", () => openServerFileBrowser(input, structured ? "insert" : "replace"));
      tools.appendChild(serverButton);

      const localPicker = document.createElement("input");
      localPicker.type = "file";
      localPicker.className = "hidden";
      if (structured) localPicker.multiple = true;
      const accept = fieldAcceptPattern(field);
      if (accept) localPicker.accept = accept;
      localPicker.addEventListener("change", () => {
        useBrowserLocalFiles(input, localPicker.files);
        localPicker.value = "";
      });
      const localButton = document.createElement("button");
      localButton.type = "button";
      localButton.textContent = structured ? "Insert Local Name" : "Choose Local File";
      localButton.title = "Choose a browser-local file name. Browsers do not expose a server-readable absolute path.";
      localButton.addEventListener("click", () => localPicker.click());
      tools.appendChild(localButton);

      let localDirectoryPicker = null;
      if (directoryLike || structured) {
        localDirectoryPicker = document.createElement("input");
        localDirectoryPicker.type = "file";
        localDirectoryPicker.className = "hidden";
        localDirectoryPicker.multiple = true;
        localDirectoryPicker.webkitdirectory = true;
        localDirectoryPicker.addEventListener("change", () => {
          useBrowserLocalFiles(input, localDirectoryPicker.files, {directory: true});
          localDirectoryPicker.value = "";
        });
        const directoryButton = document.createElement("button");
        directoryButton.type = "button";
        directoryButton.textContent = structured ? "Insert Local Folder" : "Choose Local Folder";
        directoryButton.title = "Choose a browser-local folder name. Browsers expose relative names, not server-readable absolute paths.";
        directoryButton.addEventListener("click", () => localDirectoryPicker.click());
        tools.appendChild(directoryButton);
      }

      const hint = document.createElement("div");
      hint.className = "field-hint";
      hint.textContent = structured
        ? "Insert paths at the cursor, then adjust the JSON structure if needed."
        : "Server Browse writes a server-readable path. Local selection records the browser file name only.";
      control.append(tools, localPicker);
      if (localDirectoryPicker) control.appendChild(localDirectoryPicker);
      control.appendChild(hint);
    }

    function createParamInput(field, value) {
      const choices = fieldChoices(field);
      let input;
      let controlElement;
      if (field.type === "boolean") {
        input = document.createElement("input");
        input.type = "checkbox";
        input.checked = value === true || value === "true" || value === 1 || value === "1";
        const label = document.createElement("label");
        label.className = "checkbox-control";
        const text = document.createElement("span");
        text.textContent = input.checked ? "Enabled" : "Disabled";
        input.addEventListener("change", () => {
          text.textContent = input.checked ? "Enabled" : "Disabled";
        });
        label.append(input, text);
        controlElement = label;
      } else if (choices.length && !fieldIsStructured(field)) {
        input = document.createElement("select");
        if (!field.required) {
          const blank = document.createElement("option");
          blank.value = "";
          blank.textContent = "";
          input.appendChild(blank);
        }
        for (const choice of choices) {
          const option = document.createElement("option");
          option.value = String(choice);
          option.textContent = String(choice);
          input.appendChild(option);
        }
        const stringValue = value === undefined || value === null ? "" : String(value);
        if (stringValue && !choices.map((choice) => String(choice)).includes(stringValue)) {
          const current = document.createElement("option");
          current.value = stringValue;
          current.textContent = stringValue;
          input.appendChild(current);
        }
        input.value = stringValue;
        controlElement = input;
      } else if (fieldIsStructured(field)) {
        input = document.createElement("textarea");
        input.value = JSON.stringify(value ?? (field.type === "array" ? [] : {}), null, 2);
        controlElement = input;
      } else {
        input = document.createElement("input");
        input.type = field.type === "integer" || field.type === "number" ? "number" : "text";
        if (field.type === "integer") input.step = "1";
        if (field.type === "number") input.step = "any";
        if (field.minimum !== undefined) input.min = String(field.minimum);
        if (field.maximum !== undefined) input.max = String(field.maximum);
        if (field.minLength !== undefined) input.minLength = Number(field.minLength);
        if (field.maxLength !== undefined) input.maxLength = Number(field.maxLength);
        if (field.pattern) input.pattern = String(field.pattern);
        input.value = String(value ?? "");
        controlElement = input;
      }
      input.dataset.paramName = field.name;
      input.dataset.paramType = field.type || "string";
      input.addEventListener("input", markParamsEdited);
      input.addEventListener("change", markParamsEdited);
      return {input, controlElement};
    }

    function appendFieldHints(field, control) {
      const hints = [];
      if (field.description) hints.push(String(field.description));
      if (field.help_text) hints.push(String(field.help_text));
      if (field.markdown_description && field.markdown_description !== field.description) hints.push(String(field.markdown_description));
      if (field.structured_artifact?.kind === "samplesheet") {
        const schemaPath = field.structured_artifact.schema_path ? ` (${field.structured_artifact.schema_path})` : "";
        hints.push(`Samplesheet input${schemaPath}`);
      }
      const constraints = [];
      if (field.minimum !== undefined) constraints.push(`min ${field.minimum}`);
      if (field.maximum !== undefined) constraints.push(`max ${field.maximum}`);
      if (field.minItems !== undefined) constraints.push(`min items ${field.minItems}`);
      if (field.maxItems !== undefined) constraints.push(`max items ${field.maxItems}`);
      if (constraints.length) hints.push(`Constraints: ${constraints.join(", ")}`);
      for (const text of hints.filter(Boolean)) {
        const hint = document.createElement("div");
        hint.className = "field-hint";
        hint.textContent = text;
        control.appendChild(hint);
      }
    }

    function renderParamRow(field) {
      const row = document.createElement("div");
      row.className = field.advanced ? "row advanced-param" : "row";
      const info = document.createElement("div");
      const name = document.createElement("div");
      name.className = "field-name";
      name.textContent = field.label || field.name;
      const meta = document.createElement("div");
      meta.className = "field-meta";
      meta.textContent = [
        field.name,
        field.required ? "required" : "optional",
        field.type || "string",
        field.artifact_type,
        field.path_role,
        field.advanced ? "advanced" : ""
      ].filter(Boolean).join(" / ");
      info.append(name, meta);
      const value = state.params[field.name] ?? "";
      const {input, controlElement} = createParamInput(field, value);
      const control = document.createElement("div");
      control.className = "field-control";
      control.appendChild(controlElement);
      appendPathTools(field, input, control);
      appendFieldHints(field, control);
      row.append(info, control);
      return row;
    }

    function renderParamGroup(group) {
      const details = document.createElement("details");
      details.className = group.advanced ? "param-group param-group-advanced" : "param-group";
      details.open = !group.advanced;
      const summary = document.createElement("summary");
      const title = document.createElement("span");
      title.className = "param-group-title";
      title.textContent = group.title || "Parameters";
      const meta = document.createElement("span");
      meta.className = "param-group-meta";
      meta.textContent = [group.fields.length === 1 ? "1 field" : `${group.fields.length} fields`, group.advanced ? "advanced" : ""].filter(Boolean).join(" / ");
      summary.append(title, meta);
      details.appendChild(summary);
      if (group.description) {
        const description = document.createElement("div");
        description.className = "param-group-description";
        description.textContent = group.description;
        details.appendChild(description);
      }
      const body = document.createElement("div");
      body.className = "param-group-body";
      for (const field of group.fields) {
        body.appendChild(renderParamRow(field));
      }
      details.appendChild(body);
      return details;
    }

    function renderParamForm() {
      const form = $("paramForm");
      form.innerHTML = "";
      const fields = graphFields(state.graph);
      if (!fields.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No parameter form is available yet.";
        form.appendChild(empty);
      }
      for (const group of paramGroups(state.graph, fields)) {
        form.appendChild(renderParamGroup(group));
      }
      $("paramJson").value = JSON.stringify(state.params, null, 2);
    }

    function loadGraph(graph, params = null) {
      state.graph = graph;
      state.graphId = graph?.graph_id || "";
      state.runId = "";
      state.params = params || initialParams(graph, state.params);
      state.approved = false;
      state.script = "";
      state.scriptFresh = false;
      state.reviewed = false;
      state.bundlePath = "";
      state.lastPreflight = null;
      state.lastExecution = null;
      state.lastDiagnostic = null;
      state.lastExecutionReview = null;
      state.pendingExecutionReview = null;
      state.recipeDraft = null;
      state.bundleExecutionLocation = "";
      $("workflowState").textContent = graph?.title || "none";
      $("graphState").textContent = state.graphId || "none";
      $("paramState").textContent = "review";
      $("scriptState").textContent = "waiting";
      $("bundleState").textContent = state.bundlePath || "none";
      $("runText").textContent = "";
      clearExecutionOutputs();
      $("graphView").textContent = JSON.stringify(graph || {}, null, 2);
      renderParamForm();
      renderPlan(graph);
      renderDetails();
      markStep("plan", "ready");
      markStep("params", "ready");
      markStep("script", "blocked");
      markStep("run", "blocked");
      updateRunControls();
    }

    function clearWorkbenchCanvas() {
      closeExpandedWorkspace();
      ["fileBrowserModal", "diagnosticModal", "executionReviewModal", "localRunModal"].forEach((id) => {
        const modal = $(id);
        if (modal) modal.classList.add("hidden");
      });
      state.graph = null;
      state.graphId = "";
      state.runId = "";
      state.params = {};
      state.approved = false;
      state.script = "";
      state.scriptFresh = false;
      state.reviewed = false;
      state.bundlePath = "";
      state.helperScripts = [];
      state.helperIndex = -1;
      state.lastResponse = null;
      state.lastPreflight = null;
      state.lastExecution = null;
      state.lastDiagnostic = null;
      state.lastExecutionReview = null;
      state.pendingExecutionReview = null;
      state.recipeDraft = null;
      state.executionLocation = "server";
      state.bundleExecutionLocation = "";
      state.threadId = "";
      state.activeConversation = null;
      persistConversationId("");
      state.activeWalkthroughDemoMode = false;
      state.activeWalkthroughId = "";
      state.fileBrowser = {target: null, mode: "replace", currentPath: "", parentPath: "", selectedPath: "", roots: []};
      $("messages").innerHTML = "";
      $("goal").value = "";
      $("workflowState").textContent = "none";
      $("graphState").textContent = "none";
      $("paramState").textContent = "waiting";
      $("scriptState").textContent = "waiting";
      $("bundleState").textContent = "none";
      $("runText").textContent = "";
      $("scriptEditor").value = "";
      $("graphView").textContent = "";
      $("paramJson").value = "{}";
      $("rawView").textContent = "";
      $("helperEditor").value = "";
      $("threadLogView").textContent = "";
      setActiveConversation(null);
      renderHelperList();
      clearExecutionOutputs();
      renderPlan(null);
      renderParamForm();
      renderDetails();
      markStep("chat", "ready");
      markStep("plan", "blocked");
      markStep("params", "blocked");
      markStep("script", "blocked");
      markStep("run", "blocked");
      updateRunControls();
      switchPane("chat");
      addMessage("system", "Ready.");
      if (window.location.hash) window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      setStatus("blank", "good-text");
    }

    function applyPlannerResponse(payload, options = {}) {
      showRaw(options.rawPayload || payload);
      const graph = options.preserveGraph ? null : payload.workflow_graph || payload.recipe_draft?.workflow_graph;
      if (graph) {
        const params = payload.params_json?.params ? {...initialParams(graph), ...payload.params_json.params} : null;
        loadGraph(graph, params);
      } else {
        renderDetails(payload);
      }
      const msg = payload.assistant_message || payload.run_blocker || `Selected ${payload.graph_id || payload.status || "workflow"}.`;
      addMessage("agent", msg);
    }

    async function runLlmTurn(goal, options = {}) {
      goal = String(goal || "").trim();
      if (!goal) return;
      if (options.addUser !== false) addMessage("user", goal);
      if (options.clearGoal !== false && $("goal").value.trim() === goal) $("goal").value = "";
      setStatus(options.status || "thinking");
      const wasDisabled = $("sendBtn").disabled;
      $("sendBtn").disabled = true;
      const thinking = addThinkingMessage();
      try {
        const payload = await requestJson("/v1/agent/chat", {
          thread_id: state.threadId || undefined,
          goal,
          require_model: Boolean(options.requireModel)
        });
        state.threadId = payload.thread_id || state.threadId;
        adoptConversation(payload);
        const loadedGraph = Boolean(!options.preserveGraph && (payload.workflow_graph || payload.recipe_draft?.workflow_graph));
        applyPlannerResponse(payload, {preserveGraph: Boolean(options.preserveGraph)});
        if (options.switchPane !== false) switchPane(loadedGraph ? "plan" : "chat");
        setStatus("ready", "good-text");
        return payload;
      } finally {
        removeThinkingMessage(thinking);
        $("sendBtn").disabled = wasDisabled;
      }
    }

    async function sendMessage() {
      await runLlmTurn($("goal").value);
    }

    const WALKTHROUGHS = {
      "00_assay_catalog": {
        title: "00 Assay catalog sanity check",
        prompt: "Tell me what assay and workflow types are available. I have paired-end FASTQ files.",
        note: "Seeded Walkthrough 00. Send this prompt to verify that the agent answers conversationally and asks for assay clarification before drafting."
      },
      "01_trimodal_quick_demo": {
        title: "01 Load Quick Demo: Trimodal MuData QC",
        quickDemo: true,
        prompt: "QC report for the trimodal MuData at data/demo_trimodal_small.h5mu",
        note: "Loads the existing demo artifact and drafts the runnable trimodal QC graph."
      },
      "02_bulk_pe_deseq2": {
        title: "02 Bulk paired-end RNA-seq with DESeq2",
        prompt: "Create a bulk paired-end RNA-seq DEG analysis with DESeq2. I have paired FASTQ files, no existing BAM, and I want sorted BAM output.",
        note: "Seeded Walkthrough 02. Send the prompt, then confirm with `yes, draft it` when the agent asks before drafting."
      },
      "03_bulk_plots": {
        title: "03 Bulk RNA-seq with volcano and heatmap plots",
        prompt: "Create a bulk paired-end RNA-seq workflow with DESeq2, volcano plots, and heatmaps.",
        note: "Seeded Walkthrough 03. Send the prompt, then confirm with `yes, draft it`; the expected graph includes a visualization renderer blocker."
      },
      "04_slam_seq": {
        title: "04 SLAM-seq conversation",
        prompt: "Can you work with SLAM Seq? I have paired-end FASTQs and want DEGs.",
        note: "Seeded Walkthrough 04. Send this prompt to verify that the assistant stays on SLAM-seq and does not silently substitute bulk RNA-seq."
      },
      "05_post_mex": {
        title: "05 STARsolo / post-MEX downstream modules",
        prompt: "I have STARsolo 10x MEX output. What downstream modules can the workbench help with?",
        note: "Seeded Walkthrough 05. Send this prompt to inspect post-MEX module discovery before drafting any graph."
      },
      "06_example_perturb_visualization": {
        title: "06 Example perturbation perturb-seq visualization suite",
        prompt: "Draft the Example perturbation perturb-seq visualization suite from existing smoke release artifacts. Include QC, UMAP, pseudobulk DESeq2, volcano plots, heatmaps, target correlations, and pathway enrichment.",
        note: "Seeded Walkthrough 06. Send the prompt, then confirm with `yes, draft it`; this is expected to expose graph-to-bundle blockers."
      },
      "07_chromap_atac": {
        title: "07 Chromap ATAC / scATAC",
        prompt: "Can the workbench help with ATAC-seq or single-cell ATAC using Chromap? I have paired-end FASTQs and want fragments, BAM, and MACS3 peaks.",
        note: "Seeded Walkthrough 07. Send this prompt to verify Chromap ATAC discovery without drafting a runnable graph."
      },
      "08_chromap_chip": {
        title: "08 Chromap ChIP-seq / TagAlign",
        prompt: "Can the workbench plan a ChIP-seq mapping workflow with Chromap and TagAlign output?",
        note: "Seeded Walkthrough 08. Send this prompt to verify Chromap ChIP-seq discovery."
      },
      "09_chromap_hic": {
        title: "09 Chromap Hi-C pairs",
        prompt: "Can the workbench plan a Hi-C pairs workflow with Chromap?",
        note: "Seeded Walkthrough 09. Send this prompt to verify Chromap Hi-C discovery."
      },
      "10_multiomics": {
        title: "10 Multiomics discovery",
        prompt: "What can the workbench do with multiome, CAT-ATAC, DOGMA-HIV, or four-factor MuData data?",
        note: "Seeded Walkthrough 10. Send this prompt to inspect distinct Multiomics recipe families. Only the trimodal QC quick demo is materialized here; CAT-ATAC and DOGMA-HIV remain separate operator-only surfaces."
      },
      "11_visualization_catalog": {
        title: "11 Visualization catalog",
        prompt: "What visualizations are available after differential expression or single-cell analysis?",
        note: "Seeded Walkthrough 11. Send this prompt to verify visualization discovery and active-context preservation."
      },
      "12_chromap_evidence_compose": {
        title: "12 Chromap ATAC evidence composition",
        prompt: "Compose Chromap ATAC BAM/fragments into ATAC evidence from peaks.",
        note: "Seeded Walkthrough 12. Loads a SQLite compatibility-edge composition without running suite jobs.",
        composePayload: {
          goal: "Compose Chromap ATAC BAM/fragments into ATAC evidence from peaks.",
          input_artifacts: ["fasta", "chromap_index", "fastq"],
          requested_outputs: ["atac_evidence_table"],
          capabilities: ["chromap"],
          include_launchpad: false
        }
      },
      "13_chromap_hic_pairs_compose": {
        title: "13 Chromap Hi-C suite recipe",
        prompt: "Load the Chromap Hi-C pairs suite recipe from paired FASTQs.",
        note: "Seeded Walkthrough 13. Loads the imported Chromap Hi-C suite recipe as a SQLite-backed graph node.",
        composePayload: {
          goal: "Load the Chromap Hi-C pairs suite recipe from paired FASTQs.",
          input_artifacts: ["fasta", "chromap_index", "fastq"],
          requested_outputs: ["hic_pairs"],
          capabilities: ["chromap", "hic"],
          include_launchpad: false
        }
      },
      "14_multiomics_mudata_builder_compose": {
        title: "14 Multiomics MuData builder suite recipe",
        prompt: "Load the Multiomics MuData builder suite recipe from 10x MEX artifacts.",
        note: "Seeded Walkthrough 14. Loads the imported Multiomics MuData builder as a SQLite-backed graph node.",
        composePayload: {
          goal: "Load the Multiomics MuData builder suite recipe from 10x MEX artifacts.",
          input_artifacts: ["tenx_mex"],
          requested_outputs: ["h5mu"],
          capabilities: ["multiomics", "multiome"],
          include_launchpad: false
        }
      },
      "15_multiomics_trimodal_report_compose": {
        title: "15 Multiomics trimodal report suite recipe",
        prompt: "Load the Multiomics suite report selected by the trimodal capability.",
        note: "Seeded Walkthrough 15. Loads the imported Multiomics trimodal report recipe instead of the curated quick-demo graph.",
        composePayload: {
          goal: "Load the Multiomics suite report selected by the trimodal capability.",
          input_artifacts: ["h5mu"],
          requested_outputs: ["html", "json", "png"],
          capabilities: ["multiomics", "report", "trimodal"],
          include_launchpad: false
        }
      },
      "16_nfcore_da_bulk_counts": {
        title: "16 nf-core differential abundance from bulk counts",
        prompt: "Load nf-core/differentialabundance as a wrapper recipe for the count matrix and sample metadata produced by the Workbench bulk RNA-seq recipe.",
        note: "Seeded Walkthrough 16. Harvests a local nf-core/differentialabundance schema fixture and loads the generated Nextflow wrapper graph without executing it.",
        nfcorePayload: {
          schema_path: "tests/fixtures/nfcore/differentialabundance_nextflow_schema.json",
          modules_json_path: "tests/fixtures/nfcore/downstream_modules.json",
          downstream_source: "bulk_pe_deseq2_v0",
          seededParams: {
            input: "tests/fixtures/nfcore/bulk_differentialabundance_samplesheet.tsv",
            contrasts: "tests/fixtures/nfcore/bulk_differentialabundance_contrasts.tsv",
            matrix: "tests/fixtures/deseq2_smoke/counts_matrix.tsv",
            outdir: "results/nfcore-differentialabundance-bulk",
            profile: "docker"
          }
        }
      },
      "17_nfcore_da_chromap_peak_counts": {
        title: "17 nf-core differential abundance from Chromap peaks",
        prompt: "Load nf-core/differentialabundance as a wrapper recipe for a peak-count matrix downstream of the Chromap ATAC evidence recipe.",
        note: "Seeded Walkthrough 17. Uses the same local nf-core/differentialabundance schema with Chromap-oriented seed parameters; no model or Nextflow execution is used.",
        nfcorePayload: {
          schema_path: "tests/fixtures/nfcore/differentialabundance_nextflow_schema.json",
          modules_json_path: "tests/fixtures/nfcore/downstream_modules.json",
          downstream_source: "composed_0c804cb7c5ed_v0",
          seededParams: {
            input: "tests/fixtures/nfcore/chromap_differentialabundance_samplesheet.tsv",
            contrasts: "tests/fixtures/nfcore/bulk_differentialabundance_contrasts.tsv",
            matrix: "tests/fixtures/nfcore/chromap_peak_counts.tsv",
            outdir: "results/nfcore-differentialabundance-chromap",
            profile: "docker"
          }
        }
      },
      "18_nfcore_atacseq_chromap_handoff": {
        title: "18 nf-core ATAC-seq Chromap handoff",
        prompt: "Load nf-core/atacseq as a wrapper recipe seeded from the tiny Chromap fixture FASTQs and reference FASTA.",
        note: "Seeded Walkthrough 18. Harvests a local nf-core/atacseq schema fixture to show the Nextflow wrapper contract for Chromap-compatible fixture inputs.",
        nfcorePayload: {
          schema_path: "tests/fixtures/nfcore/atacseq_nextflow_schema.json",
          modules_json_path: "tests/fixtures/nfcore/downstream_modules.json",
          downstream_source: "chromap_atac_bam_fragments",
          seededParams: {
            input: "tests/fixtures/nfcore/atacseq_samplesheet.csv",
            fasta: "tests/fixtures/chromap/reference.fa",
            outdir: "results/nfcore-atacseq-chromap-fixture",
            profile: "docker"
          }
        }
      }
    };

    function selectedWalkthrough() {
      return WALKTHROUGHS[$("walkthroughSelect").value] || WALKTHROUGHS["01_trimodal_quick_demo"];
    }

    function selectedWalkthroughAction() {
      return $("walkthroughActionMode")?.value || "start";
    }

    function walkthroughForceLlm() {
      return selectedWalkthroughAction() === "start" && Boolean($("walkthroughRequireLlm")?.checked);
    }

    function walkthroughProvenance(selected, overrides = {}) {
      return {
        schema: "morphic.launchpad_walkthrough_provenance/v0",
        walkthrough_id: $("walkthroughSelect").value,
        walkthrough_title: selected.title,
        prompt: selected.prompt,
        timestamp: new Date().toISOString(),
        ...overrides
      };
    }

    function seedWalkthroughPrompt(selected) {
      $("goal").value = selected.prompt;
      addMessage("agent", `Starting prompt only for ${selected.title}. Edit or send it when ready.`);
      showRaw(walkthroughProvenance(selected, {
        action: "starting_prompt_only",
        model_used: false,
        route: null,
        prompts: [{step: "start", prompt: selected.prompt}]
      }));
      switchPane("chat");
      $("goal").focus();
      setStatus("ready", "good-text");
    }

    function showWalkthroughPromptGuidance(selected) {
      $("goal").value = selected.prompt;
      const guidance = selected.note || "Use the starting prompt, then continue manually from the chat.";
      addMessage(
        "agent",
        `Prompt guidance for ${selected.title}.\n\nStarting prompt:\n${selected.prompt}\n\nGuidance:\n${guidance}`
      );
      showRaw(walkthroughProvenance(selected, {
        action: "prompt_guidance_only",
        model_used: false,
        route: null,
        prompts: [{step: "start", prompt: selected.prompt}],
        guidance
      }));
      switchPane("chat");
      $("goal").focus();
      setStatus("guidance ready", "good-text");
    }

    function walkthroughRequiresModel(selected, forceModel = false) {
      return Boolean(forceModel || (selected && !selected.quickDemo && !selected.composePayload && !selected.nfcorePayload));
    }

    function modelUnavailableMessage() {
      const status = state.modelStatus || {};
      return `Model-backed walkthroughs are disabled because the configured model is unavailable. ${status.error || "The model probe failed."}`;
    }

    function updateWalkthroughModeStatus() {
      const selected = selectedWalkthrough();
      const action = selectedWalkthroughAction();
      const requireLlm = $("walkthroughRequireLlm");
      if (requireLlm) requireLlm.disabled = action !== "start";
      let message = "";
      if (action === "starting_prompt") {
        message = "Starting prompt only: no route or model call; the prompt is copied into chat for manual use.";
      } else if (action === "prompt_guidance") {
        message = "Prompt guidance only: no route or model call; prompts and guidance are shown for manual use.";
      } else if (requireLlm?.checked) {
        message = "Start requires LLM input: the selected prompt is sent through the configured model path.";
      } else if (selected.quickDemo) {
        message = "Start uses a direct Workbench graph load through /api/graphs/draft; no model is used.";
      } else if (selected.composePayload) {
        message = "Start uses local registry composition through /api/compose; no model is used.";
      } else if (selected.nfcorePayload) {
        message = "Start harvests a local nf-core schema through /api/nfcore/harvest and loads the wrapper recipe; no model is used.";
      } else {
        message = "Start uses the agent/model path so the prompt can influence the selected result.";
      }
      if ($("walkthroughModeStatus")) $("walkthroughModeStatus").textContent = message;
    }

    function applyModelStatusToWalkthroughs() {
      const status = state.modelStatus || {};
      const unavailable = status.available === false && !status.checking;
      document.querySelectorAll("#walkthroughSelect option").forEach((option) => {
        const selected = WALKTHROUGHS[option.value];
        const requiresModel = walkthroughRequiresModel(selected);
        option.disabled = false;
        option.title = Boolean(requiresModel && unavailable) ? modelUnavailableMessage() : "";
      });
      if ($("modelWalkthroughStatus")) {
        if (status.checking) {
          $("modelWalkthroughStatus").textContent = "Checking model availability for conversation walkthroughs.";
        } else if (status.available === true) {
          const label = [status.provider || status.probe_provider || "model", status.model || status.probe_model || ""].filter(Boolean).join(" / ");
          $("modelWalkthroughStatus").textContent = `Model-backed walkthroughs enabled: ${label}.`;
        } else {
          $("modelWalkthroughStatus").textContent = `${modelUnavailableMessage()} Direct loads and prompt-only modes still work.`;
        }
      }
      updateWalkthroughModeStatus();
    }

    async function refreshModelStatus() {
      state.modelStatus = {available: false, checking: true, error: "Model probe is running."};
      applyModelStatusToWalkthroughs();
      try {
        const payload = await requestJson("/api/model/status?probe=1");
        state.modelStatus = {...payload, checking: false, probed: true};
      } catch (error) {
        const payload = error.payload || {};
        state.modelStatus = {
          ...payload,
          available: false,
          checking: false,
          probed: true,
          error: payload.error || error.message || "Model probe failed."
        };
      }
      applyModelStatusToWalkthroughs();
      return state.modelStatus;
    }

    async function ensureModelAvailableForWalkthrough(selected, forceModel = false) {
      if (!walkthroughRequiresModel(selected, forceModel)) return true;
      if (state.modelStatus.available !== true) {
        await refreshModelStatus();
      }
      if (state.modelStatus.available === true) return true;
      const message = modelUnavailableMessage();
      addMessage("agent", message);
      showRaw(walkthroughProvenance(selected, {
        action: "model_required",
        model_used: true,
        require_llm_input: Boolean(forceModel),
        route: "/v1/agent/chat",
        model_status: state.modelStatus
      }));
      setStatus("model unavailable", "bad-text");
      return false;
    }

    async function applyWalkthroughSelection() {
      const selected = selectedWalkthrough();
      const action = selectedWalkthroughAction();
      if (action === "starting_prompt") {
        seedWalkthroughPrompt(selected);
        return;
      }
      if (action === "prompt_guidance") {
        showWalkthroughPromptGuidance(selected);
        return;
      }
      const forceModel = walkthroughForceLlm();
      if (forceModel || walkthroughRequiresModel(selected)) {
        if (!(await ensureModelAvailableForWalkthrough(selected, forceModel))) {
          return;
        }
        $("goal").value = selected.prompt;
        showRaw(walkthroughProvenance(selected, {
          action: "sent_to_llm",
          model_used: true,
          require_llm_input: Boolean(forceModel),
          route: "/v1/agent/chat"
        }));
        await runLlmTurn(selected.prompt, {requireModel: true});
        return;
      }
      if (selected.quickDemo) {
        await loadQuickDemo(selected);
        return;
      }
      if (selected.composePayload) {
        await loadCompositionWalkthrough(selected);
        return;
      }
      if (selected.nfcorePayload) {
        await loadNfcoreWalkthrough(selected);
        return;
      }
    }

    async function loadNfcoreWalkthrough(selected) {
      $("goal").value = selected.prompt;
      addMessage("user", selected.prompt);
      setStatus("harvesting nf-core");
      const nfcorePayload = selected.nfcorePayload || {};
      const {seededParams = {}, downstream_source = null, ...harvestBody} = nfcorePayload;
      const payload = await requestJson("/api/nfcore/harvest", harvestBody);
      const graph = payload.workflow_graph;
      const params = {...initialParams(graph), ...seededParams};
      const provenance = walkthroughProvenance(selected, {
        action: "local_nfcore_schema_harvest",
        model_used: false,
        require_llm_input: false,
        route: "/api/nfcore/harvest",
        source_kind: "local_nfcore_schema",
        graph_id: graph?.graph_id || payload.graph_id || null,
        downstream_source,
        pipeline: graph?.runtime?.pipeline || graph?.runtime?.pipeline_name || null
      });
      showRaw({...payload, walkthrough: selected.title, seeded_params: params, walkthrough_provenance: provenance});
      loadGraph(graph, params);
      addMessage("agent", `Loaded ${selected.title} from a local nf-core schema through /api/nfcore/harvest. No model call or workflow execution was made.`);
      switchPane("plan");
      setStatus("ready", "good-text");
    }

    async function loadCompositionWalkthrough(selected) {
      $("goal").value = selected.prompt;
      addMessage("user", selected.prompt);
      setStatus("composing");
      const payload = await requestJson("/api/compose", selected.composePayload);
      const provenance = walkthroughProvenance(selected, {
        action: "local_registry_composition",
        model_used: false,
        require_llm_input: false,
        route: "/api/compose",
        source_kind: "registry_composition",
        graph_id: payload.workflow_graph?.graph_id || null
      });
      const rawPayload = {...payload, walkthrough: selected.title, walkthrough_provenance: provenance};
      applyPlannerResponse(payload, {rawPayload});
      addMessage("agent", `Loaded ${selected.title} through local registry composition. No model call was made.`);
      switchPane("plan");
      setStatus("ready", "good-text");
    }

    async function loadQuickDemo(selected = WALKTHROUGHS["01_trimodal_quick_demo"]) {
      const goal = "QC report for the trimodal MuData at data/demo_trimodal_small.h5mu";
      $("goal").value = goal;
      addMessage("user", goal);
      setStatus("loading demo");
      const payload = await requestJson("/api/graphs/draft", {
        goal,
        include_launchpad: false,
        thread_id: state.threadId || undefined,
        log_interaction: true
      });
      state.threadId = payload.thread_id || state.threadId;
      adoptConversation(payload);
      const graph = payload.workflow_graph;
      const params = {
        ...initialParams(graph),
        mudata: "data/demo_trimodal_small.h5mu",
        output_prefix: "/tmp/morphic-workbench-demo/trimodal_qc",
        title: "Demo trimodal QC",
      };
      const provenance = walkthroughProvenance(selected, {
        action: "direct_workbench_load",
        model_used: false,
        require_llm_input: false,
        route: "/api/graphs/draft",
        source_kind: "curated_graph",
        graph_id: graph?.graph_id || null
      });
      showRaw({...payload, demo_params: params, walkthrough_provenance: provenance});
      loadGraph(graph, params);
      addMessage(
        "agent",
        "Loaded a quick demo directly from the Workbench graph catalog; no model call was made. Review the plan, inspect the parameter form, then approve or edit before trying script generation."
      );
      switchPane("plan");
      setStatus("ready", "good-text");
    }

    async function applyWorkbenchHandoffFromLocation() {
      let handoff = null;
      try {
        handoff = workbenchHandoffFromLocation();
      } catch (error) {
        addMessage("agent", `Workbench handoff could not be decoded: ${error.message || error}`);
        setStatus("handoff blocked", "bad-text");
        return false;
      }
      if (!handoff) return false;
      if (!handoff.graph_id) {
        addMessage("agent", "Workbench handoff is missing graph_id.");
        setStatus("handoff blocked", "bad-text");
        return false;
      }
      setStatus("loading handoff");
      const graphPayload = await requestJson(`/api/graphs/${encodeURIComponent(handoff.graph_id)}`);
      const graph = graphPayload.workflow_graph || graphPayload;
      const params = handoff.params && typeof handoff.params === "object" ? handoff.params : null;
      loadGraph(graph, params);
      state.runId = handoff.run_id || state.runId || "";
      applyRemoteSshMetadata(handoff.execution_location_metadata || handoff.execution_location_request?.metadata || {});
      setExecutionLocation(handoff.execution_location || "server");
      if (handoff.bundle_path) {
        state.bundlePath = handoff.bundle_path;
        state.bundleExecutionLocation = state.executionLocation;
        $("bundleState").textContent = state.bundlePath;
        markStep("run", "ready");
        updateRunControls();
      }
      showRaw({status: "handoff_loaded", handoff, graph: graphPayload});
      addMessage("agent", `Loaded Workbench handoff for ${handoff.graph_id}.`);
      if (handoff.action === "open_execution_review") {
        switchPane("script");
        const reviewParams = currentParams();
        const reviewStage = handoff.review_stage || "before_render";
        requestExecutionReview(reviewParams, reviewStage, handoff.bundle_path || null)
          .then(async (review) => {
            if (review.status === "approved") {
              applyRemoteSshMetadata(review.approved_execution_location_request?.metadata || {});
              state.executionLocation = review.approved_execution_location || state.executionLocation;
              updateRunControls();
              addMessage("agent", `Execution review approved for ${executionLocationLabel(state.executionLocation)}.`);
              if (reviewStage === "before_render" && !handoff.bundle_path) {
                await renderBundleAfterApprovedReview(review, reviewParams);
              }
            }
          })
          .catch((error) => {
            showRaw(error.payload || {error: String(error)});
            setStatus("review blocked", "bad-text");
          });
      } else if (handoff.action === "open_execution_diagnostic") {
        switchPane("run");
        if (handoff.bundle_path) await runExecutionDiagnostic();
      } else {
        switchPane("params");
      }
      clearWorkbenchHandoffFromLocation();
      setStatus("handoff loaded", "good-text");
      return true;
    }

    function renderThreadLog(payload) {
      const turns = payload?.turns || [];
      if (!turns.length) {
        $("threadLogView").textContent = state.threadId ? "No turns recorded for this thread yet." : "No thread has been started yet.";
        return;
      }
      $("threadLogView").textContent = turns.map((turn) => {
        const payload = turn.payload || {};
        const text = turn.role === "user"
          ? (turn.goal || JSON.stringify(payload))
          : (payload.assistant_message || payload.summary || JSON.stringify(payload));
        const meta = turn.role === "assistant" && (payload.status || payload.graph_id)
          ? ` (${[payload.status, payload.graph_id].filter(Boolean).join(" ")})`
          : "";
        return `[${turn.created_at}] ${turn.role}${meta}: ${text}`;
      }).join("\n\n");
    }

    async function loadThreadLog() {
      if (!state.threadId) {
        renderThreadLog({turns: []});
        return;
      }
      setStatus("loading log");
      const payload = await requestJson(`/api/threads/${encodeURIComponent(state.threadId)}/turns?limit=50`);
      renderThreadLog(payload);
      setStatus("ready", "good-text");
    }

    async function explainPlan() {
      if (!state.graph) {
        addMessage("agent", "No active graph.");
        return;
      }
      const nodes = (state.graph.nodes || []).map((node) => `- ${node.label || node.module_id || node.id}`).join("\n");
      const edges = (state.graph.edges || []).map((edge) => `- ${edge.source} -> ${edge.target} (${edge.artifact_type || edge.edge_type || "edge"})`).join("\n");
      addMessage("agent", [`Graph: ${state.graph.title || state.graphId}`, nodes, edges, state.graph.run_blocker ? `Blocker: ${state.graph.run_blocker}` : ""].filter(Boolean).join("\n\n"));
    }

    async function validateParams() {
      const params = currentParams();
      showRaw({params});
      if (!state.graphId || state.graphId.startsWith("star_")) {
        $("paramState").textContent = "not required";
        addMessage("agent", "Parameter validation is not registered for this STAR MVP graph.");
        return true;
      }
      setStatus("validating");
      const payload = await requestJson(`/api/graphs/${encodeURIComponent(state.graphId)}/params/validate`, {params});
      showRaw(payload);
      if (payload.status === "valid") {
        $("paramState").textContent = "valid";
        markStep("params", "ready");
        addMessage("agent", "Parameters are valid.");
        return true;
      }
      $("paramState").textContent = "invalid";
      markStep("params", "warn");
      addMessage("agent", `Missing: ${(payload.missing_required_inputs || []).join(", ")}`);
      return false;
    }

    async function approveParams() {
      const ok = await validateParams();
      if (!ok) return;
      state.approved = true;
      $("paramState").textContent = "approved";
      markStep("script", "ready");
      addMessage("agent", "Parameters approved.");
      renderDetails();
      switchPane("script");
    }

    async function draftRecipe() {
      if (!state.graphId) return;
      const params = currentParams();
      setStatus("drafting");
      const payload = await requestJson("/api/compose/draft", {graph_id: state.graphId, params});
      applyPlannerResponse(payload);
      state.recipeDraft = payload.recipe_draft || payload;
      state.script = "";
      state.scriptFresh = false;
      state.reviewed = false;
      state.lastPreflight = null;
      state.lastDiagnostic = null;
      $("scriptEditor").value = "";
      $("scriptState").textContent = "waiting";
      markStep("script", "ready");
      addMessage("agent", payload.assistant_message || "Recipe draft is available in Advanced. Use Generate Run Directory to render a runnable script.");
      renderDetails(payload);
      setStatus("ready", "good-text");
    }

    function blockedScript(payload) {
      const reason = payload?.run_blocker || payload?.summary || "No runnable script was generated.";
      return [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Script generation is blocked for this workflow.",
        `echo ${JSON.stringify(reason)} >&2`,
        "exit 3",
        "",
      ].join("\n");
    }

    async function renderBundleAfterApprovedReview(review, params) {
      setStatus("generating");
      applyRemoteSshMetadata(review.approved_execution_location_request?.metadata || {});
      state.executionLocation = review.approved_execution_location || state.executionLocation;
      state.runId = review.run_id || state.runId || "";
      state.lastPreflight = null;
      state.reviewed = false;
      state.lastExecution = null;
      state.lastDiagnostic = null;
      clearExecutionOutputs();
      updateRunControls();

      let payload;
      if (state.graphId.startsWith("star_")) {
        payload = await requestJson("/api/star-mvp/materialize", {graph_id: state.graphId, params, thread_id: state.threadId || undefined, execution_location: executionLocationRequest()});
      } else {
        payload = await requestJson(`/api/graphs/${encodeURIComponent(state.graphId)}/render`, {params, thread_id: state.threadId || undefined, execution_location: executionLocationRequest(), run_id: state.runId || undefined});
      }
      showRaw(payload);
      const renderedRunId = payload.run_id || state.runId || "";
      if (payload.workflow_graph) loadGraph(payload.workflow_graph, params);
      state.runId = renderedRunId;
      applyRemoteSshMetadata(review.approved_execution_location_request?.metadata || {});
      state.executionLocation = review.approved_execution_location || state.executionLocation;
      state.bundlePath = payload.bundle_path || state.bundlePath;
      state.bundleExecutionLocation = payload.execution_location?.location_id || state.executionLocation;
      state.script = payload.headless?.script || "";
      state.scriptFresh = Boolean(state.script);
      state.reviewed = false;
      $("scriptEditor").value = state.script || blockedScript(payload);
      $("scriptState").textContent = state.script ? "generated" : "blocked";
      $("bundleState").textContent = state.bundlePath || "none";
      if (state.script) {
        markStep("script", "ready");
        $("runText").textContent = [
          "Review the generated script, then click Mark Reviewed before preflight.",
          payload.caller_run?.command ? `Caller-managed command: ${payload.caller_run.command}` : "",
          payload.headless?.command && !payload.caller_run?.command ? `Command after review and preflight: ${payload.headless.command}` : "",
        ].filter(Boolean).join("\n\n");
      } else {
        markStep("script", "warn");
        $("runText").textContent = payload.run_blocker || "No runnable script.";
      }
      addMessage("agent", payload.run_blocker || payload.summary || payload.status || "Generated run directory.");
      renderDetails(payload);
      updateRunControls();
      switchPane("script");
      setStatus("ready", "good-text");
      return payload;
    }

    async function generateScript() {
      if (!state.graphId) return;
      const params = currentParams();
      setStatus("generating");
      const review = await requestExecutionReview(params, "before_render", null);
      if (review.status !== "approved") {
        $("scriptState").textContent = "blocked";
        $("runText").textContent = review.run_blocker || "Execution review is required before generating a run directory.";
        addMessage("agent", $("runText").textContent);
        showRaw(review);
        updateRunControls();
        setStatus("review required", "warn-text");
        return;
      }
      await renderBundleAfterApprovedReview(review, params);
    }

    function markReviewed() {
      state.script = $("scriptEditor").value;
      state.reviewed = Boolean(state.script);
      if (!state.reviewed) return;
      $("scriptState").textContent = "reviewed";
      markStep("run", "ready");
      const runNext = state.executionLocation === "local"
        ? "The browser cannot start the final script for local execution; use Run Locally and start the bundle manually."
        : state.executionLocation === "remote_ssh"
          ? "If it passes, Run on Remote SSH will copy the bundle to the configured destination and start the selected launcher."
          : state.executionLocation === "scheduler_temporal"
            ? "If it passes, Run on Local Scheduler will submit the bundle to the Temporal scheduler."
            : state.executionLocation === "scheduler_remote_ssh"
              ? "If it passes, Run on SSH Scheduler will submit the bundle to a Temporal SSH Docker workflow."
            : "If it passes, Run on Workbench Server will be enabled.";
      $("runText").textContent = state.bundlePath
        ? `Run directory: ${state.bundlePath}\n\nExecution locale: ${executionLocationLabel(state.executionLocation)}.\n\nRun Preflight is now available. ${runNext}`
        : `Generate a run directory before running preflight.`;
      renderDetails();
      updateRunControls();
      switchPane("run");
    }

    function summarizePreflight(payload) {
      const checks = payload.checks || payload.output_contract_checks || [];
      const lines = [
        `Preflight: ${payload.status || "unknown"}`,
        payload.graph_id ? `Graph: ${payload.graph_id}` : "",
        payload.execution_location?.label ? `Execution locale: ${payload.execution_location.label}` : "",
        payload.execution_profile ? `Execution profile: ${payload.execution_profile}` : "",
        payload.run_blocker ? `Blocker: ${payload.run_blocker}` : "",
        (payload.status === "preflight_passed" || payload.executable_ready === true) && state.executionLocation !== "local"
          ? (state.executionLocation === "scheduler_remote_ssh" ? "Run on SSH Scheduler is available." : (state.executionLocation === "scheduler_temporal" ? "Run on Local Scheduler is available." : (state.executionLocation === "remote_ssh" ? "Run on Remote SSH is available." : "Run on Workbench Server is available.")))
          : "",
        "",
        "Checks:",
      ].filter((line) => line !== "");
      if (!checks.length) {
        lines.push("- No checks returned.");
      } else {
        for (const check of checks) {
          const status = check.status || (check.exists === true ? "pass" : check.exists === false ? "fail" : "unknown");
          const label = check.check || check.name || "check";
          const path = check.path ? ` (${check.path})` : "";
          lines.push(`- ${status}: ${label}${path}`);
        }
      }
      return lines.join("\n");
    }

    function summarizeDiagnostic(payload) {
      const blockers = payload.blockers || [];
      const actions = payload.action_items || [];
      const resolutions = payload.resolution_options || [];
      const requirements = payload.requirements || [];
      const checks = payload.checks || [];
      const container = payload.container || {};
      const lines = [
        `Diagnostic: ${payload.status || "unknown"}`,
        payload.graph_id ? `Graph: ${payload.graph_id}` : "",
        payload.bundle_path ? `Run directory: ${payload.bundle_path}` : "Run directory: not selected",
        payload.execution_location?.label ? `Execution locale: ${payload.execution_location.label}` : "",
        `API execution: ${payload.can_execute_in_api ? "available" : "blocked"}`,
        container.status ? `Container route: ${container.run_available ? "available" : container.status}` : "",
        container.command ? `Container command: ${container.command}` : "",
        container.image?.reference ? `Container image: ${container.image.reference}` : "",
        payload.run_blocker ? `Blocker: ${payload.run_blocker}` : "",
      ].filter(Boolean);
      lines.push("", "What is needed:");
      if (!requirements.length) {
        lines.push("- No recipe-specific requirements were returned.");
      } else {
        for (const requirement of requirements) {
          const name = requirement.name || "requirement";
          const kind = requirement.kind ? ` (${requirement.kind})` : "";
          const why = requirement.required_for ? `: ${requirement.required_for}` : "";
          const hint = requirement.check_hint ? ` [${requirement.check_hint}]` : "";
          lines.push(`- ${name}${kind}${why}${hint}`);
        }
      }
      lines.push("", "Blockers:");
      if (!blockers.length) {
        lines.push("- None reported.");
      } else {
        for (const blocker of blockers) lines.push(`- ${blocker}`);
      }
      lines.push("", "Next steps:");
      if (!actions.length) {
        lines.push("- No action needed for this locale.");
      } else {
        for (const action of actions) lines.push(`- ${action}`);
      }
      lines.push("", "Server-provided fixes:");
      if (!resolutions.length) {
        lines.push("- No resolution options were returned.");
      } else {
        for (const option of resolutions) {
          const tags = [
            option.recommended ? "recommended" : "",
            option.available === false ? "unavailable" : "available",
            option.api_managed ? "API-managed" : "caller-managed",
          ].filter(Boolean).join(", ");
          lines.push(`- ${option.label || option.id || "option"}${tags ? ` (${tags})` : ""}`);
          if (option.why) lines.push(`  ${option.why}`);
          for (const command of option.commands || []) lines.push(`  $ ${command}`);
          const requires = option.requires || [];
          if (requires.length) lines.push(`  Requires: ${requires.join("; ")}`);
        }
      }
      lines.push("", "Checks:");
      if (!checks.length) {
        lines.push("- No checks returned.");
      } else {
        for (const check of checks) {
          const status = check.status || "unknown";
          const label = check.check || check.name || "check";
          const path = check.path ? ` (${check.path})` : "";
          const reason = check.reason ? ` - ${check.reason}` : "";
          lines.push(`- ${status}: ${label}${path}${reason}`);
        }
      }
      return lines.join("\n");
    }

    function openExecutionDiagnostic(payload) {
      state.lastDiagnostic = payload;
      $("diagnosticText").textContent = summarizeDiagnostic(payload);
      $("diagnosticModal").classList.remove("hidden");
    }

    function closeExecutionDiagnostic() {
      $("diagnosticModal").classList.add("hidden");
    }

    function bundleArchiveName() {
      return `${state.graphId || "morphic-bundle"}.zip`;
    }

    function bundleFolderName() {
      if (state.graphId) return state.graphId;
      const parts = String(state.bundlePath || "").split("/").filter(Boolean);
      return parts[parts.length - 1] || "morphic-bundle";
    }

    function localRunCommands() {
      const archive = bundleArchiveName();
      const folder = bundleFolderName();
      return {
        docker: [
          `unzip -o ${archive}`,
          `cd ${folder}`,
          "./run.docker.sh",
        ].join("\n"),
        apptainer: [
          `unzip -o ${archive}`,
          `cd ${folder}`,
          "./run.apptainer.sh",
        ].join("\n"),
      };
    }

    function summarizeLocalRunOffer() {
      if (!state.bundlePath) return "Generate a run directory first.";
      const commands = localRunCommands();
      const lines = [
        "Browser JavaScript cannot directly start Docker or a shell on this machine.",
        "",
        "Use Download Bundle, unzip it where the input files are visible, then run one command from inside the bundle directory.",
        "",
        "Docker:",
        commands.docker,
        "",
        "Apptainer:",
        commands.apptainer,
        "",
        state.executionLocation === "local"
          ? "The local bundle expects manifests/path_bindings.json to contain paths visible from this shell."
          : "This bundle was generated for the Workbench server. For a local run, regenerate with My local shell selected or edit manifests/path_bindings.json.",
      ];
      return lines.join("\n");
    }

    function openLocalRunOffer() {
      $("localRunText").textContent = summarizeLocalRunOffer();
      $("localRunDownloadBtn").disabled = !state.bundlePath;
      $("localRunCopyDockerBtn").disabled = !state.bundlePath;
      $("localRunCopyApptainerBtn").disabled = !state.bundlePath;
      $("localRunModal").classList.remove("hidden");
    }

    function closeLocalRunOffer() {
      $("localRunModal").classList.add("hidden");
    }

    function openServerRunOffer(preflightPayload) {
      const graph = state.graphId ? `Graph: ${state.graphId}` : "";
      const bundle = state.bundlePath ? `Run directory: ${state.bundlePath}` : "";
      const checks = (preflightPayload?.checks || []).length;
      const schedulerExecution = state.executionLocation === "scheduler_temporal";
      const remoteExecution = state.executionLocation === "remote_ssh";
      const schedulerRemoteExecution = state.executionLocation === "scheduler_remote_ssh";
      $("serverRunText").textContent = [
        schedulerRemoteExecution ? "SSH scheduler preflight passed." : (schedulerExecution ? "Local scheduler preflight passed." : (remoteExecution ? "Remote SSH preflight passed." : "Server preflight passed.")),
        graph,
        bundle,
        checks ? `Checks passed: ${checks}` : "",
        "",
        schedulerRemoteExecution ? "Run on SSH Scheduler is ready." : (schedulerExecution ? "Run on Local Scheduler is ready." : (remoteExecution ? "Run on Remote SSH is ready." : "Run on Workbench Server is ready.")),
      ].filter(Boolean).join("\n");
      $("serverRunNowBtn").textContent = schedulerRemoteExecution ? "Run on SSH Scheduler Now" : (schedulerExecution ? "Run on Local Scheduler Now" : (remoteExecution ? "Run on Remote SSH Now" : "Run on Workbench Server Now"));
      $("serverRunNowBtn").disabled = false;
      $("serverRunModal").classList.remove("hidden");
      $("serverRunNowBtn").focus();
    }

    function closeServerRunOffer() {
      $("serverRunModal").classList.add("hidden");
    }

    async function copyLocalRunCommand(kind) {
      if (!state.bundlePath) return;
      const commands = localRunCommands();
      const text = commands[kind] || commands.docker;
      await navigator.clipboard.writeText(text);
      setStatus(`${kind} command copied`, "good-text");
    }

    async function runExecutionDiagnostic() {
      if (!state.graphId) return;
      setStatus("diagnosing location");
      const payload = await requestJson(`/api/graphs/${encodeURIComponent(state.graphId)}/execution-diagnostic`, {
        params: currentParams(),
        thread_id: state.threadId || undefined,
        run_id: state.runId || undefined,
        bundle_path: state.bundlePath || undefined,
        execution_location: executionLocationRequest(),
      });
      state.runId = payload.run_id || state.runId || "";
      state.lastDiagnostic = payload;
      showRaw(payload);
      openExecutionDiagnostic(payload);
      $("runText").textContent = summarizeDiagnostic(payload);
      updateRunControls();
      setStatus(payload.status === "ready" ? "location ready" : "location blocked", payload.status === "ready" ? "good-text" : "warn-text");
    }

    function executionLocationLabel(locationId) {
      const normalized = normalizeExecutionLocation(locationId);
      if (normalized === "local") return "My local shell";
      if (normalized === "remote_ssh") return "Remote SSH";
      if (normalized === "scheduler_temporal") return "Local Temporal scheduler";
      if (normalized === "scheduler_remote_ssh") return "Remote SSH via Temporal scheduler";
      return "Workbench server";
    }

    function summarizeExecutionReview(payload, selectedLocation = null) {
      const location = payload.proposed_execution_location || {};
      const validation = payload.params_validation || {};
      const items = payload.review_items || [];
      const selected = selectedLocation || location.location_id || state.executionLocation;
      const lines = [
        `Review: ${payload.status || "unknown"}`,
        payload.graph_title ? `Graph: ${payload.graph_title}` : "",
        payload.review_stage ? `Stage: ${payload.review_stage}` : "",
        location.label ? `Proposed locale: ${location.label}` : "",
        selected ? `Selected locale: ${executionLocationLabel(selected)}` : "",
        validation.status ? `Parameters: ${validation.status}` : "",
        payload.bundle_path ? `Bundle: ${payload.bundle_path}` : "",
        payload.run_blocker ? `Blocker: ${payload.run_blocker}` : "",
        "",
        "Review items:",
      ].filter((line) => line !== "");
      if (!items.length) {
        lines.push("- Review graph, parameters, paths, and execution locale.");
      } else {
        for (const item of items) lines.push(`- ${item}`);
      }
      return lines.join("\n");
    }

    function openExecutionReview(payload, params, reviewStage, bundlePath = null) {
      state.lastExecutionReview = payload;
      state.runId = payload.run_id || state.runId || "";
      applyRemoteSshMetadata(payload.proposed_execution_location?.metadata || payload.workbench_handoff?.payload?.execution_location_metadata || {});
      $("executionReviewLocation").value = payload.proposed_execution_location?.location_id || state.executionLocation;
      syncRemoteReviewFieldsFromState();
      setRemoteReviewFieldsVisible();
      $("executionReviewText").textContent = summarizeExecutionReview(payload, $("executionReviewLocation").value);
      $("executionReviewNotes").value = "";
      $("executionReviewApproveBtn").disabled = false;
      $("executionReviewApproveBtn").textContent = reviewStage === "before_render" && !bundlePath
        ? "Approve & Generate Run Directory"
        : "Approve";
      $("executionReviewModal").classList.remove("hidden");
      return new Promise((resolve) => {
        state.pendingExecutionReview = {resolve, params, reviewStage, bundlePath};
      });
    }

    function resolveExecutionReview(payload) {
      $("executionReviewModal").classList.add("hidden");
      const pending = state.pendingExecutionReview;
      state.pendingExecutionReview = null;
      if (pending && typeof pending.resolve === "function") pending.resolve(payload);
    }

    function cancelExecutionReview() {
      resolveExecutionReview({status: "cancelled", run_blocker: "User cancelled execution review."});
    }

    async function submitExecutionReview() {
      const pending = state.pendingExecutionReview;
      if (!pending || !state.graphId) return;
      setStatus("recording review");
      let remoteFields = {};
      if (["remote_ssh", "scheduler_remote_ssh"].includes($("executionReviewLocation").value)) {
        remoteFields = remoteReviewFields();
        applyRemoteSshMetadata(remoteFields);
      }
      const payload = await requestJson(`/api/graphs/${encodeURIComponent(state.graphId)}/execution-review`, {
        params: pending.params,
        thread_id: state.threadId || undefined,
        run_id: state.runId || undefined,
        bundle_path: pending.bundlePath || undefined,
        execution_location: executionLocationRequest(),
        review_stage: pending.reviewStage,
        human_review: {
          approved: true,
          execution_location: $("executionReviewLocation").value,
          verified_paths: true,
          notes: $("executionReviewNotes").value,
          ...remoteFields,
        },
      });
      state.runId = payload.run_id || state.runId || "";
      state.lastExecutionReview = payload;
      showRaw(payload);
      if (payload.status === "approved") {
        resolveExecutionReview(payload);
        setStatus("review approved", "good-text");
      } else {
        $("executionReviewText").textContent = summarizeExecutionReview(payload, $("executionReviewLocation").value);
        setStatus("review blocked", "bad-text");
      }
    }

    async function requestExecutionReview(params, reviewStage, bundlePath = null) {
      setStatus("requesting review");
      const payload = await requestJson(`/api/graphs/${encodeURIComponent(state.graphId)}/execution-review`, {
        params,
        thread_id: state.threadId || undefined,
        run_id: state.runId || undefined,
        bundle_path: bundlePath || undefined,
        execution_location: executionLocationRequest(),
        review_stage: reviewStage,
      });
      state.runId = payload.run_id || state.runId || "";
      state.lastExecutionReview = payload;
      showRaw(payload);
      if (payload.status !== "needs_user_input") return payload;
      return openExecutionReview(payload, params, reviewStage, bundlePath);
    }

    async function runPreflight() {
      if (!state.graphId) return;
      if (!state.bundlePath || !(state.script || $("scriptEditor").value)) {
        $("runText").textContent = "Generate the run directory before running preflight.";
        addMessage("agent", "Generate the run directory before running preflight.");
        updateRunControls();
        return;
      }
      if (!state.reviewed) {
        $("runText").textContent = "Review the generated script and click Mark Reviewed before running preflight.";
        addMessage("agent", "Review the generated script and click Mark Reviewed before running preflight.");
        updateRunControls();
        return;
      }
      if (state.bundleExecutionLocation && state.bundleExecutionLocation !== state.executionLocation) {
        $("runText").textContent = "Execution locale changed after this run directory was generated. Regenerate the run directory for the selected locale before preflight.";
        addMessage("agent", "Execution locale changed. Regenerate the run directory for the selected locale before preflight.");
        updateRunControls();
        return;
      }
      const params = currentParams();
      setStatus("preflighting");
      const payload = state.graphId.startsWith("star_")
        ? await requestJson("/api/star-mvp/preflight", {graph_id: state.graphId, params, thread_id: state.threadId || undefined, bundle_path: state.bundlePath || undefined, execution_location: executionLocationRequest()})
        : await requestJson(`/api/graphs/${encodeURIComponent(state.graphId)}/preflight`, {params, thread_id: state.threadId || undefined, run_id: state.runId || undefined, bundle_path: state.bundlePath || undefined, execution_location: executionLocationRequest()});
      state.runId = payload.run_id || state.runId || "";
      state.lastPreflight = payload;
      showRaw(payload);
      $("runText").textContent = summarizePreflight(payload);
      const passed = payload.status === "preflight_passed" || payload.executable_ready === true;
      markStep("run", passed ? "ready" : "warn");
      addMessage("agent", passed ? "Preflight passed." : `Preflight blocked: ${payload.run_blocker || payload.status || "review checks"}.`);
      updateRunControls();
      if (passed && state.executionLocation !== "local") {
        openServerRunOffer(payload);
      }
      setStatus(passed ? "preflight passed" : "preflight blocked", passed ? "good-text" : "bad-text");
    }

    async function runProduction() {
      if (!state.bundlePath) return;
      if (state.executionLocation === "local") {
        $("runText").textContent = "My local shell is caller-managed. Download or copy the run directory and run it outside the Workbench API.";
        updateRunControls();
        return;
      }
      const passed = state.lastPreflight && (state.lastPreflight.status === "preflight_passed" || state.lastPreflight.executable_ready === true);
      if (!passed) return;
      setStatus(state.executionLocation === "scheduler_remote_ssh" ? "running on ssh scheduler" : (state.executionLocation === "scheduler_temporal" ? "running on scheduler" : (state.executionLocation === "remote_ssh" ? "running on remote ssh" : "running on workbench server")));
      closeServerRunOffer();
      $("runProductionBtn").disabled = true;
      $("runProductionBtn").classList.remove("primary");
      $("executionLog").textContent = "";
      renderArtifactManifest(null);
      try {
        const payload = await requestJsonStream(`/api/graphs/${encodeURIComponent(state.graphId)}/execute-production/stream`, {
          params: currentParams(),
          thread_id: state.threadId || undefined,
          run_id: state.runId || undefined,
          bundle_path: state.bundlePath,
          execution_location: executionLocationRequest(),
          timeout: 120
        }, (event) => {
          if (event.event === "log") appendExecutionLog(event.stream || "stdout", event.text || "");
        });
        renderExecutionPayload(payload);
      } finally {
        updateRunControls();
      }
    }

    async function downloadRunDirectory() {
      if (!state.graphId || !state.bundlePath) return;
      const url = appPath(`/api/graphs/${encodeURIComponent(state.graphId)}/bundle.zip?bundle_path=${encodeURIComponent(state.bundlePath)}&client_session_id=${encodeURIComponent(state.clientSessionId)}`);
      const response = await fetch(url, {headers: {"X-Morphic-Session": state.clientSessionId}});
      if (!response.ok) {
        let payload = {status: "failed", message: response.statusText};
        try {
          payload = await response.json();
        } catch (error) {
          // Keep the simple fallback payload.
        }
        throw Object.assign(new Error(payload.run_blocker || payload.message || "Bundle download failed."), {payload});
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `${state.graphId || "morphic-bundle"}.zip`;
      link.click();
      URL.revokeObjectURL(objectUrl);
      setStatus("bundle downloaded", "good-text");
      if (state.executionLocation === "local") {
        $("runText").textContent = [
          `Downloaded run directory: ${state.graphId}.zip`,
          "Unzip it in your local shell, adjust manifests/path_bindings.json if needed, then run bash run.sh from inside the bundle directory.",
        ].join("\n\n");
      }
    }

    function renderHelperList() {
      const list = $("helperList");
      list.innerHTML = "";
      state.helperScripts.forEach((script, index) => {
        const button = document.createElement("button");
        button.className = "helper-item";
        button.textContent = script.path;
        button.addEventListener("click", () => {
          state.helperIndex = index;
          $("helperEditor").value = script.content || "";
        });
        list.appendChild(button);
      });
      if (state.helperIndex < 0 && state.helperScripts.length) {
        state.helperIndex = 0;
        $("helperEditor").value = state.helperScripts[0].content || "";
      }
    }

    async function loadHelpers() {
      setStatus("loading helpers");
      const payload = await requestJson("/api/suites/star/helper-scripts?workflow_id=example_perturb_star_suite_production");
      showRaw(payload);
      state.helperScripts = payload.scripts || [];
      state.helperIndex = -1;
      renderHelperList();
      setStatus("ready", "good-text");
    }

    async function downloadHelpers() {
      if (state.helperIndex >= 0) {
        state.helperScripts[state.helperIndex].content = $("helperEditor").value;
        state.helperScripts[state.helperIndex].modified = true;
      }
      const response = await fetch(appPath("/api/suites/star/helper-scripts/bundle"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({workflow_id: "example_perturb_star_suite_production", scripts: state.helperScripts})
      });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "star-helper-bundle-example_perturb_star_suite_production.zip";
      link.click();
      URL.revokeObjectURL(url);
    }

    document.querySelectorAll(".step").forEach((button) => button.addEventListener("click", () => switchPane(button.dataset.pane)));
    $("toParamsBtn").addEventListener("click", () => switchPane("params"));
    $("explainPlanFromPlanBtn").addEventListener("click", explainPlan);
    $("sendBtn").addEventListener("click", () => sendMessage().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("walkthroughSelect").addEventListener("change", updateWalkthroughModeStatus);
    $("walkthroughActionMode").addEventListener("change", updateWalkthroughModeStatus);
    $("walkthroughRequireLlm").addEventListener("change", updateWalkthroughModeStatus);
    $("quickDemoBtn").addEventListener("click", () => applyWalkthroughSelection().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("explainBtn").addEventListener("click", explainPlan);
    $("validateBtn").addEventListener("click", () => validateParams().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("approveBtn").addEventListener("click", () => approveParams().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("draftRecipeBtn").addEventListener("click", () => draftRecipe().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("generateBtn").addEventListener("click", () => generateScript().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("reviewScriptBtn").addEventListener("click", markReviewed);
    $("scriptEditor").addEventListener("input", () => {
      if (!state.scriptFresh && !state.reviewed) return;
      state.script = $("scriptEditor").value;
      state.reviewed = false;
      state.lastPreflight = null;
      state.lastExecution = null;
      state.lastDiagnostic = null;
      state.lastExecutionReview = null;
      $("scriptState").textContent = state.script ? "modified" : "waiting";
      $("runText").textContent = "Script changed. Mark Reviewed and rerun preflight before production execution.";
      clearExecutionOutputs();
      updateRunControls();
      renderDetails();
    });
    $("copyScriptBtn").addEventListener("click", () => navigator.clipboard.writeText($("scriptEditor").value || ""));
    $("preflightBtn").addEventListener("click", () => runPreflight().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("executionDiagnosticBtn").addEventListener("click", () => runExecutionDiagnostic().catch((error) => {
      const payload = error.payload || {status: "blocked", message: String(error), blockers: [String(error)]};
      showRaw(payload);
      openExecutionDiagnostic(payload);
      setStatus("diagnostic blocked", "bad-text");
    }));
    $("downloadBundleBtn").addEventListener("click", () => downloadRunDirectory().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("localRunBtn").addEventListener("click", openLocalRunOffer);
    $("localRunDownloadBtn").addEventListener("click", () => downloadRunDirectory().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("localRunCopyDockerBtn").addEventListener("click", () => copyLocalRunCommand("docker").catch((error) => { showRaw({error: String(error)}); setStatus("copy blocked", "bad-text"); }));
    $("localRunCopyApptainerBtn").addEventListener("click", () => copyLocalRunCommand("apptainer").catch((error) => { showRaw({error: String(error)}); setStatus("copy blocked", "bad-text"); }));
    $("localRunCloseBtn").addEventListener("click", closeLocalRunOffer);
    $("localRunDoneBtn").addEventListener("click", closeLocalRunOffer);
    $("serverRunCloseBtn").addEventListener("click", closeServerRunOffer);
    $("serverRunLaterBtn").addEventListener("click", closeServerRunOffer);
    $("serverRunNowBtn").addEventListener("click", () => runProduction().catch((error) => {
      showRaw(error.payload || {error: String(error)});
      setStatus("error", "bad-text");
    }));
    $("runProductionBtn").addEventListener("click", () => runProduction().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    document.querySelectorAll("[data-execution-location]").forEach((button) => button.addEventListener("click", () => {
      setExecutionLocation(button.dataset.executionLocation || "server");
    }));
    $("loadHelpersBtn").addEventListener("click", () => loadHelpers().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("loadThreadLogBtn").addEventListener("click", () => loadThreadLog().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("newConversationBtn").addEventListener("click", () => createConversation().catch(showConversationError));
    $("refreshConversationsBtn").addEventListener("click", () => refreshConversations().catch(showConversationError));
    $("renameConversationBtn").addEventListener("click", () => renameConversation().catch(showConversationError));
    $("forkConversationBtn").addEventListener("click", () => forkConversation().catch(showConversationError));
    $("archiveConversationBtn").addEventListener("click", () => archiveOrRestoreConversation().catch(showConversationError));
    $("conversationStatus").addEventListener("change", () => refreshConversations().catch(showConversationError));
    $("conversationSearch").addEventListener("input", () => {
      window.clearTimeout(state.conversationSearchTimer);
      state.conversationSearchTimer = window.setTimeout(() => refreshConversations().catch(showConversationError), 250);
    });
    $("downloadHelpersBtn").addEventListener("click", () => downloadHelpers().catch((error) => { showRaw(error.payload || {error: String(error)}); setStatus("error", "bad-text"); }));
    $("expandedWindowBtn").addEventListener("click", () => openPanelWindow());
    $("expandedCloseTabBtn").addEventListener("click", () => closeExpandedTab());
    $("expandedCloseBtn").addEventListener("click", closeExpandedWorkspace);
    $("clearWorkbenchBtn").addEventListener("click", () => clearWorkbenchCanvas());
    $("logoutBtn").addEventListener("click", endSession);
    $("fileBrowserCloseBtn").addEventListener("click", closeServerFileBrowser);
    $("fileBrowserCancelBtn").addEventListener("click", closeServerFileBrowser);
    $("fileBrowserUseBtn").addEventListener("click", useSelectedServerPath);
    $("fileBrowserRefreshBtn").addEventListener("click", () => loadServerFileBrowser(state.fileBrowser.currentPath));
    $("fileBrowserUpBtn").addEventListener("click", () => {
      if (state.fileBrowser.parentPath) loadServerFileBrowser(state.fileBrowser.parentPath);
    });
    $("fileBrowserModal").addEventListener("click", (event) => {
      if (event.target === $("fileBrowserModal")) closeServerFileBrowser();
    });
    $("diagnosticCloseBtn").addEventListener("click", closeExecutionDiagnostic);
    $("diagnosticDismissBtn").addEventListener("click", closeExecutionDiagnostic);
    $("diagnosticRawBtn").addEventListener("click", () => {
      showRaw(state.lastDiagnostic || {status: "not_run"});
      switchPane("details");
    });
    $("diagnosticModal").addEventListener("click", (event) => {
      if (event.target === $("diagnosticModal")) closeExecutionDiagnostic();
    });
    $("executionReviewCloseBtn").addEventListener("click", cancelExecutionReview);
    $("executionReviewCancelBtn").addEventListener("click", cancelExecutionReview);
    $("executionReviewApproveBtn").addEventListener("click", () => submitExecutionReview().catch((error) => {
      showRaw(error.payload || {error: String(error)});
      setStatus("review blocked", "bad-text");
    }));
    $("executionReviewLocation").addEventListener("change", () => {
      setRemoteReviewFieldsVisible();
      if (state.lastExecutionReview) {
        $("executionReviewText").textContent = summarizeExecutionReview(state.lastExecutionReview, $("executionReviewLocation").value);
      }
    });
    $("executionReviewModal").addEventListener("click", (event) => {
      if (event.target === $("executionReviewModal")) cancelExecutionReview();
    });
    $("localRunModal").addEventListener("click", (event) => {
      if (event.target === $("localRunModal")) closeLocalRunOffer();
    });
    $("serverRunModal").addEventListener("click", (event) => {
      if (event.target === $("serverRunModal")) closeServerRunOffer();
    });
    $("helperEditor").addEventListener("input", () => {
      if (state.helperIndex >= 0) {
        state.helperScripts[state.helperIndex].content = $("helperEditor").value;
        state.helperScripts[state.helperIndex].modified = true;
      }
    });

    initPanelExpansion();
    addMessage("system", "Ready.");
    renderPlan(null);
    renderParamForm();
    renderDetails();
    updateRunControls();
    applyModelStatusToWalkthroughs();
    refreshModelStatus().catch(() => applyModelStatusToWalkthroughs());
    applyWorkbenchHandoffFromLocation().catch((error) => {
      showRaw(error.payload || {error: String(error)});
      addMessage("agent", `Workbench handoff failed: ${error.message || error}`);
      setStatus("handoff blocked", "bad-text");
    });
    requestJson("/healthz").then((payload) => {
      $("service").textContent = `${payload.service}: ${payload.status}`;
      setStatus("ready", "good-text");
    }).catch(() => setStatus("offline", "bad-text"));
    loadSessionInfo()
      .then(() => refreshConversations({resume: true}))
      .catch(() => {
        $("sessionUser").textContent = "session unknown";
        $("sessionUser").title = "Session endpoint unavailable";
      });
  </script>
</body>
</html>
"""
