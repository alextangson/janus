const STATUS = {
  executed:  ["mdi:check-circle", "var(--success-color, #43a047)", "已执行"],
  failed:    ["mdi:alert-circle", "var(--error-color, #db4437)", "失败"],
  rejected:  ["mdi:cancel", "var(--error-color, #db4437)", "已拒绝"],
  answered:  ["mdi:magnify", "var(--info-color, #039be5)", "查询"],
  pending:   ["mdi:help-circle", "var(--warning-color, #ffa600)", "待确认"],
  cancelled: ["mdi:close", "var(--secondary-text-color, #888)", "已取消"],
};

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
  });
}

function fmtTime(ts) {
  try {
    const d = new Date(ts);
    const now = new Date();
    const hm = d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    if (d.toDateString() === now.toDateString()) return "今天 " + hm;
    return d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" }) + " " + hm;
  } catch (e) {
    return "";
  }
}

class JanusAuditPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._init) {
      this._init = true;
      this._load();
    }
  }

  async _load() {
    this._error = false;
    try {
      const res = await this._hass.callWS({ type: "janus/audit/list" });
      this._data = res.decisions || [];
    } catch (e) {
      this._error = true;
      this._data = [];
    }
    this._render();
  }

  _row(r) {
    const s = STATUS[r.status] || STATUS.cancelled;
    const dev = esc(r.device_id || "—");
    const op = r.operation ? " · " + esc(r.operation) : "";
    const utter = r.utterance
      ? '<div style="font-size:14px;margin-top:3px">「' + esc(r.utterance) + "」</div>"
      : "";
    const reason = r.reason
      ? '<div style="font-size:12px;color:var(--secondary-text-color);margin-top:2px">' + esc(r.reason) + "</div>"
      : "";
    return (
      '<div style="display:flex;gap:12px;padding:12px 16px;border-bottom:1px solid var(--divider-color)">' +
      '<ha-icon icon="' + s[0] + '" style="color:' + s[1] + ';--mdc-icon-size:22px;flex-shrink:0"></ha-icon>' +
      '<div style="flex:1;min-width:0">' +
      '<div style="display:flex;align-items:center;gap:8px">' +
      '<span style="font-family:var(--code-font-family,monospace);font-size:13px">' + dev + op + "</span>" +
      '<span style="font-size:11px;padding:1px 8px;border-radius:8px;border:1px solid ' + s[1] + ";color:" + s[1] + '">' + s[2] + "</span>" +
      '<span style="margin-left:auto;font-size:12px;color:var(--secondary-text-color);white-space:nowrap">' + fmtTime(r.ts) + "</span>" +
      "</div>" + utter + reason +
      "</div></div>"
    );
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const n = (this._data || []).length;
    const body = this._error
      ? '<div style="padding:24px 16px;color:var(--error-color)">读取失败</div>'
      : n
      ? this._data.map((r) => this._row(r)).join("")
      : '<div style="padding:24px 16px;color:var(--secondary-text-color)">还没有决策记录</div>';
    this.shadowRoot.innerHTML =
      '<div style="background:var(--card-background-color);color:var(--primary-text-color);' +
      "font-family:var(--paper-font-body1_-_font-family,sans-serif);max-width:900px;margin:16px auto;" +
      'border-radius:12px;overflow:hidden;border:1px solid var(--divider-color)">' +
      '<div style="display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--divider-color)">' +
      '<ha-icon icon="mdi:shield-check" style="--mdc-icon-size:20px;color:var(--primary-color)"></ha-icon>' +
      '<span style="font-size:18px;font-weight:500">Janus 决策</span>' +
      '<span style="font-size:12px;color:var(--secondary-text-color)">最近 ' + n + ' 条 · 本地</span>' +
      '<button id="refresh" style="margin-left:auto;cursor:pointer;background:none;' +
      'border:1px solid var(--divider-color);border-radius:8px;color:var(--primary-text-color);padding:6px 8px">' +
      '<ha-icon icon="mdi:refresh" style="--mdc-icon-size:16px"></ha-icon></button>' +
      "</div>" + body + "</div>";
    const btn = this.shadowRoot.getElementById("refresh");
    if (btn) btn.onclick = () => this._load();
  }
}

customElements.define("janus-audit-panel", JanusAuditPanel);
