// 3D drawing of the graph view (WebGL via the vendored 3d-force-graph / Three.js). It only draws what
// graph_logic.js already selected: it fetches nothing and parses no server text as HTML. The library's
// own hover tooltip would insert HTML, so it is switched off; labels are our own absolutely positioned
// elements filled with textContent and moved to the projected node position on every frame.
// Candidates are amber, confirmed items green, conversations blue; relations that are not ABOUT are thicker.
(function () {
  "use strict";

  function available() {
    if (typeof window.ForceGraph3D !== "function") return false;
    try {
      const probe = document.createElement("canvas");
      return !!(probe.getContext("webgl2") || probe.getContext("webgl"));
    } catch (error) {
      return false;
    }
  }

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  function colors() {
    return { fg: css("--fg"), bg: css("--card"), line: css("--line"), muted: css("--muted"), cand: css("--cand"), ok: css("--ok"), accent: css("--accent") };
  }

  // Nodes and links are copied: the library replaces link ends by node objects and adds coordinates.
  function data(graph) {
    return {
      nodes: graph.nodes.map((n) => ({ id: n.id, label: n.label, type: n.type, kind: n.kind, status: n.status, strength: n.strength || 0 })),
      links: graph.edges.map((e) => ({ id: e.id, source: e.source, target: e.target, type: e.type, relation: e.relation, status: e.status })),
    };
  }

  // handle: {box, scene, labels, observers, frame}; render() returns it, destroy() takes it down.
  function render(box, graph, hooks) {
    const c = colors();
    const nodeColor = (n) => (n.type === "conversation" ? c.accent : n.status === "confirmed" ? c.ok : c.cand);
    const linkColor = (l) => (l.type === "origin" ? c.muted : l.status === "confirmed" ? c.ok : c.cand);
    const layer = document.createElement("div");
    layer.className = "g3d-labels";
    layer.setAttribute("aria-hidden", "true");
    const scene = window.ForceGraph3D()(box)
      .backgroundColor(c.bg)
      .showNavInfo(false)
      .width(box.clientWidth).height(box.clientHeight)
      .nodeLabel(() => "")
      .linkLabel(() => "")
      .nodeColor(nodeColor)
      .nodeVal((n) => (n.kind === "Theme" ? 8 : n.type === "conversation" ? 4 : 2 + Math.min(n.strength, 4)))
      .nodeOpacity(0.95)
      .nodeResolution(12)
      .linkColor(linkColor)
      .linkOpacity(0.7)
      .linkWidth((l) => (l.type === "origin" ? 0 : l.relation === "ABOUT" ? 0.4 : 1.4))
      .linkDirectionalArrowLength((l) => (l.type === "origin" ? 0 : 4))
      .linkDirectionalArrowRelPos(1)
      .linkHoverPrecision(6)
      .cooldownTicks(160)
      .onNodeClick((n) => {
        focus(handle, n.id);
        hooks.onNode(n.id);
      })
      .onLinkClick((l) => hooks.onLink(l.id))
      .onBackgroundClick(() => hooks.onBackground())
      .graphData(data(graph));
    box.append(layer);

    const labels = new Map();
    for (const n of graph.nodes) {
      const tag = document.createElement("span");
      tag.className = "g3d-label" + (n.kind === "Theme" ? " theme" : "");
      tag.textContent = n.label;
      layer.append(tag);
      labels.set(n.id, tag);
    }
    const handle = { box, scene, layer, labels, observer: null, resize: null, frame: 0, running: true };

    function place() {
      handle.frame = 0;
      if (!handle.running) return;
      const cam = scene.camera().position;
      const width = box.clientWidth, height = box.clientHeight;
      for (const n of scene.graphData().nodes) {
        const tag = labels.get(n.id);
        if (!tag) continue;
        if (n.x === undefined) { tag.hidden = true; continue; }
        const p = scene.graph2ScreenCoords(n.x, n.y, n.z);
        const dist = Math.hypot(n.x - cam.x, n.y - cam.y, n.z - cam.z);
        const off = p.x < -40 || p.y < -20 || p.x > width + 40 || p.y > height + 20 || !isFinite(dist);
        tag.hidden = off;
        if (off) continue;
        tag.style.transform = "translate(" + Math.round(p.x) + "px," + Math.round(p.y + 10) + "px) translateX(-50%)";
        tag.style.opacity = String(Math.max(0.25, Math.min(1, 260 / dist)));
      }
      handle.frame = requestAnimationFrame(place);
    }
    handle.start = () => { handle.running = true; scene.resumeAnimation(); if (!handle.frame) handle.frame = requestAnimationFrame(place); };
    handle.stop = () => { handle.running = false; scene.pauseAnimation(); if (handle.frame) cancelAnimationFrame(handle.frame); handle.frame = 0; };

    // The canvas follows its container; drawing pauses while the view is hidden or scrolled away.
    if (typeof ResizeObserver === "function") {
      handle.resize = new ResizeObserver(() => { if (box.clientWidth > 0) scene.width(box.clientWidth).height(box.clientHeight); });
      handle.resize.observe(box);
    }
    if (typeof IntersectionObserver === "function") {
      handle.observer = new IntersectionObserver((entries) => { if (entries[entries.length - 1].isIntersecting) handle.start(); else handle.stop(); });
      handle.observer.observe(box);
    }
    handle.start();
    return handle;
  }

  function focus(handle, id) {
    const n = handle.scene.graphData().nodes.find((x) => x.id === id);
    if (!n || n.x === undefined) return;
    const ratio = 1 + 90 / (Math.hypot(n.x, n.y, n.z) || 1);
    handle.scene.cameraPosition({ x: n.x * ratio, y: n.y * ratio, z: n.z * ratio }, n, 700);
  }

  function destroy(handle) {
    if (!handle) return;
    handle.stop();
    if (handle.observer) handle.observer.disconnect();
    if (handle.resize) handle.resize.disconnect();
    if (typeof handle.scene._destructor === "function") handle.scene._destructor();
    handle.box.replaceChildren();
  }

  window.AMGraph3D = { available, render, focus, destroy };
})();
