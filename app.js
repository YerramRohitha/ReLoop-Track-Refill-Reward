/* ReLoop frontend - plain JavaScript, no build step. Talks to the Flask API at /api */
const $ = (s, r = document) => r.querySelector(s);
const app = $("#app");
const state = { token: localStorage.getItem("rl_token"), me: null, outlets: [], poll: null };

const ICON = { refill: "💧", byo_cup: "☕", byo_bag: "🛍️", no_lid: "🥤", borrow: "♻️" };
const LABEL = { refill: "Refilled own bottle", byo_cup: "Brought own cup", byo_bag: "Brought own bag",
                no_lid: "No lid / straw", borrow: "Borrowed ReLoop cup" };

// ---------- helpers ----------
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDate = s => s ? new Date(s.replace(" ", "T") + "Z").toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const grams = g => g >= 1000 ? (g / 1000).toFixed(2) + " kg" : Math.round(g) + " g";

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 3200);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers.Authorization = "Bearer " + state.token;
  const res = await fetch("/api" + path, { method: opts.method || "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (opts.raw) return res;
  let data = {};
  try { data = await res.json(); } catch (e) { /* not json */ }
  if (res.status === 401 && state.token) { logout(); throw new Error("Please login again"); }
  if (!res.ok) { const e = new Error(data.message || data.error || "Something went wrong"); e.status = res.status; e.data = data; throw e; }
  return data;
}

function logout() {
  localStorage.removeItem("rl_token"); state.token = null; state.me = null; clearInterval(state.poll);
  location.hash = ""; start();
}
$("#logout").onclick = logout;

function bars(items, key = "items") {
  const max = Math.max(1, ...items.map(i => i[key]));
  return `<div class="bars">${items.map(i => `<div title="${esc(i.date)}: ${i[key]}"><i style="height:${Math.round(i[key] / max * 78)}px"></i>${esc(i.date.slice(8))}</div>`).join("")}</div>`;
}
function hbars(rows) {
  const max = Math.max(1, ...rows.map(r => r.items));
  return rows.map(r => `<div style="margin:8px 0"><div class="row between"><span>${esc(r.name)}</span><b>${r.items}</b></div>
    <div class="bar"><i style="width:${Math.round(r.items / max * 100)}%"></i></div></div>`).join("") || `<p class="muted">No data yet.</p>`;
}
function ring(value, max, label) {
  const r = 38, c = 2 * Math.PI * r, p = Math.min(1, value / max);
  return `<svg width="104" height="104" viewBox="0 0 104 104"><circle cx="52" cy="52" r="${r}" fill="none" stroke="#C8E6C9" stroke-width="9"/>
  <circle cx="52" cy="52" r="${r}" fill="none" stroke="#2E7D32" stroke-width="9" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - p)}" transform="rotate(-90 52 52)"/>
  <text x="52" y="52" text-anchor="middle" font-size="19" font-weight="800" fill="#2E7D32">${value}</text><text x="52" y="68" text-anchor="middle" font-size="10" fill="#6B7280">${label}</text></svg>`;
}
const txnRow = t => `<div class="item"><div class="dot">${ICON[t.action] || "♻️"}</div><div class="grow"><div>${LABEL[t.action] || t.action}${t.container ? " · " + esc(t.container) : ""}</div>
  <div class="muted">${esc(t.outlet)} · ${fmtDate(t.created_at)} · <span class="pill ${t.status === "overdue" ? "red" : t.status === "pending" ? "sun" : ""}">${t.status}</span></div></div>
  <div class="right ${t.points_awarded < 0 ? "neg" : ""}">${t.points_awarded ? (t.points_awarded > 0 ? "+" : "") + t.points_awarded : ""}</div></div>`;

// ---------- navigation ----------
const NAVS = {
  student: [["home", "🏠", "Home"], ["scan", "📷", "Scan"], ["impact", "🌱", "Impact"], ["board", "🏆", "Board"], ["rewards", "🎁", "Rewards"]],
  vendor: [["v-approvals", "✅", "Approvals"], ["v-cups", "🧼", "Cups"], ["v-manual", "✍️", "Manual"]],
  admin: [["a-dash", "📊", "Dashboard"], ["a-outlets", "🏪", "Outlets"], ["a-qr", "🔳", "QR codes"], ["a-settings", "⚙️", "Settings"]],
};
function roleKey(role) { return role === "vendor" ? "vendor" : role === "admin" ? "admin" : "student"; }
function drawNav(active) {
  const nav = $("#nav"); nav.hidden = false;
  nav.innerHTML = NAVS[roleKey(state.me.user.role)].map(([id, ic, lb]) => `<a href="#/${id}" class="${id === active ? "on" : ""}"><span>${ic}</span>${lb}</a>`).join("");
}

async function start() {
  clearInterval(state.poll);
  if (!state.token) { $("#topbar").hidden = true; $("#nav").hidden = true; return loginView(); }
  try { state.me = await api("/me"); state.outlets = await api("/outlets"); } catch (e) { return loginView(); }
  $("#topbar").hidden = false;
  $("#who").textContent = `${state.me.user.alias || state.me.user.name} · ${state.me.user.role}`;
  route();
}
window.addEventListener("hashchange", () => state.token && state.me && route());

async function route() {
  clearInterval(state.poll);
  const role = roleKey(state.me.user.role);
  const def = { student: "home", vendor: "v-approvals", admin: "a-dash" }[role];
  let id = (location.hash.replace("#/", "") || def);
  if (!NAVS[role].some(n => n[0] === id)) id = def;
  app.className = role === "admin" ? "wide" : "";
  drawNav(id);
  app.innerHTML = `<p class="muted center">Loading…</p>`;
  try { await VIEWS[id](); } catch (e) { app.innerHTML = `<div class="card warn">${esc(e.message)}</div>`; }
  window.scrollTo(0, 0);
}

// ---------- login ----------
function loginView() {
  app.className = "";
  app.innerHTML = `<div class="login"><h1>♻️ ReLoop</h1><div class="tag">Track. Refill. Reward.</div>
    <div class="card">
      <label>Roll number, email or phone</label>
      <input id="ident" placeholder="e.g. student1" autocomplete="username">
      <div id="newbox" hidden>
        <label>Your name (new here? we will register you)</label><input id="name" placeholder="Full name">
        <label>Department</label><select id="dept"><option>CSE</option><option>ECE</option><option>IT</option><option>EEE</option><option>Civil</option><option>Other</option></select>
        <label>Hostel</label><select id="hostel"><option>Day scholar</option><option>Block A</option><option>Block B</option><option>Block C</option></select>
      </div>
      <button class="block" id="send">Send OTP</button>
      <div id="otpbox" hidden>
        <label style="margin-top:12px;display:block">Enter OTP</label><input id="otp" inputmode="numeric" maxlength="6" placeholder="6-digit OTP">
        <button class="block" id="verify">Login</button>
      </div>
      <div id="demohint"></div>
    </div>
    <div class="demo"><b>Demo accounts</b> (sample data): <code>student1</code> to <code>student12</code>, vendor <code>vendor1</code>, admin <code>admin1</code>.<br>
    In demo mode the OTP is always <code>123456</code>.</div></div>`;
  $("#send").onclick = async () => {
    const body = { identifier: $("#ident").value.trim() };
    if (!$("#newbox").hidden) Object.assign(body, { name: $("#name").value.trim(), department: $("#dept").value, hostel: $("#hostel").value });
    try {
      const r = await api("/auth/otp/request", { method: "POST", body });
      $("#otpbox").hidden = false; $("#otp").focus();
      $("#demohint").innerHTML = r.demo_otp ? `<p class="muted">Demo OTP: <b>${r.demo_otp}</b></p>` : "";
      if (r.demo_otp) $("#otp").value = r.demo_otp;
    } catch (e) {
      if (e.data && e.data.error === "new_user") { $("#newbox").hidden = false; toast(e.message); } else toast(e.message);
    }
  };
  $("#verify").onclick = async () => {
    try {
      const r = await api("/auth/otp/verify", { method: "POST", body: { identifier: $("#ident").value.trim(), otp: $("#otp").value.trim() } });
      state.token = r.token; localStorage.setItem("rl_token", r.token); location.hash = ""; start();
    } catch (e) { toast(e.message); }
  };
}

// ---------- student views ----------
const VIEWS = {};
VIEWS.home = async () => {
  const [me, imp, tx] = await Promise.all([api("/me"), api("/impact/me"), api("/transactions/me?limit=5")]);
  state.me = me;
  const week = imp.last7.reduce((a, d) => a + d.items, 0);
  const cups = me.open_cups.map(c => `<div class="card ${c.status === "overdue" ? "warn" : "sun"}"><div class="row between"><div><b>${esc(c.code)}</b> is with you
    <div class="muted">Due ${fmtDate(c.due_at)} · ${c.status}</div></div><button class="small" data-ret="${esc(c.code)}">Return</button></div></div>`).join("");
  app.innerHTML = `<h1>Hi ${esc(me.user.alias || me.user.name)} 👋</h1>
    <div class="card"><div class="ring">${ring(me.points, Math.max(100, Math.ceil((me.points + 1) / 100) * 100), "points")}</div>
      <p class="center muted">Today: ${me.points_today} / ${me.daily_cap} points${me.pending ? ` · ${me.pending} waiting for vendor` : ""}</p></div>
    ${cups}
    <div class="grid g2"><div class="card stat"><b>${week}</b><span>items avoided this week</span></div><div class="card stat"><b>${me.streak} 🔥</b><span>day streak</span></div></div>
    <a href="#/scan"><button class="block">Scan now</button></a>
    <h2>Recent activity</h2><div class="card list">${tx.map(txnRow).join("") || `<p class="muted">Nothing yet. Scan your first QR!</p>`}</div>`;
  app.querySelectorAll("[data-ret]").forEach(b => b.onclick = () => { sessionStorage.setItem("rl_prefill", JSON.stringify({ mode: "return", code: b.dataset.ret })); location.hash = "#/scan"; });
};

VIEWS.scan = async () => {
  const pre = JSON.parse(sessionStorage.getItem("rl_prefill") || "null"); sessionStorage.removeItem("rl_prefill");
  let mode = pre ? pre.mode : "borrow";
  const modes = [["borrow", "♻️ Borrow cup"], ["return", "↩️ Return cup"], ["refill", "💧 Refill bottle"], ["byo_cup", "☕ Own cup"], ["byo_bag", "🛍️ Own bag"], ["no_lid", "🥤 No lid/straw"]];
  app.innerHTML = `<h1>Scan</h1>
    <div class="chips" id="modes">${modes.map(([m, l]) => `<span class="chip ${m === mode ? "on" : ""}" data-m="${m}">${l}</span>`).join("")}</div>
    <div class="card"><video id="cam" hidden playsinline muted></video>
      <button class="ghost block" id="camBtn">📷 Open camera to scan QR</button>
      <div id="codeBox"><label>Container code (printed under the QR)</label><input id="code" placeholder="e.g. CUP-010" value="${esc(pre ? pre.code : "")}"></div>
      <div id="outBox"><label>Outlet</label><select id="outlet"><option value="">Choose outlet…</option>${state.outlets.map(o => `<option value="${o.outlet_id}">${esc(o.name)}</option>`).join("")}</select></div>
      <button class="block" id="go">Confirm</button></div>
    <div id="result"></div>
    <p class="muted center">Tip: you can also scan the QR on a counter, or type the code if the camera is not available.</p>`;
  const sync = () => {
    const isC = mode === "borrow" || mode === "return";
    $("#codeBox").hidden = !isC; $("#outBox").hidden = mode === "borrow";
    document.querySelectorAll("#modes .chip").forEach(c => c.classList.toggle("on", c.dataset.m === mode));
  };
  document.querySelectorAll("#modes .chip").forEach(c => c.onclick = () => { mode = c.dataset.m; sync(); });
  sync();
  $("#camBtn").onclick = () => startCamera(text => {
    const m = /^RELOOP:OUTLET:(\d+)$/.exec(text), c = /^RELOOP:([A-Z]{3}-\d+)$/i.exec(text);
    if (m) { $("#outlet").value = m[1]; toast("Outlet selected"); }
    else if (c) { $("#code").value = c[1].toUpperCase(); toast("Code " + c[1].toUpperCase() + " scanned"); }
    else toast("Not a ReLoop QR code");
  });
  $("#go").onclick = async () => {
    const btn = $("#go"); btn.disabled = true;
    try {
      let r;
      if (mode !== "borrow" && mode !== "return" && !$("#outlet").value) throw new Error("Please choose the outlet");
      if (mode === "borrow") r = await api("/scan/borrow", { method: "POST", body: { container_code: $("#code").value } });
      else if (mode === "return") r = await api("/scan/return", { method: "POST", body: { container_code: $("#code").value, outlet_id: $("#outlet").value ? +$("#outlet").value : undefined } });
      else r = await api("/scan/refill", { method: "POST", body: { outlet_id: +$("#outlet").value, action: mode } });
      $("#result").innerHTML = resultCard(r, mode);
      state.me = await api("/me");
    } catch (e) { $("#result").innerHTML = `<div class="card warn">${esc(e.message)}</div>`; }
    btn.disabled = false;
  };
};
function resultCard(r, mode) {
  if (r.status === "pending") return `<div class="card sun"><div class="big">⏳</div><p class="center"><b>Request sent</b><br>Waiting for the vendor to tap Approve.</p></div>`;
  if (r.status === "open") return `<div class="card mint"><div class="big">✅</div><p class="center"><b>Cup is yours!</b><br>Return it by ${fmtDate(r.due_at)} to earn points.</p></div>`;
  return `<div class="card mint"><div class="big">${r.points >= 0 ? "+" : ""}${r.points} pts</div>
    <p class="center">You avoided one disposable item${r.late ? " (returned late)" : ""}.<br><b>${r.plastic_g} g</b> plastic · <b>${r.co2_g} g</b> CO₂e saved</p></div>`;
}
async function startCamera(onCode) {
  if (!("BarcodeDetector" in window)) return toast("Camera scanning is not supported in this browser. Please type the code.");
  const video = $("#cam");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    video.srcObject = stream; video.hidden = false; await video.play();
    const det = new BarcodeDetector({ formats: ["qr_code"] });
    const tick = async () => {
      if (!video.srcObject) return;
      try { const codes = await det.detect(video); if (codes.length) { onCode(codes[0].rawValue); stream.getTracks().forEach(t => t.stop()); video.srcObject = null; video.hidden = true; return; } } catch (e) { /* ignore */ }
      setTimeout(tick, 300);
    };
    tick();
  } catch (e) { toast("Could not open the camera. Please type the code."); }
}

VIEWS.impact = async () => {
  const [imp, tx] = await Promise.all([api("/impact/me"), api("/transactions/me?limit=15")]);
  app.innerHTML = `<h1>My Plastic Ledger</h1>
    <div class="grid g3"><div class="card stat"><b>${imp.items}</b><span>items avoided</span></div><div class="card stat"><b>${grams(imp.plastic_g)}</b><span>plastic kept out</span></div><div class="card stat"><b>${grams(imp.co2_g)}</b><span>CO₂e saved</span></div></div>
    <div class="card mint center">That is about <b>${imp.bottles_equivalent}</b> plastic water bottles 🌍</div>
    <div class="card"><b>Last 7 days</b>${bars(imp.last7)}</div>
    <div class="card"><b>What you did</b>${imp.by_action.map(a => `<div class="row between" style="margin:6px 0"><span>${ICON[a.action]} ${LABEL[a.action]}</span><b>${a.n}</b></div>`).join("") || `<p class="muted">No actions yet.</p>`}</div>
    <h2>History</h2><div class="card list">${tx.map(txnRow).join("")}</div>`;
};

VIEWS.board = async () => {
  let kind = "department";
  const draw = async () => {
    const rows = await api("/leaderboard?type=" + kind);
    $("#boardList").innerHTML = rows.map(r => `<div class="item"><div class="dot">${r.rank <= 3 ? ["🥇", "🥈", "🥉"][r.rank - 1] : r.rank}</div><div class="grow"><b>${esc(r.name)}${r.me ? " (you)" : ""}</b>
      <div class="bar"><i style="width:${Math.round(r.items / rows[0].items * 100)}%"></i></div></div><div class="right">${r.items}</div></div>`).join("") || `<p class="muted">No data yet.</p>`;
    document.querySelectorAll("#tabs .chip").forEach(c => c.classList.toggle("on", c.dataset.k === kind));
  };
  app.innerHTML = `<h1>Leaderboard</h1><div class="chips" id="tabs"><span class="chip" data-k="department">Departments</span><span class="chip" data-k="hostel">Hostels</span><span class="chip" data-k="user">Students</span></div>
    <div class="card list" id="boardList"></div><p class="muted center">Counted by items avoided. Students appear with their alias.</p>`;
  document.querySelectorAll("#tabs .chip").forEach(c => c.onclick = () => { kind = c.dataset.k; draw(); });
  draw();
};

VIEWS.rewards = async () => {
  const [me, rw, my] = await Promise.all([api("/me"), api("/rewards"), api("/redemptions/me")]);
  app.innerHTML = `<h1>Rewards</h1><div class="card mint center"><div class="big">${me.points}</div><span class="muted">your green points</span></div>
    ${rw.map(r => `<div class="card sun"><div class="row between"><div><b>${esc(r.title)}</b><div class="muted">${esc(r.outlet || "Anywhere on campus")} · ${r.stock} left</div></div>
      <button class="small" data-r="${r.reward_id}" ${me.points < r.points_cost || r.stock <= 0 ? "disabled" : ""}>${r.points_cost} pts</button></div></div>`).join("")}
    <h2>My vouchers</h2><div class="card list">${my.map(m => `<div class="item"><div class="dot">🎟️</div><div class="grow"><b>${esc(m.title)}</b><div class="muted">${fmtDate(m.created_at)}</div></div><div class="right">${esc(m.voucher_code)}</div></div>`).join("") || `<p class="muted">No vouchers yet.</p>`}</div>`;
  app.querySelectorAll("[data-r]").forEach(b => b.onclick = async () => {
    try { const r = await api(`/rewards/${b.dataset.r}/redeem`, { method: "POST" }); toast("Voucher " + r.voucher_code); VIEWS.rewards(); } catch (e) { toast(e.message); }
  });
};

// ---------- vendor views ----------
VIEWS["v-approvals"] = async () => {
  const draw = async () => {
    const [st, pend] = await Promise.all([api("/vendor/stats"), api("/vendor/pending")]);
    if (!$("#vbox")) return;
    $("#vbox").innerHTML = `<div class="grid g3"><div class="card stat"><b>${st.pending ?? 0}</b><span>waiting</span></div><div class="card stat"><b>${st.saved_today ?? 0}</b><span>saved today</span></div><div class="card stat"><b>${st.overdue ?? 0}</b><span>cups overdue</span></div></div>
      <h2>Pending requests</h2>${pend.map(p => `<div class="card"><div class="row between"><div><b>${esc(p.user_name)}</b><div class="muted">${LABEL[p.action]}${p.container ? " · " + esc(p.container) : ""} · ${esc(p.outlet)}</div></div>
        <div class="row"><button class="small" data-a="${p.txn_id}">Approve</button><button class="small danger" data-x="${p.txn_id}">Reject</button></div></div></div>`).join("") || `<div class="card muted center">No pending requests 🎉</div>`}`;
    $("#vbox").querySelectorAll("[data-a],[data-x]").forEach(b => b.onclick = async () => {
      try { await api("/vendor/approvals/" + (b.dataset.a || b.dataset.x), { method: "POST", body: { decision: b.dataset.a ? "approve" : "reject" } }); draw(); } catch (e) { toast(e.message); }
    });
  };
  app.innerHTML = `<h1>Approvals</h1><div id="vbox"></div><p class="muted center">This list refreshes every 5 seconds.</p>`;
  await draw(); state.poll = setInterval(() => draw().catch(() => {}), 5000);
};
VIEWS["v-cups"] = async () => {
  const [st, cs] = await Promise.all([api("/vendor/stats"), api("/vendor/containers")]);
  const c = st.containers || {};
  app.innerHTML = `<h1>Cups and bottles</h1><div class="grid g3"><div class="card stat"><b>${c.ready || 0}</b><span>ready</span></div><div class="card stat"><b>${c.in_use || 0}</b><span>with students</span></div><div class="card stat"><b>${c.dirty || 0}</b><span>to wash</span></div></div>
    <button class="block" id="wash" ${c.dirty ? "" : "disabled"}>🧼 Mark all dirty as washed</button>
    <h2>All containers</h2><div class="card list">${cs.map(x => `<div class="item"><div class="dot">${x.type === "cup" ? "☕" : "💧"}</div><div class="grow"><b>${esc(x.code)}</b><div class="muted">${esc(x.outlet)}</div></div><span class="pill ${x.wash_status === "dirty" ? "red" : x.wash_status === "in_use" ? "sun" : ""}">${x.wash_status}</span></div>`).join("")}</div>`;
  $("#wash").onclick = async () => { const r = await api("/vendor/containers/wash", { method: "POST", body: { all: true } }); toast(r.washed + " containers marked ready"); VIEWS["v-cups"](); };
};
VIEWS["v-manual"] = async () => {
  app.innerHTML = `<h1>Log for a student</h1><div class="card"><p class="muted">For students without a smartphone: enter the roll number and choose what they did.</p>
    <label>Roll number</label><input id="mi" placeholder="e.g. student12">
    <label>Action</label><select id="ma">${Object.keys(LABEL).filter(k => k !== "borrow").map(k => `<option value="${k}">${LABEL[k]}</option>`).join("")}</select>
    <button class="block" id="mgo">Save</button></div><div id="mres"></div>`;
  $("#mgo").onclick = async () => {
    try { const r = await api("/vendor/manual", { method: "POST", body: { identifier: $("#mi").value.trim(), action: $("#ma").value } }); $("#mres").innerHTML = `<div class="card mint center"><b>Saved ✓</b><br>${r.plastic_g} g plastic · ${r.points} points</div>`; }
    catch (e) { $("#mres").innerHTML = `<div class="card warn">${esc(e.message)}</div>`; }
  };
};

// ---------- admin views ----------
VIEWS["a-dash"] = async () => {
  const [d, fl] = await Promise.all([api("/admin/dashboard"), api("/admin/flags")]);
  app.innerHTML = `<h1>Campus Impact</h1>
    <div class="grid g4"><div class="card stat"><b>${d.items}</b><span>items avoided</span></div><div class="card stat"><b>${grams(d.plastic_g)}</b><span>plastic kept out</span></div><div class="card stat"><b>${grams(d.co2_g)}</b><span>CO₂e avoided</span></div><div class="card stat"><b>${d.active_users_7d}/${d.registered_users}</b><span>active users (7 days)</span></div></div>
    <div class="grid g2"><div class="card stat"><b>${d.return_rate ?? "-"}${d.return_rate != null ? "%" : ""}</b><span>cups returned</span></div><div class="card stat"><b>${d.overdue}</b><span>cups overdue now</span></div></div>
    <div class="card"><b>Items avoided per day (last 14 days)</b>${bars(d.per_day)}</div>
    <div class="cols2"><div class="card"><b>By outlet</b>${hbars(d.by_outlet)}</div><div class="card"><b>By department</b>${hbars(d.by_department)}</div></div>
    <div class="card ${fl.length ? "warn" : ""}"><b>Unusual activity</b>${fl.map(f => `<p>${esc(f.name)} (${esc(f.identifier)}) made ${f.scans_last_hour} scans in the last hour</p>`).join("") || `<p class="muted">Nothing unusual right now.</p>`}</div>`;
};
VIEWS["a-outlets"] = async () => {
  const os = await api("/admin/outlets");
  app.innerHTML = `<h1>Outlets</h1><div class="card"><table><tr><th>Name</th><th>Type</th><th>Vendor</th><th>Containers</th></tr>${os.map(o => `<tr><td>${esc(o.name)}</td><td>${esc(o.type)}</td><td>${esc(o.vendor || "-")}</td><td>${o.containers}</td></tr>`).join("")}</table></div>
    <div class="cols2"><div class="card"><b>Add outlet</b><label>Name</label><input id="on"><label>Type</label><input id="ot" placeholder="canteen / tea stall / cafe / refill point"><label>Vendor login (optional)</label><input id="ov" placeholder="vendor1"><button class="block" id="oadd">Add outlet</button></div>
    <div class="card"><b>Add cups or bottles</b><label>Outlet</label><select id="co">${os.map(o => `<option value="${o.outlet_id}">${esc(o.name)}</option>`).join("")}</select><label>Type</label><select id="ct"><option value="cup">Cup</option><option value="bottle">Bottle</option></select><label>How many (1-200)</label><input id="cc" type="number" value="10"><button class="block" id="cadd">Create with QR codes</button></div></div>`;
  $("#oadd").onclick = async () => { try { await api("/admin/outlets", { method: "POST", body: { name: $("#on").value, type: $("#ot").value, vendor_identifier: $("#ov").value.trim() || undefined } }); toast("Outlet added"); VIEWS["a-outlets"](); } catch (e) { toast(e.message); } };
  $("#cadd").onclick = async () => { try { const r = await api("/admin/containers", { method: "POST", body: { outlet_id: +$("#co").value, type: $("#ct").value, count: +$("#cc").value } }); toast(r.created.length + " containers created"); VIEWS["a-outlets"](); } catch (e) { toast(e.message); } };
};
VIEWS["a-qr"] = async () => {
  const q = await api("/admin/qr-list");
  const all = [...q.outlets.map(o => ({ ...o, sub: "Outlet QR" })), ...q.containers];
  app.innerHTML = `<div class="row between noprint"><h1>QR codes</h1><button class="small" onclick="window.print()">🖨️ Print</button></div>
    <p class="muted noprint">Print this page and stick the QR on each cup, bottle and counter.</p><div class="qrgrid">${all.map((x, i) => `<div class="qrbox"><div class="q" id="q${i}"><small>${esc(x.value)}</small></div><b>${esc(x.label)}</b><div class="muted">${esc(x.sub || "")}</div></div>`).join("")}</div>`;
  try {
    await new Promise((ok, no) => { if (window.QRCode) return ok(); const s = document.createElement("script"); s.src = "https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"; s.onload = ok; s.onerror = no; document.head.appendChild(s); });
    all.forEach((x, i) => { const el = $("#q" + i); el.innerHTML = ""; new QRCode(el, { text: x.value, width: 96, height: 96 }); });
  } catch (e) { toast("QR library could not load (needs internet). Codes are shown as text."); }
};
VIEWS["a-settings"] = async () => {
  const [items, outs] = await Promise.all([api("/admin/item-types"), api("/admin/outlets")]);
  app.innerHTML = `<h1>Settings</h1><div class="card"><b>Item catalogue</b><p class="muted">Plastic weight and emission values for each disposable item. These are starting estimates: replace them with verified values.</p>
    <table><tr><th>Item</th><th>Plastic (g)</th><th>CO₂e (kg)</th><th>Reuse CO₂e (kg)</th><th></th></tr>${items.map(i => `<tr><td>${esc(i.name)}</td><td><input id="p${i.item_type_id}" value="${i.plastic_grams}"></td><td><input id="e${i.item_type_id}" value="${i.emission_kg}"></td><td><input id="r${i.item_type_id}" value="${i.reuse_footprint_kg}"></td><td><button class="small" data-i="${i.item_type_id}">Save</button></td></tr>`).join("")}</table></div>
    <div class="cols2"><div class="card"><b>Add reward</b><label>Title</label><input id="rt"><label>Points needed</label><input id="rc" type="number" value="100"><label>Stock</label><input id="rs" type="number" value="10"><button class="block" id="radd">Add reward</button></div>
    <div class="card"><b>Monthly report</b><p class="muted">Download all counted actions as a CSV file for the green audit.</p><button class="block" id="csv">⬇️ Download report (CSV)</button></div></div>`;
  app.querySelectorAll("[data-i]").forEach(b => b.onclick = async () => {
    const id = b.dataset.i;
    try { await api("/admin/item-types/" + id, { method: "PUT", body: { plastic_grams: $("#p" + id).value, emission_kg: $("#e" + id).value, reuse_footprint_kg: $("#r" + id).value } }); toast("Saved"); } catch (e) { toast(e.message); }
  });
  $("#radd").onclick = async () => { try { await api("/admin/rewards", { method: "POST", body: { title: $("#rt").value, points_cost: +$("#rc").value, stock: +$("#rs").value } }); toast("Reward added"); } catch (e) { toast(e.message); } };
  $("#csv").onclick = async () => {
    const res = await api("/admin/report.csv", { raw: true }); const blob = await res.blob();
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "reloop_report.csv"; a.click();
  };
};

start();
