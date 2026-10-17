/* CURRENT code panel. window.CurrentCode.mount(hostEl,{getSession,send}); CurrentCode.onMessage(msg) for ws 'sketch'. */
(function () {
  var CHIPS = ['blink twice as fast', 'use pin 8', 'fade the LED', 'button toggles it'];
  var inst = null;
  function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function hl(line) {
    var i = line.indexOf('//'), c = '';
    if (i >= 0) { c = '<span class="cc-cm">' + esc(line.slice(i)) + '</span>'; line = line.slice(0, i); }
    return esc(line).replace(/\b(void|int|const|bool|if|else|for|while|return|true|false|HIGH|LOW|OUTPUT|INPUT_PULLUP|INPUT)\b/g, '<span class="cc-kw">$1</span>')
      .replace(/\b(\d+)\b/g, '<span class="cc-num">$1</span>') + c;
  }
  function el(tag, cls, txt) { var e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }
  function mount(host, opts) {
    opts = opts || {};
    var st = { code: '', board: 'nano', notes: [], canUndo: false, busy: false };
    var root = el('div', 'cc-root'), head = el('div', 'cc-head'), title = el('div', 'cc-title', 'Arduino sketch');
    var badge = el('span', 'cc-badge', 'nano');
    var copy = el('button', 'cc-btn', 'Copy'), dl = el('button', 'cc-btn', 'Download .ino'), undo = el('button', 'cc-btn', 'Undo');
    head.append(title, badge, copy, dl, undo);
    var pre = el('pre', 'cc-code'), ask = el('div', 'cc-ask'), input = el('input', 'cc-in'), gen = el('button', 'cc-btn cc-primary', 'Regenerate');
    input.placeholder = 'Tell the coach how to change the code...';
    ask.append(input, gen);
    var chips = el('div', 'cc-chips');
    CHIPS.forEach(function (t) { var c = el('span', 'cc-chip', t); c.onclick = function () { input.value = t; request(); }; chips.append(c); });
    var status = el('div', 'cc-status', 'Ready. Ask for a change or press Regenerate.');
    root.append(head, pre, ask, chips, status); host.innerHTML = ''; host.append(root);
    function render() {
      pre.innerHTML = '';
      (st.code || '// no sketch yet').replace(/\n$/, '').split('\n').forEach(function (l, i) {
        var r = el('div', 'cc-ln'); r.append(el('span', 'cc-n', String(i + 1)));
        var t = el('span', 'cc-t'); t.innerHTML = hl(l); r.append(t); pre.append(r);
      });
      badge.textContent = st.board; undo.disabled = !st.canUndo || st.busy; gen.disabled = st.busy;
      status.textContent = st.busy ? 'Writing code for your bench...' : (st.notes.join(' ') || 'Ready.');
      status.className = 'cc-status' + (/resistor|template|error/i.test(st.notes.join(' ')) && !st.busy ? ' cc-warn' : '');
    }
    function request(undoFlag) {
      st.busy = true; render();
      var m = { type: 'sketch_request', instruction: input.value.trim() };
      if (undoFlag) m.undo = true;
      opts.send && opts.send(m);
      setTimeout(function () { if (st.busy) { st.busy = false; st.notes = ['No answer yet. Is the session connected?']; render(); } }, 25000);
    }
    copy.onclick = function () { (navigator.clipboard ? navigator.clipboard.writeText(st.code) : Promise.reject()).then(function () { status.textContent = 'Copied.'; }, function () { status.textContent = 'Copy blocked by browser.'; }); };
    dl.onclick = function () {
      var s = opts.getSession ? opts.getSession() : ''; var code = typeof s === 'object' && s ? s.code : s;
      if (code) { location.href = '/api/sketch/download?code=' + encodeURIComponent(code) + '&board=' + st.board; return; }
      var a = el('a'); a.href = URL.createObjectURL(new Blob([st.code], { type: 'text/plain' })); a.download = 'current_sketch.ino'; a.click();
    };
    gen.onclick = function () { request(); }; undo.onclick = function () { request(true); };
    input.onkeydown = function (e) { if (e.key === 'Enter') request(); };
    inst = { st: st, render: render };
    // initial fetch of existing sketch
    var s0 = opts.getSession && opts.getSession(); var c0 = typeof s0 === 'object' && s0 ? s0.code : s0;
    if (c0) fetch('/api/sketch?code=' + encodeURIComponent(c0)).then(function (r) { return r.json(); })
      .then(function (d) { if (d.code) onMessage(d); }).catch(function () {});
    render();
    return { render: render };
  }
  function onMessage(m) {
    if (!inst || !m) return;
    if (m.type && m.type !== 'sketch') return;
    var s = inst.st; s.code = m.code || s.code; s.board = m.board || s.board; s.notes = m.notes || [];
    s.canUndo = m.can_undo != null ? !!m.can_undo : true; s.busy = false; inst.render();
  }
  window.CurrentCode = { mount: mount, onMessage: onMessage };
})();
