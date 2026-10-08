/* Renderização compacta dos gráficos do Dashboard */

function formatarDataString(val) {
  if (!val) return "";
  let s = String(val).trim();
  if (/^\d{9,13}$/.test(s)) {
    let ts = Number(s);
    if (s.length === 10) ts *= 1000;
    let d = new Date(ts);
    if (!isNaN(d.getTime())) {
      let dia = String(d.getDate()).padStart(2, '0');
      let mes = String(d.getMonth() + 1).padStart(2, '0');
      return dia + '/' + mes;
    }
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
    let partes = s.split("-");
    return partes[2].slice(0, 2) + '/' + partes[1];
  }
  return s.slice(0, 10);
}

function estadoCanvas(id) {
  const canvas = document.getElementById(id);
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  const w = Math.max(320, Math.floor(rect.width || 600));
  const h = 250; // Altura fixa e compacta para não poluir o painel
  canvas.width = Math.floor(w * dpr);
  canvas.height = Math.floor(h * dpr);
  canvas.style.height = h + "px";
  canvas.style.width = w + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function ret(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

function ajustarLarguraGrafico(id, quantidade) {
  const c = document.getElementById(id);
  if (!c) return;
  const largura = Math.max(550, quantidade * 32 + 60);
  c.style.width = largura + "px";
  c.style.maxWidth = "none";
  const wrap = c.closest(".grafico-wrap");
  if (wrap) {
    wrap.style.width = largura + "px";
    wrap.style.minWidth = largura + "px";
  }
}

function barras(id, labels, valores, fill) {
  const n = (labels || []).length;
  ajustarLarguraGrafico(id, n);
  const s = estadoCanvas(id);
  if (!s) return;
  const { ctx, w, h } = s;
  const vals = (valores || []).map(v => Number(v) || 0);
  const maxVal = Math.max(0, ...vals);

  const m = { l: 35, r: 15, t: 20, b: 90 };
  const aw = w - m.l - m.r;
  const ah = h - m.t - m.b;
  const max = maxVal > 0 ? maxVal : 1;
  const step = aw / Math.max(1, n);
  const bw = Math.max(6, Math.min(18, step * 0.5));

  // Grade de fundo
  ctx.font = "10px -apple-system, BlinkMacSystemFont, Segoe UI";
  ctx.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const y = m.t + ah - (ah * i) / 4;
    ctx.strokeStyle = "#f1f5f9";
    ctx.beginPath();
    ctx.moveTo(m.l, y);
    ctx.lineTo(w - m.r, y);
    ctx.stroke();
    ctx.fillStyle = "#94a3b8";
    ctx.fillText(String(Math.round((max * i) / 4)), m.l - 5, y + 3);
  }

  if (maxVal === 0) {
    ctx.fillStyle = "#64748b";
    ctx.font = "600 11px -apple-system, BlinkMacSystemFont, Segoe UI";
    ctx.textAlign = "center";
    ctx.fillText("Sem dados cadastrados. Clique em 'Pesquisar dados agora'.", w / 2, m.t + ah / 2);
  }

  vals.forEach((v, i) => {
    const cx = m.l + step * i + step / 2;
    const bh = maxVal > 0 ? (v / max) * ah : 0;
    const x = cx - bw / 2;
    const y = m.t + ah - bh;

    if (v > 0) {
      ctx.fillStyle = fill || "#2d78d0";
      ret(ctx, x, y, bw, Math.max(2, bh), 2);
      ctx.fill();

      ctx.fillStyle = "#1e293b";
      ctx.font = "700 8px -apple-system, BlinkMacSystemFont, Segoe UI";
      ctx.textAlign = "center";
      ctx.fillText(Number.isInteger(v) ? v : v.toFixed(1), cx, Math.max(10, y - 3));
    }

    // Nomes rotacionados de forma compacta
    ctx.save();
    ctx.translate(cx, m.t + ah + 8);
    ctx.rotate(-Math.PI / 3);
    ctx.fillStyle = "#475569";
    ctx.font = "9px -apple-system, BlinkMacSystemFont, Segoe UI";
    ctx.textAlign = "right";
    let text = String(labels[i] || "");
    if (text.length > 15) text = text.slice(0, 14) + "…";
    ctx.fillText(text, 0, 0);
    ctx.restore();
  });
}

function linha(id, labels, valores) {
  const canvas = document.getElementById(id);
  if (!canvas) return;

  // Força o container e o canvas a ocuparem 100% da largura do painel
  const wrap = canvas.closest(".grafico-wrap");
  if (wrap) {
    wrap.style.width = "100%";
    wrap.style.minWidth = "0";
    wrap.style.maxWidth = "100%";
  }
  canvas.style.width = "100%";

  const s = estadoCanvas(id);
  if (!s) return;
  const { ctx, w, h } = s;
  const vals = (valores || []).map(v => Number(v) || 0);
  if (!vals.length) {
    ctx.fillStyle = "#64748b";
    ctx.font = "11px Segoe UI";
    ctx.fillText("Sem dados temporais.", 20, h / 2);
    return;
  }

  const m = { l: 35, r: 25, t: 20, b: 50 };
  const aw = w - m.l - m.r;
  const ah = h - m.t - m.b;
  const maxVal = Math.max(1, ...vals);

  // Grade de fundo
  ctx.font = "10px -apple-system, BlinkMacSystemFont, Segoe UI";
  ctx.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const y = m.t + ah - (ah * i) / 4;
    ctx.strokeStyle = "#f1f5f9";
    ctx.beginPath();
    ctx.moveTo(m.l, y);
    ctx.lineTo(w - m.r, y);
    ctx.stroke();
    ctx.fillStyle = "#94a3b8";
    ctx.fillText(String(Math.round((maxVal * i) / 4)), m.l - 5, y + 3);
  }

  // Desenho da Linha
  ctx.strokeStyle = "#2563eb";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = m.l + (vals.length === 1 ? aw / 2 : (aw * i) / (vals.length - 1));
    const y = m.t + ah - (v / maxVal) * ah;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Desenho dos Pontos e Rótulos de Data
  const stepFactor = Math.max(1, Math.ceil(vals.length / 8));
  let ultimoXRotulo = -999;

  vals.forEach((v, i) => {
    const x = m.l + (vals.length === 1 ? aw / 2 : (aw * i) / (vals.length - 1));
    const y = m.t + ah - (v / maxVal) * ah;

    // Marcador
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Rótulo de Data (evita sobreposição)
    const eFim = i === vals.length - 1;
    const deveDesenhar = (i % stepFactor === 0) || eFim;
    if (deveDesenhar && (x - ultimoXRotulo > 32 || eFim)) {
      if (eFim && (x - ultimoXRotulo <= 32)) {
        return;
      }
      ultimoXRotulo = x;
      ctx.save();
      ctx.translate(x, h - 12);
      ctx.rotate(-Math.PI / 6);
      ctx.fillStyle = "#64748b";
      ctx.font = "500 10px -apple-system, BlinkMacSystemFont, Segoe UI";
      ctx.textAlign = "right";
      ctx.fillText(formatarDataString(labels[i]), 0, 0);
      ctx.restore();
    }
  });
}

function renderDashboard() {
  if (window.dadosDashboard) {
    barras("graficoCasos", dadosDashboard.labels, dadosDashboard.casos, "#2d78d0");
    barras("graficoRisco", dadosDashboard.labels, dadosDashboard.risco, "#7c3aed");
    barras("graficoIncidencia", dadosDashboard.labels, dadosDashboard.incidencia, "#16a34a");
    linha("graficoOficial", dadosDashboard.oficialDatas, dadosDashboard.oficialCasos);
  }
  if (window.dadosBairro) {
    barras("graficoBairro", dadosBairro.labels, dadosBairro.casos, "#2d78d0");
  }
}

window.addEventListener("resize", () => {
  clearTimeout(window.__resizeTimer);
  window.__resizeTimer = setTimeout(renderDashboard, 120);
});

document.addEventListener("DOMContentLoaded", () => {
  document
    .querySelectorAll(".flash-fechar")
    .forEach(b => b.addEventListener("click", () => b.parentElement.remove()));
  renderDashboard();
});