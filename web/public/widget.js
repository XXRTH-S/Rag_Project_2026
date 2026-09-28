/**
 * RAG Workshop chat widget
 *
 * ฝังด้วยแท็กเดียว:
 *   <script src="http://localhost/widget.js" defer></script>
 *
 * กำหนดค่าเพิ่มได้ผ่าน data attribute:
 *   <script src="/widget.js" data-api="https://rag.example.com" defer></script>
 *
 * เขียนด้วย vanilla JS ไม่มี dependency เพราะต้องฝังในเว็บอะไรก็ได้
 * โดยไม่ไปชนกับ framework ที่เว็บนั้นใช้อยู่ และสไตล์ทั้งหมดอยู่ใน shadow DOM
 * เพื่อไม่ให้ CSS ของเว็บเจ้าบ้านรั่วเข้ามาหรือรั่วออกไป
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var API = (script && script.dataset.api) || "";

  var state = { open: false, busy: false, sessionId: null, config: null };

  // ui

  var host = document.createElement("div");
  host.id = "rag-widget";
  var root = host.attachShadow({ mode: "open" });
  document.body.appendChild(host);

  var style = document.createElement("style");
  style.textContent = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:ui-sans-serif,system-ui,'Segoe UI','Noto Sans Thai',sans-serif}",
    ".fab{position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;",
    "border:none;cursor:pointer;color:#fff;font-size:24px;box-shadow:0 4px 16px rgba(0,0,0,.25);z-index:2147483000}",
    ".panel{position:fixed;right:20px;bottom:88px;width:380px;max-width:calc(100vw - 40px);",
    "height:540px;max-height:calc(100vh - 120px);background:#fff;color:#18181b;border-radius:14px;",
    "box-shadow:0 12px 40px rgba(0,0,0,.28);display:none;flex-direction:column;overflow:hidden;z-index:2147483000}",
    ".panel.open{display:flex}",
    ".head{padding:14px 16px;color:#fff;font-weight:650}",
    ".body{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px;background:#fafafa}",
    ".msg{padding:9px 12px;border-radius:12px;max-width:85%;white-space:pre-wrap;font-size:14px;line-height:1.55}",
    ".msg.user{align-self:flex-end;color:#fff}",
    ".msg.bot{align-self:flex-start;background:#fff;border:1px solid #e4e4e7}",
    ".working{color:#71717a;font-size:12.5px}",
    ".sugg{display:flex;flex-wrap:wrap;gap:6px;padding:0 14px 10px;background:#fafafa}",
    ".sugg button{border:1px solid #e4e4e7;background:#fff;border-radius:999px;padding:5px 11px;",
    "font-size:12.5px;cursor:pointer;color:#3f3f46}",
    ".foot{display:flex;gap:8px;padding:12px;border-top:1px solid #e4e4e7;background:#fff}",
    ".foot input{flex:1;padding:9px 11px;border:1px solid #e4e4e7;border-radius:9px;font-size:14px;color:#18181b}",
    ".foot button{border:none;color:#fff;border-radius:9px;padding:9px 15px;cursor:pointer;font-size:14px}",
    ".foot button:disabled{opacity:.5;cursor:not-allowed}",
    "@media(prefers-color-scheme:dark){",
    ".panel{background:#131316;color:#fafafa}.body{background:#0d0d10}",
    ".msg.bot{background:#1c1c20;border-color:#27272a}",
    ".foot{background:#131316;border-color:#27272a}",
    ".foot input{background:#1c1c20;border-color:#27272a;color:#fafafa}",
    ".sugg{background:#0d0d10}.sugg button{background:#1c1c20;border-color:#27272a;color:#d4d4d8}}",
  ].join("");
  root.appendChild(style);

  var fab = el("button", "fab", "💬");
  var panel = el("div", "panel");
  var head = el("div", "head");
  var body = el("div", "body");
  var sugg = el("div", "sugg");
  var foot = el("div", "foot");
  var input = document.createElement("input");
  var send = el("button", "", "ส่ง");

  foot.appendChild(input);
  foot.appendChild(send);
  panel.appendChild(head);
  panel.appendChild(body);
  panel.appendChild(sugg);
  panel.appendChild(foot);
  root.appendChild(fab);
  root.appendChild(panel);

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  // ซ่อนเฉพาะเลขอ้างอิงที่มีแหล่งที่มาจริง และส่วนท้ายที่ยัง stream ไม่ครบ
  // เก็บเลขในวงเล็บที่เป็นเนื้อหาเอกสารไว้
  function stripCitationMarkers(value, citationCount) {
    if (!citationCount) return value;
    return value
      .replace(/\s*\[(\d+)\]/g, function (match, digits) {
        var rank = Number(digits);
        return rank >= 1 && rank <= citationCount ? "" : match;
      })
      .replace(/\s*\[\d*$/, "")
      .replace(/\s+$/, "");
  }

  function bubble(kind, text) {
    var node = el("div", "msg " + kind, text);
    if (kind === "user") node.style.background = accent();
    body.appendChild(node);
    body.scrollTop = body.scrollHeight;
    return node;
  }

  function accent() {
    return (state.config && state.config.accent_color) || "#4f46e5";
  }

  // config

  fetch(API + "/api/widget/config", { credentials: "include" })
    .then(function (r) {
      return r.json();
    })
    .then(function (config) {
      state.config = config;
      head.textContent = config.title;
      head.style.background = config.accent_color;
      fab.style.background = config.accent_color;
      send.style.background = config.accent_color;
      input.placeholder = config.placeholder;
      bubble("bot", config.greeting);

      (config.suggestions || []).forEach(function (question) {
        var chip = el("button", "", question);
        chip.onclick = function () {
          input.value = question;
          ask();
        };
        sugg.appendChild(chip);
      });
    })
    .catch(function () {
      head.textContent = "ผู้ช่วยตอบคำถาม";
      head.style.background = accent();
      fab.style.background = accent();
      send.style.background = accent();
      bubble("bot", "ต่อระบบไม่ได้ ลองใหม่อีกครั้งภายหลัง");
    });

  // chat

  fab.onclick = function () {
    state.open = !state.open;
    panel.classList.toggle("open", state.open);
    if (state.open) input.focus();
  };

  send.onclick = ask;
  input.onkeydown = function (event) {
    if (event.key === "Enter") ask();
  };

  function ask() {
    var question = input.value.trim();
    if (!question || state.busy) return;

    input.value = "";
    state.busy = true;
    send.disabled = true;
    bubble("user", question);

    var answer = bubble("bot", "");
    var text = "";
    var citationCount = 0;

    // แสดงเวลารอระหว่างค้นเอกสารและสร้างคำตอบ
    var started = Date.now();
    var progress = el("div", "working", "กำลังค้นเอกสาร…");
    answer.appendChild(progress);
    var label = "กำลังค้นเอกสาร";
    var ticker = setInterval(function () {
      var seconds = Math.round((Date.now() - started) / 1000);
      progress.textContent =
        label + "… " + seconds + " วิ" +
        (seconds >= 20 ? " (ครั้งแรกหลังพักนานจะช้ากว่าปกติ)" : "");
    }, 1000);

    function stopProgress() {
      clearInterval(ticker);
      if (progress.parentNode) progress.parentNode.removeChild(progress);
    }

    fetch(API + "/api/chat", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, session_id: state.sessionId }),
    })
      .then(function (response) {
        if (response.status === 401) throw new Error("ต้องเข้าสู่ระบบก่อนใช้งาน");
        if (response.status === 429) throw new Error("ถามถี่เกินไป รอสักครู่แล้วลองใหม่");
        if (!response.ok) throw new Error("ระบบขัดข้อง (HTTP " + response.status + ")");
        return readStream(response, function (name, data) {
          if (name === "session") {
            state.sessionId = data.session_id;
          } else if (name === "token") {
            if (text === "") stopProgress();
            text += data.text;
            answer.textContent = stripCitationMarkers(text, citationCount);
            body.scrollTop = body.scrollHeight;
          } else if (name === "citations" && data.citations.length) {
            // เก็บแค่จำนวน เพื่อรู้ว่าเลขในวงเล็บตัวไหนเป็นการอ้างอิงจริง
            citationCount = data.citations.length;
            // แสดงสถานะค้นพบข้อมูลโดยไม่แสดงรายการอ้างอิงใน widget
            label = "ค้นเจอเอกสารที่เกี่ยวข้องแล้ว · กำลังเรียบเรียงคำตอบ";
          } else if (name === "error") {
            stopProgress();
            answer.textContent = "เกิดข้อผิดพลาด: " + data.detail;
          }
        });
      })
      .catch(function (err) {
        stopProgress();
        answer.textContent = err.message || "ส่งคำถามไม่สำเร็จ";
      })
      .finally(function () {
        stopProgress();
        state.busy = false;
        send.disabled = false;
      });
  }

  /** อ่าน SSE จาก POST — EventSource รองรับแค่ GET จึงใช้ไม่ได้ */
  function readStream(response, onEvent) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";

    function pump() {
      return reader.read().then(function (chunk) {
        if (chunk.done) return;
        buffer += decoder.decode(chunk.value, { stream: true });

        var split;
        while ((split = buffer.indexOf("\n\n")) !== -1) {
          var block = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);

          var name = "message";
          var raw = "";
          block.split("\n").forEach(function (line) {
            if (line.indexOf("event: ") === 0) name = line.slice(7);
            else if (line.indexOf("data: ") === 0) raw = line.slice(6);
          });
          if (raw) {
            try {
              onEvent(name, JSON.parse(raw));
            } catch (e) {
              /* ข้าม event ที่ parse ไม่ได้ ไม่ให้ล้มทั้งสตรีม */
            }
          }
        }
        return pump();
      });
    }

    return pump();
  }
})();
