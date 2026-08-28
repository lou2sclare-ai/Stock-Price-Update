window.DASHBOARD_CONFIG = {
  dataUrl: "https://raw.githubusercontent.com/lou2sclare-ai/Stock-Price-Update/main/data/latest.json",
  excelUrl: "https://raw.githubusercontent.com/lou2sclare-ai/Stock-Price-Update/main/output/latest.xlsx"
};

(function () {
  const SECTOR_LABELS = {
    SHIPBUILDING: "조선",
    DEFENSE: "방산",
    POWER_EQUIPMENT: "전력기기",
    CONSTRUCTION_EQUIPMENT: "건설장비",
    MACHINERY: "기계"
  };

  const fmt = (n, currency) => {
    if (n === null || n === undefined || n === "") return "-";
    const x = Number(n);
    const digits = Math.abs(x) < 10 ? 3 : (Math.abs(x) < 100 ? 2 : 0);
    const value = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: digits }).format(x);
    return currency ? `${value} ${currency}` : value;
  };

  const pct = n => n === null || n === undefined || n === "" ? "-" : `${Number(n) > 0 ? "+" : ""}${Number(n).toFixed(1)}%`;
  const esc = s => String(s ?? "").replace(/[&<>"']/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));

  async function renderPriorityCoverage() {
    const anchor = document.querySelector(".fresh");
    if (!anchor || !window.DASHBOARD_CONFIG?.dataUrl) return;

    try {
      const res = await fetch(`${window.DASHBOARD_CONFIG.dataUrl}?priority=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) return;
      const payload = await res.json();
      const rows = (payload.rows || [])
        .filter(r => r.priority_coverage && r.priority_coverage_rank)
        .sort((a, b) => Number(a.priority_coverage_rank) - Number(b.priority_coverage_rank));
      if (!rows.length) return;

      const style = document.createElement("style");
      style.textContent = `
        .priority-wrap{margin-top:14px;background:#fff;border:1px solid #dde5ef;border-radius:14px;box-shadow:0 8px 28px rgba(20,32,51,.06);overflow:hidden}
        .priority-head{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:15px 18px;border-bottom:1px solid #edf1f6;background:linear-gradient(90deg,#f8fbff,#fff)}
        .priority-title{font-size:16px;font-weight:900;color:#0b1d3a}.priority-sub{margin-top:3px;font-size:11px;color:#66758a}
        .priority-count{font-size:12px;font-weight:800;color:#2f61d5;background:#eaf2ff;padding:6px 10px;border-radius:999px;white-space:nowrap}
        .priority-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:0}
        .priority-item{padding:13px 14px;border-right:1px solid #edf1f6;border-bottom:1px solid #edf1f6;min-width:0}
        .priority-item:nth-child(5n){border-right:0}.priority-rank{display:inline-flex;align-items:center;justify-content:center;min-width:26px;height:22px;padding:0 6px;border-radius:999px;background:#0b1d3a;color:#fff;font-size:11px;font-weight:900}
        .priority-sector{margin-left:6px;font-size:10px;font-weight:800;color:#2f61d5}.priority-name{margin-top:8px;font-size:13px;font-weight:900;color:#142033;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .priority-price{margin-top:8px;font-size:13px;font-weight:800}.priority-meta{display:flex;justify-content:space-between;gap:8px;margin-top:4px;font-size:11px;color:#66758a}.priority-up{color:#d63031;font-weight:900}.priority-down{color:#2f61d5;font-weight:900}.priority-flat{color:#66758a;font-weight:900}
        @media(max-width:1100px){.priority-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.priority-item:nth-child(5n){border-right:1px solid #edf1f6}.priority-item:nth-child(3n){border-right:0}}
        @media(max-width:650px){.priority-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.priority-head{align-items:flex-start}.priority-item:nth-child(3n){border-right:1px solid #edf1f6}.priority-item:nth-child(2n){border-right:0}}
      `;
      document.head.appendChild(style);

      const section = document.createElement("section");
      section.className = "priority-wrap";
      const cards = rows.map(r => {
        const move = Number(r.price_change_pct);
        const moveClass = Number.isNaN(move) ? "priority-flat" : move > 0 ? "priority-up" : move < 0 ? "priority-down" : "priority-flat";
        const name = r.priority_coverage_display_name || r.company_name || "-";
        return `<div class="priority-item">
          <div><span class="priority-rank">${esc(r.priority_coverage_rank)}</span><span class="priority-sector">${esc(SECTOR_LABELS[r.research_sector] || r.research_sector || "-")}</span></div>
          <div class="priority-name" title="${esc(name)}">${esc(name)}</div>
          <div class="priority-price">${esc(fmt(r.price, r.currency))}</div>
          <div class="priority-meta"><span class="${moveClass}">${esc(pct(r.price_change_pct))}</span><span>${esc(r.price_date || "날짜 미확인")}</span></div>
        </div>`;
      }).join("");

      section.innerHTML = `<div class="priority-head"><div><div class="priority-title">우선 커버리지</div><div class="priority-sub">지정된 15개 핵심 종목을 우선순위 순으로 표시 · 기존 리서치 상태 판정과 별도</div></div><div class="priority-count">${rows.length}개</div></div><div class="priority-grid">${cards}</div>`;
      anchor.insertAdjacentElement("afterend", section);
    } catch (e) {
      console.warn("Priority coverage panel unavailable", e);
    }
  }

  window.addEventListener("DOMContentLoaded", renderPriorityCoverage);
})();
