(function () {
  "use strict";

  var container = document.getElementById("concept-graph");
  if (!container) return;

  var dataEl = document.getElementById("concept-graph-data");
  var payload = { nodes: [], edges: [] };
  try {
    payload = JSON.parse((dataEl && dataEl.textContent) || "{}");
  } catch (err) {
    payload = { nodes: [], edges: [] };
  }

  if (!payload.nodes || !payload.nodes.length) {
    var empty = document.createElement("p");
    empty.className = "concept-graph__empty";
    empty.textContent = "هنوز مفهومی برای نمایش در گراف نیست.";
    container.appendChild(empty);
    return;
  }

  if (typeof cytoscape === "undefined") return;
  if (typeof cytoscapeDagre !== "undefined") {
    cytoscape.use(cytoscapeDagre);
  }

  var rootStyle = getComputedStyle(document.documentElement);
  function cssVar(name, fallback) {
    var value = rootStyle.getPropertyValue(name);
    return value && value.trim() ? value.trim() : fallback;
  }

  var colors = {
    covered: cssVar("--success", "#35644c"),
    omitted: cssVar("--muted", "#6d6157"),
    not_covered: cssVar("--danger", "#8b3728"),
    tier1: cssVar("--brand", "#1d4268"),
    tier2: cssVar("--brand-soft", "#a8c1d8"),
    tier3: cssVar("--border-strong", "#c4b6a4"),
    closure: cssVar("--info", "#315b7d"),
    edge: cssVar("--border-strong", "#c4b6a4"),
    ink: cssVar("--ink", "#221f1c"),
  };

  function nodeColor(data) {
    if (data.coverage === "covered") return colors.covered;
    if (data.coverage === "omitted") return colors.omitted;
    if (data.coverage === "not_covered") return colors.not_covered;
    if (data.tier === 1) return colors.tier1;
    if (data.tier === 2) return colors.tier2;
    return colors.tier3;
  }

  var cy = cytoscape({
    container: container,
    elements: { nodes: payload.nodes, edges: payload.edges },
    style: [
      {
        selector: "node",
        style: {
          "background-color": function (ele) {
            return nodeColor(ele.data());
          },
          label: "data(label)",
          color: colors.ink,
          "font-size": "11px",
          "text-wrap": "wrap",
          "text-max-width": "90px",
          width: 26,
          height: 26,
          "border-width": function (ele) {
            return ele.data("closure") ? 3 : 0;
          },
          "border-color": colors.closure,
          "border-style": "dashed",
          "text-valign": "bottom",
          "text-halign": "center",
          "text-margin-y": 4,
        },
      },
      {
        selector: "edge",
        style: {
          width: 1.5,
          "line-color": colors.edge,
          "target-arrow-color": colors.edge,
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          opacity: 0.65,
        },
      },
      {
        selector: 'edge[type = "prerequisite"]',
        style: {
          "line-color": colors.closure,
          "target-arrow-color": colors.closure,
          opacity: 0.9,
        },
      },
    ],
    layout: {
      name: typeof cytoscapeDagre !== "undefined" ? "dagre" : "grid",
      rankDir: "TB",
      nodeSep: 28,
      rankSep: 56,
      animate: false,
    },
    wheelSensitivity: 0.2,
  });

  cy.on("tap", "node", function (evt) {
    var id = evt.target.id();
    var row = document.querySelector('[data-cell-key="' + CSS.escape(id) + '"]');
    if (!row) return;
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    row.classList.add("is-highlighted");
    setTimeout(function () {
      row.classList.remove("is-highlighted");
    }, 1500);
  });
})();
