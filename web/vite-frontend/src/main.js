import { marked } from "marked";
import { Network, DataSet } from "vis-network/standalone";
import * as $3Dmol from "3dmol";
import "./style.css";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const APP_NAME = "MatCreator";

const AGENT_MODE_KEY = "mat_agentMode";

const state = {
  sessionId: localStorage.getItem("mat_sessionId") || `session-${Math.floor(Date.now() / 1000)}`,
  userId: localStorage.getItem("mat_userId") || "",
  displayName: localStorage.getItem("mat_displayName") || localStorage.getItem("mat_userId") || "",
  activeSessionUserId: localStorage.getItem("mat_userId") || "",
  isAdmin: false,
  sessionReady: false,
  structure3dViewer: null,
  currentUploads: [],
  isSending: false,
  sendController: null,
  agentMode: localStorage.getItem(AGENT_MODE_KEY) || "normal",
};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const chatArea = document.getElementById("chat-area");
const textInput = document.getElementById("text-input");
const sendBtn = document.getElementById("send-btn");
const fileUploadBtn = document.getElementById("file-upload-btn");
const fileUploadInput = document.getElementById("file-upload-input");
const uploadStatus = document.getElementById("upload-status");
const sessionIdEl = document.getElementById("session-id");
const sessionListEl = document.getElementById("session-list");
const resetBtn = document.getElementById("reset-session");
const refreshSessionsBtn = document.getElementById("refresh-sessions");
const graphViewport = document.getElementById("graph-viewport");
const graphDetail = document.getElementById("graph-detail");
const structureViewer = document.getElementById("structure-viewer");
const svCanvas = document.getElementById("sv-canvas");
const svMeta = document.getElementById("sv-meta");
const svClose = document.getElementById("sv-close");
const graphResizer = document.getElementById("graph-resizer");
const detailResizer = document.getElementById("detail-resizer");
const structureResizer = document.getElementById("structure-resizer");
const graphStatusEl = document.getElementById("graph-status");
const loginModal = document.getElementById("login-modal");
const loginInput = document.getElementById("login-input");
const loginPassword = document.getElementById("login-password");
const loginError = document.getElementById("login-error");
const loginUuidDisplay = document.getElementById("login-uuid-display");
const loginSubmit = document.getElementById("login-submit");
const loginView = document.getElementById("login-view");
const registerView = document.getElementById("register-view");
const regInput = document.getElementById("reg-input");
const regPassword = document.getElementById("reg-password");
const regConfirm = document.getElementById("reg-confirm");
const regError = document.getElementById("reg-error");
const regSubmit = document.getElementById("reg-submit");
const switchToRegister = document.getElementById("switch-to-register");
const switchToLogin = document.getElementById("switch-to-login");
const userDisplay = document.getElementById("user-display");
const editUserBtn = document.getElementById("edit-user");
const logoutBtn = document.getElementById("logout-btn");
const settingsLogoutBtn = document.getElementById("settings-logout-btn");
const benchToggle = null; // removed — replaced by mode-selector
const benchChip = null;  // removed — replaced by agent-mode-chip
const modeSelector = document.getElementById("mode-selector");
const agentModeChip = document.getElementById("agent-mode-chip");
const graphColumn       = document.getElementById("graph-column");
const sidePanel         = document.getElementById("side-panel");
const fileExplorerCol   = document.getElementById("file-explorer-col");
const colResizerGraph   = document.getElementById("col-resizer-graph");
const colResizerSide    = document.getElementById("col-resizer-side");
const colResizerFiles   = document.getElementById("col-resizer-files");
const filesColToggleBtn = document.getElementById("files-col-toggle");
const knowledgeReviewBanner = document.getElementById("knowledge-review-banner");
const knowledgeReviewText = document.getElementById("knowledge-review-text");
const knowledgeReviewSpinner = document.getElementById("knowledge-review-spinner");
let knowledgeReviewPoll = null;

function autoResizeTextInput() {
  if (!textInput) return;
  textInput.style.height = "auto";
  const computed = window.getComputedStyle(textInput);
  const lineHeight = parseFloat(computed.lineHeight) || 24;
  const maxHeight = lineHeight * 3;
  const nextHeight = Math.min(textInput.scrollHeight, maxHeight);
  textInput.style.height = `${nextHeight}px`;
  textInput.style.overflowY = textInput.scrollHeight > maxHeight ? "auto" : "hidden";
}

autoResizeTextInput();
textInput?.addEventListener("input", autoResizeTextInput);

sessionIdEl.textContent = state.sessionId;
if (state.userId) userDisplay.textContent = state.displayName || state.userId;
refreshKnowledgeReviewStatus();

// ---------------------------------------------------------------------------
// Agent Graph Visualization
// ---------------------------------------------------------------------------

const NODE_COLORS = {
  orchestrator: { bg: "#7C3AED", border: "#6D28D9", font: "#fff" },
  planning:     { bg: "#3B82F6", border: "#2563EB", font: "#fff" },
  execution:    { bg: "#10B981", border: "#059669", font: "#fff" },
  tester:       { bg: "#F59E0B", border: "#D97706", font: "#1a1a1a" },
  step:         { bg: "#374151", border: "#4B5563", font: "#e5e7eb" },
};

const STATUS_COLORS = {
  running:          { bg: "#FBBF24", border: "#F59E0B", font: "#1a1a1a" },
  success:          null,
  failed:           { bg: "#EF4444", border: "#DC2626", font: "#fff" },
  needs_replanning: { bg: "#F97316", border: "#EA580C", font: "#fff" },
  idle:             { bg: "#374151", border: "#4B5563", font: "#9CA3AF" },
};

const MOBILE_LAYOUT_QUERY = window.matchMedia("(max-width: 900px)");
const PANEL_HEIGHT_DEFAULTS = {
  "graph-viewport": 600,
  "graph-detail": 500,
  "structure-viewer": 500,
};
const PANEL_HEIGHT_BOUNDS = {
  "graph-viewport": { min: 220, max: 1200 },
  "graph-detail": { min: 110, max: 600 },
  "structure-viewer": { min: 140, max: 900 },
};

const COL_WIDTH_DEFAULTS = {
  "graph-column": 360,
  "side-panel": 300,
  "file-explorer-col": 260,
};
const COL_WIDTH_BOUNDS = {
  "graph-column":      { min: 240, max: 600 },
  "side-panel":        { min: 200, max: 500 },
  "file-explorer-col": { min: 160, max: 500 },
};

class AgentGraphView {
  constructor(containerId) {
    this._container = document.getElementById(containerId);
    this._surfaceEl = document.getElementById("graph-surface");
    this._nodes = new DataSet([]);
    this._edges = new DataSet([]);
    this._network = null;
    this._pollInterval = null;
    this._didInitialFit = false;
    this._pendingFit = true;
    this._detailEl = document.getElementById("graph-detail");
    this._detailLabel = document.getElementById("detail-label");
    this._detailStatus = document.getElementById("detail-status");
    this._detailSummary = document.getElementById("detail-summary");
    this._detailArtifacts = document.getElementById("detail-artifacts");
    this._detailTiming = document.getElementById("detail-timing");
    this._detailInput = document.getElementById("detail-input");
    this._detailToolcalls = document.getElementById("detail-toolcalls");
    this._detailToolcallsCount = document.getElementById("detail-toolcalls-count");
    this._detailConversation = document.getElementById("detail-conversation");
    this._nodeData = {};
    this._activeDetailNodeId = null;
    this._init();
  }

  _captureOpenToolCallKeys() {
    const openKeys = new Set();
    this._detailToolcalls?.querySelectorAll("details[data-toolcall-key][open]")?.forEach((el) => {
      openKeys.add(el.getAttribute("data-toolcall-key"));
    });
    return openKeys;
  }

  _restoreOpenToolCallKeys(openKeys) {
    if (!openKeys?.size) return;
    this._detailToolcalls?.querySelectorAll("details[data-toolcall-key]")?.forEach((el) => {
      el.open = openKeys.has(el.getAttribute("data-toolcall-key"));
    });
  }

  _init() {
    const options = {
      layout: {
        hierarchical: {
          direction: "UD",
          sortMethod: "directed",
          nodeSpacing: 120,
          levelSeparation: 90,
          blockShifting: true,
          edgeMinimization: true,
        },
      },
      physics: { enabled: false },
      edges: {
        arrows: { to: { enabled: true, scaleFactor: 0.6 } },
        color: { color: "#4B5563", highlight: "#9CA3AF" },
        width: 1.5,
        smooth: { type: "cubicBezier", forceDirection: "vertical" },
      },
      nodes: {
        shape: "box",
        borderWidth: 2,
        borderWidthSelected: 3,
        font: { size: 13, face: "Manrope, sans-serif" },
        margin: { top: 8, bottom: 8, left: 12, right: 12 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 200,
        dragNodes: true,
        dragView: true,
        zoomView: true,
      },
    };

    this._network = new Network(
      this._container,
      { nodes: this._nodes, edges: this._edges },
      options
    );

    this._network.on("selectNode", (params) => {
      if (params.nodes.length) this._showDetail(params.nodes[0]);
    });
    this._network.on("deselectNode", () => this._hideDetail());
  }

  _visNode(raw) {
    const typeColors = NODE_COLORS[raw.type] || NODE_COLORS.step;
    const statusOverride = STATUS_COLORS[raw.status];
    const colors = statusOverride || typeColors;
    const isRunning = raw.status === "running";
    return {
      id: raw.id,
      label: raw.label,
      color: {
        background: colors.bg,
        border: colors.border,
        highlight: { background: colors.border, border: colors.border },
      },
      font: { color: colors.font },
      shapeProperties: isRunning ? { borderDashes: [4, 3] } : {},
      borderWidth: isRunning ? 2.5 : 2,
      title: raw.summary || raw.label,
    };
  }

  _computeLevels(rawNodes, edges) {
    const nodeMap = Object.fromEntries(rawNodes.map(n => [n.id, n]));
    const children = {};
    const hasParent = new Set();
    edges.forEach(e => {
      (children[e.from] = children[e.from] || []).push(e.to);
      hasParent.add(e.to);
    });
    const roots = rawNodes.map(n => n.id).filter(id => !hasParent.has(id));
    const levels = {};

    // Recursively assign levels. Among siblings, sort by start_time and
    // increment the level each time a child starts after the previous group ends
    // (sequential). Children whose time windows overlap stay at the same level
    // (parallel).
    function assign(id, minLevel) {
      if (levels[id] !== undefined && levels[id] >= minLevel) return;
      levels[id] = minLevel;

      const currentType = nodeMap[id]?.type;
      if (currentType === "orchestrator") {
        (children[id] || []).forEach((kid) => assign(kid, 1));
        return;
      }
      if (currentType === "planning") {
        (children[id] || []).forEach((kid) => assign(kid, 2));
        return;
      }

      const kids = (children[id] || []).slice().sort((a, b) => {
        const ta = nodeMap[a]?.start_time ? new Date(nodeMap[a].start_time).getTime() : Infinity;
        const tb = nodeMap[b]?.start_time ? new Date(nodeMap[b].start_time).getTime() : Infinity;
        return ta - tb;
      });

      let nextLevel = minLevel + 1;
      let groupEndTime = null; // latest end_time seen in the current parallel group

      for (const kid of kids) {
        const kidStart = nodeMap[kid]?.start_time ? new Date(nodeMap[kid].start_time).getTime() : null;
        const kidEnd   = nodeMap[kid]?.end_time   ? new Date(nodeMap[kid].end_time).getTime()   : null;

        if (groupEndTime !== null && kidStart !== null && kidStart >= groupEndTime) {
          // This child starts after the previous group ended — sequential, new level
          nextLevel++;
          groupEndTime = kidEnd;
        } else {
          // Concurrent with previous group (or no timing info) — extend group window
          if (groupEndTime === null || (kidEnd !== null && kidEnd > groupEndTime)) {
            groupEndTime = kidEnd;
          }
        }

        assign(kid, nextLevel);
      }
    }

    roots.forEach(r => assign(r, 0));
    return levels;
  }

  _buildDisplayEdges(rawNodes, edges) {
    const nodeMap = Object.fromEntries(rawNodes.map((n) => [n.id, n]));
    const phaseTypes = new Set(["planning", "execution", "tester"]);
    const displayEdges = [];
    const phaseNodes = rawNodes
      .filter((n) => n.parent_id === "orchestrator" && phaseTypes.has(n.type))
      .sort((a, b) => {
        const ta = a.start_time ? new Date(a.start_time).getTime() : Infinity;
        const tb = b.start_time ? new Date(b.start_time).getTime() : Infinity;
        return ta - tb;
      });

    const planningNodes = phaseNodes.filter((n) => n.type === "planning");
    const childPhaseNodes = phaseNodes.filter((n) => n.type !== "planning");

    planningNodes.forEach((planning) => {
      displayEdges.push({
        id: `phase__orchestrator__${planning.id}`,
        from: "orchestrator",
        to: planning.id,
      });
    });

    childPhaseNodes.forEach((node) => {
      let parentPlanning = null;
      const nodeStart = node.start_time ? new Date(node.start_time).getTime() : Infinity;

      for (const planning of planningNodes) {
        const planningStart = planning.start_time ? new Date(planning.start_time).getTime() : -Infinity;
        if (planningStart <= nodeStart) {
          parentPlanning = planning;
        } else {
          break;
        }
      }

      displayEdges.push({
        id: `phase__${(parentPlanning || { id: "orchestrator" }).id}__${node.id}`,
        from: parentPlanning ? parentPlanning.id : "orchestrator",
        to: node.id,
      });
    });

    (edges || []).forEach((edge) => {
      const fromNode = nodeMap[edge.from];
      const toNode = nodeMap[edge.to];
      if (!fromNode || !toNode) return;

      const isTopLevelPhaseEdge =
        edge.from === "orchestrator" &&
        toNode.parent_id === "orchestrator" &&
        phaseTypes.has(toNode.type);

      if (isTopLevelPhaseEdge) return;

      displayEdges.push({
        id: edge.id || `${edge.from}__${edge.to}`,
        from: edge.from,
        to: edge.to,
      });
    });

    return displayEdges;
  }

  _resizeSurface(levels) {
    if (!this._surfaceEl || !graphViewport) return;

    // Keep the graph canvas matched to the visible viewport so vis-network's
    // fit() shows the whole graph in the default view instead of fitting into
    // an oversized off-screen surface.
    const targetWidth = Math.max(620, Math.round(graphViewport.clientWidth || 620));
    const targetHeight = Math.max(420, Math.round(graphViewport.clientHeight || 420));
    this._surfaceEl.style.width = `${targetWidth}px`;
    this._surfaceEl.style.height = `${targetHeight}px`;
  }

  _fitGraph() {
    if (!this._network || this._nodes.length === 0) return;
    this._network.fit({ animation: { duration: 300, easingFunction: "easeInOutQuad" } });
    this._didInitialFit = true;
    this._pendingFit = false;
  }

  update(graphData) {
    if (!graphData || typeof graphData.nodes !== "object") return;

    const rawNodes = Object.values(graphData.nodes);
    this._nodeData = graphData.nodes;
    const displayEdges = this._buildDisplayEdges(rawNodes, graphData.edges || []);
    const levels = this._computeLevels(rawNodes, displayEdges);
    this._resizeSurface(levels);

    rawNodes.forEach((raw) => {
      const vis = this._visNode(raw);
      vis.level = levels[raw.id] ?? 0;
      if (this._nodes.get(raw.id)) {
        this._nodes.update(vis);
      } else {
        this._nodes.add(vis);
      }
    });

    const displayEdgeIds = new Set(displayEdges.map((e) => e.id || `${e.from}__${e.to}`));
    this._edges.getIds().forEach((edgeId) => {
      if (!displayEdgeIds.has(edgeId)) this._edges.remove(edgeId);
    });

    const existingEdgeIds = new Set(this._edges.getIds());
    displayEdges.forEach((e) => {
      const edgeId = e.id || `${e.from}__${e.to}`;
      if (!existingEdgeIds.has(edgeId)) {
        this._edges.add({
          id: edgeId,
          from: e.from,
          to: e.to,
          hidden: false,
          physics: false,
          smooth: { type: "cubicBezier", forceDirection: "vertical" },
        });
      }
    });

    if (rawNodes.length > 0 && (!this._didInitialFit || this._pendingFit)) {
      this._fitGraph();
    }

    if (this._activeDetailNodeId) {
      if (this._nodeData[this._activeDetailNodeId]) {
        this._showDetail(this._activeDetailNodeId, { preserveScroll: true });
      } else {
        this._hideDetail();
      }
    }
  }

  startPolling(sessionId) {
    this._currentSessionId = sessionId;
    this._setStatus("polling");
    this._poll(sessionId);
    this._pollInterval = setInterval(() => this._poll(sessionId), 2000);
  }

  stopPolling() {
    if (this._pollInterval) {
      clearInterval(this._pollInterval);
      this._pollInterval = null;
    }
    this._setStatus("idle");
  }

  async _poll(sessionId) {
    try {
      const resp = await fetch(`/api/agent-graph/${sessionId}`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (sessionId !== this._currentSessionId) return;
      this.update(data);
    } catch (_) {
      // silently ignore network errors during polling
    }
  }

  reset() {
    this._currentSessionId = null;
    this._nodes.clear();
    this._edges.clear();
    this._nodeData = {};
    this._didInitialFit = false;
    this._pendingFit = true;
    this._resizeSurface([], { 0: 1 });
    this._hideDetail();
    this._setStatus("idle");
    this.stopPolling();
  }

  _setStatus(s) {
    if (graphStatusEl) {
      graphStatusEl.textContent = s;
      graphStatusEl.className = `graph-status status-${s}`;
    }
  }

  _showDetail(nodeId, options = {}) {
    const raw = this._nodeData[nodeId];
    if (!raw) return;
    this._activeDetailNodeId = nodeId;
    const preserveScroll = Boolean(options.preserveScroll);
    const prevScrollTop = preserveScroll ? this._detailEl.scrollTop : 0;
    const prevOpenToolCallKeys = preserveScroll ? this._captureOpenToolCallKeys() : new Set();
    structureViewer.classList.add("hidden");
    state.structure3dViewer = null;
    svCanvas.innerHTML = "";
    this._detailLabel.textContent = raw.label;
    this._detailStatus.textContent = raw.status;
    this._detailStatus.className = `badge badge-${raw.status}`;
    this._detailSummary.textContent = raw.summary || "—";

    // Timing
    if (raw.start_time) {
      const start = new Date(raw.start_time);
      if (raw.end_time) {
        const end = new Date(raw.end_time);
        const secs = ((end - start) / 1000).toFixed(1);
        this._detailTiming.textContent = `${secs}s`;
      } else {
        this._detailTiming.textContent = "running…";
      }
    } else {
      this._detailTiming.textContent = "—";
    }

    // Stop-step button (only for running step nodes)
    const actionsRow = document.getElementById("detail-actions-row");
    const stopStepBtn = document.getElementById("detail-stop-step-btn");
    const stepNumber = raw.input && raw.input.step_number;
    if (raw.type === "step" && raw.status === "running" && stepNumber) {
      stopStepBtn.disabled = false;
      stopStepBtn.textContent = "Stop step";
      stopStepBtn.onclick = () => {
        fetch(`/api/sessions/${state.sessionId}/cancel-step/${stepNumber}`, { method: "POST" }).catch(() => {});
        stopStepBtn.disabled = true;
        stopStepBtn.textContent = "Stopping…";
      };
      actionsRow.style.display = "";
    } else {
      actionsRow.style.display = "none";
    }
    this._detailArtifacts.innerHTML = "";
    const arts = raw.artifacts || [];
    if (arts.length) {
      arts.forEach((a) => {
        const li = document.createElement("li");
        li.textContent = a.split("/").pop();
        li.title = a;
        this._detailArtifacts.appendChild(li);
      });
    } else {
      const li = document.createElement("li");
      li.textContent = "none";
      this._detailArtifacts.appendChild(li);
    }

    // Input parameters
    if (raw.input && Object.keys(raw.input).length) {
      this._detailInput.textContent = JSON.stringify(raw.input, null, 2);
      document.getElementById("detail-input-row").style.display = "";
    } else {
      document.getElementById("detail-input-row").style.display = "none";
    }

    // Tool calls
    const toolCalls = raw.tool_calls || [];
    this._detailToolcallsCount.textContent = toolCalls.length;
    this._detailToolcalls.innerHTML = "";
    if (toolCalls.length) {
      toolCalls.forEach((tc) => {
        const d = document.createElement("details");
        d.className = "timeline-function-call";
        d.setAttribute("data-toolcall-key", tc.id || `${tc.name}:${tc.start_time || ""}`);
        const dur = tc.start_time && tc.end_time
          ? ` (${((new Date(tc.end_time) - new Date(tc.start_time)) / 1000).toFixed(1)}s)`
          : "";
        const s = document.createElement("summary");
        s.textContent = `🔧 ${tc.name}${dur}`;
        d.appendChild(s);
        if (tc.args_summary) {
          const pre = document.createElement("pre");
          pre.className = "json-block";
          pre.textContent = tc.args_summary;
          d.appendChild(pre);
        }
        if (tc.result_summary) {
          const pre = document.createElement("pre");
          pre.className = "json-block";
          pre.style.borderTop = "1px solid rgba(255,255,255,0.06)";
          pre.textContent = `→ ${tc.result_summary}`;
          d.appendChild(pre);
        }
        this._detailToolcalls.appendChild(d);
      });
      document.getElementById("detail-toolcalls-row").style.display = "";
    } else {
      document.getElementById("detail-toolcalls-row").style.display = "none";
    }

    // Conversation transcript
    const conversation = raw.conversation || [];
    this._detailConversation.innerHTML = "";
    if (conversation.length) {
      conversation.forEach((evt) => {
        const d = document.createElement("details");
        d.className = `timeline-${evt.type}`;
        const s = document.createElement("summary");
        const icon = evt.type === "thought" ? "💭" : evt.type === "text" ? "💬" : evt.type === "function_call" ? "🔧" : "↩";
        s.textContent = `${icon} [${evt.author}] ${evt.type}`;
        d.appendChild(s);
        const pre = document.createElement("pre");
        pre.className = "json-block";
        pre.textContent = evt.content;
        d.appendChild(pre);
        this._detailConversation.appendChild(d);
      });
      document.getElementById("detail-conversation-row").style.display = "";
    } else {
      document.getElementById("detail-conversation-row").style.display = "none";
    }

    this._detailEl.classList.remove("hidden");
    syncPanelResizerVisibility();
    if (preserveScroll) {
      this._restoreOpenToolCallKeys(prevOpenToolCallKeys);
      this._detailEl.scrollTop = prevScrollTop;
    }
  }

  _hideDetail() {
    this._activeDetailNodeId = null;
    this._detailEl.classList.add("hidden");
    syncPanelResizerVisibility();
  }

  notifyLayoutChanged() {
    if (!this._network) return;
    this._network.redraw();
  }
}

// ---------------------------------------------------------------------------
// Execution Plan Graph (floating popup in chat column)
// ---------------------------------------------------------------------------

const PLAN_NODE_STATUS_COLORS = {
  pending:   { bg: "#374151", border: "#6B7280", font: "#9CA3AF" },
  running:   { bg: "#FBBF24", border: "#F59E0B", font: "#1a1a1a" },
  success:   { bg: "#10B981", border: "#059669", font: "#fff" },
  failed:    { bg: "#EF4444", border: "#DC2626", font: "#fff" },
  blocked:   { bg: "#1F2937", border: "#374151", font: "#4B5563" },
};

class ExecutionPlanView {
  constructor(containerId) {
    this._container = document.getElementById(containerId);
    this._network = null;
    this._pollInterval = null;
    this._didInitialFit = false;
    this._structureKey = null;
    this._init();
  }

  _init() {
    if (!this._container) return;
    const options = {
      layout: {
        hierarchical: {
          direction: "UD",
          sortMethod: "directed",
          nodeSpacing: 120,
          levelSeparation: 90,
          blockShifting: true,
          edgeMinimization: true,
        },
      },
      physics: { enabled: false },
      edges: {
        arrows: { to: { enabled: true, scaleFactor: 0.6 } },
        color: { color: "#4B5563", highlight: "#9CA3AF" },
        width: 1.5,
        smooth: { type: "cubicBezier", forceDirection: "vertical" },
      },
      nodes: {
        shape: "box",
        borderWidth: 2,
        borderWidthSelected: 3,
        font: { size: 14, face: "Manrope, sans-serif" },
        margin: { top: 8, bottom: 8, left: 12, right: 12 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 200,
        dragNodes: true,
        dragView: true,
        zoomView: true,
      },
    };
    this._network = new Network(
      this._container,
      { nodes: new DataSet([]), edges: new DataSet([]) },
      options
    );
  }

  _computeLevels(nodeIds, rawEdges) {
    const inDeg = Object.fromEntries(nodeIds.map((id) => [id, 0]));
    const adj   = Object.fromEntries(nodeIds.map((id) => [id, []]));
    rawEdges.forEach((e) => {
      const from = Array.isArray(e) ? e[0] : e.from;
      const to   = Array.isArray(e) ? e[1] : e.to;
      if (adj[from]) adj[from].push(to);
      if (to in inDeg) inDeg[to]++;
    });
    const levels = {};
    const queue = nodeIds.filter((id) => inDeg[id] === 0);
    queue.forEach((id) => { levels[id] = 0; });
    while (queue.length) {
      const curr = queue.shift();
      (adj[curr] || []).forEach((nxt) => {
        levels[nxt] = Math.max(levels[nxt] ?? 0, (levels[curr] ?? 0) + 1);
        if (--inDeg[nxt] === 0) queue.push(nxt);
      });
    }
    nodeIds.forEach((id) => { if (!(id in levels)) levels[id] = 0; });
    return levels;
  }

  _visNode(nodeId, node, level) {
    const status = node.status || "pending";
    const isRunning = status === "running";
    const colors = PLAN_NODE_STATUS_COLORS[status] || PLAN_NODE_STATUS_COLORS.pending;
    return {
      id: nodeId,
      label: node.label || nodeId,
      title: node.action || nodeId,
      level,
      color: {
        background: colors.bg,
        border: colors.border,
        highlight: { background: colors.border, border: colors.border },
      },
      font: { color: colors.font, size: 14 },
      shapeProperties: isRunning ? { borderDashes: [4, 3] } : {},
      borderWidth: isRunning ? 2.5 : 2,
    };
  }

  update(graphData) {
    if (!graphData || typeof graphData.nodes !== "object") return;
    const nodeEntries = Object.entries(graphData.nodes);
    if (nodeEntries.length === 0) return;

    // Auto-show popup on first data
    if (!this._didInitialFit && planGraphPopup?.classList.contains("hidden")) {
      showPlanGraph();
    }

    const rawEdges = graphData.edges || [];
    const nodeIds  = nodeEntries.map(([id]) => id);
    const levels   = this._computeLevels(nodeIds, rawEdges);

    const visNodes = nodeEntries.map(([id, n]) => this._visNode(id, n, levels[id] ?? 0));
    const visEdges = rawEdges.map((e) => {
      const from = Array.isArray(e) ? e[0] : e.from;
      const to   = Array.isArray(e) ? e[1] : e.to;
      return {
        id: `e__${from}__${to}`,
        from,
        to,
        physics: false,
        hidden: false,
        smooth: { type: "cubicBezier", forceDirection: "vertical" },
      };
    });

    // Rebuild via setData so hierarchical layout sees nodes + edges together.
    // Re-fit only when structure changes to avoid jarring jumps on status updates.
    const structureKey = JSON.stringify({ ids: [...nodeIds].sort(), edges: rawEdges });
    const structureChanged = structureKey !== this._structureKey;
    this._network.setData({ nodes: new DataSet(visNodes), edges: new DataSet(visEdges) });
    if (structureChanged || !this._didInitialFit) {
      this._structureKey = structureKey;
      this._network.fit({ animation: { duration: 300, easingFunction: "easeInOutQuad" } });
      this._didInitialFit = true;
    }
  }

  startPolling(sessionId) {
    this._currentSessionId = sessionId;
    this._setStatus("polling");
    this._poll(sessionId);
    this._pollInterval = setInterval(() => this._poll(sessionId), 2000);
  }

  stopPolling() {
    if (this._pollInterval) {
      clearInterval(this._pollInterval);
      this._pollInterval = null;
    }
    this._setStatus("idle");
  }

  async _poll(sessionId) {
    try {
      const resp = await fetch(`/api/execution-graph/${sessionId}`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (sessionId !== this._currentSessionId) return;
      this.update(data);
    } catch (_) {}
  }

  reset() {
    this._currentSessionId = null;
    this._network?.setData({ nodes: new DataSet([]), edges: new DataSet([]) });
    this._didInitialFit = false;
    this._structureKey = null;
    this.stopPolling();
  }

  notifyLayoutChanged() {
    this._network?.redraw();
    this._network?.fit({ animation: false });
  }

  _setStatus(s) {
    const el = document.getElementById("plan-graph-status");
    if (el) { el.textContent = s; el.className = `graph-status status-${s}`; }
  }
}

const agentGraph = new AgentGraphView("agent-graph");
const planGraph = new ExecutionPlanView("plan-graph-canvas");

// ---------------------------------------------------------------------------
// Plan graph popup toggle
// ---------------------------------------------------------------------------

const planGraphPopup = document.getElementById("plan-graph-popup");
const planGraphToggleBtn = document.getElementById("plan-graph-toggle");
const planGraphCloseBtn = document.getElementById("plan-graph-close");

function showPlanGraph() {
  planGraphPopup?.classList.remove("hidden");
  planGraph.notifyLayoutChanged();
}

function hidePlanGraph() {
  planGraphPopup?.classList.add("hidden");
}

planGraphToggleBtn?.addEventListener("click", () => {
  if (planGraphPopup?.classList.contains("hidden")) {
    showPlanGraph();
  } else {
    hidePlanGraph();
  }
});

planGraphCloseBtn?.addEventListener("click", hidePlanGraph);
// ---------------------------------------------------------------------------

function isMobileLayout() {
  return MOBILE_LAYOUT_QUERY.matches;
}

function panelStorageKey(targetId) {
  const user = state.userId || "anon";
  return `mat_panel_height_${user}_${targetId}`;
}

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function getTargetHeight(targetEl) {
  return Math.round(targetEl.getBoundingClientRect().height);
}

function applyTargetHeight(targetEl, heightPx) {
  if (!targetEl) return;
  const bounds = PANEL_HEIGHT_BOUNDS[targetEl.id];
  if (!bounds) return;
  targetEl.style.height = `${clamp(heightPx, bounds.min, bounds.max)}px`;
}

function persistTargetHeight(targetEl) {
  if (!targetEl) return;
  localStorage.setItem(panelStorageKey(targetEl.id), String(getTargetHeight(targetEl)));
}

function applyStoredPanelHeights() {
  for (const [targetId, fallback] of Object.entries(PANEL_HEIGHT_DEFAULTS)) {
    const el = document.getElementById(targetId);
    if (!el) continue;
    if (isMobileLayout()) {
      el.style.removeProperty("height");
      continue;
    }

    const raw = localStorage.getItem(panelStorageKey(targetId));
    const parsed = raw ? Number(raw) : fallback;
    const nextHeight = Number.isFinite(parsed) ? parsed : fallback;
    applyTargetHeight(el, nextHeight);
  }
}

function refreshGraphAndStructureLayout() {
  agentGraph.notifyLayoutChanged();
  if (state.structure3dViewer && !structureViewer.classList.contains("hidden")) {
    try {
      state.structure3dViewer.resize();
      state.structure3dViewer.render();
    } catch (_) {
      // ignore transient resize/render issues
    }
  }
}

function syncPanelResizerVisibility() {
  const hideAll = isMobileLayout();
  const detailHidden = graphDetail.classList.contains("hidden");
  const structureHidden = structureViewer.classList.contains("hidden");

  if (graphResizer) {
    graphResizer.classList.toggle("hidden", hideAll);
  }

  if (detailResizer) {
    detailResizer.classList.toggle("hidden", hideAll || detailHidden);
  }

  if (structureResizer) {
    structureResizer.classList.toggle("hidden", hideAll || structureHidden);
  }
}

function initPanelResizer(handleEl, targetEl) {
  if (!handleEl || !targetEl) return;

  const keyStep = 16;

  const commit = () => {
    persistTargetHeight(targetEl);
    refreshGraphAndStructureLayout();
  };

  const resizeBy = (delta) => {
    const curr = getTargetHeight(targetEl);
    applyTargetHeight(targetEl, curr + delta);
    refreshGraphAndStructureLayout();
  };

  handleEl.addEventListener("pointerdown", (e) => {
    if (isMobileLayout() || handleEl.classList.contains("hidden")) return;
    e.preventDefault();

    const startY = e.clientY;
    const startHeight = getTargetHeight(targetEl);
    handleEl.classList.add("resizing");
    handleEl.setPointerCapture(e.pointerId);

    const onMove = (moveEvt) => {
      const dy = moveEvt.clientY - startY;
      applyTargetHeight(targetEl, startHeight + dy);
      refreshGraphAndStructureLayout();
    };

    const onUp = () => {
      handleEl.classList.remove("resizing");
      handleEl.removeEventListener("pointermove", onMove);
      handleEl.removeEventListener("pointerup", onUp);
      handleEl.removeEventListener("pointercancel", onUp);
      commit();
    };

    handleEl.addEventListener("pointermove", onMove);
    handleEl.addEventListener("pointerup", onUp);
    handleEl.addEventListener("pointercancel", onUp);
  });

  handleEl.addEventListener("keydown", (e) => {
    if (isMobileLayout() || handleEl.classList.contains("hidden")) return;
    if (e.key === "ArrowUp") {
      e.preventDefault();
      resizeBy(-keyStep);
      commit();
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      resizeBy(keyStep);
      commit();
    }
  });
}

// ---------------------------------------------------------------------------
// Column (horizontal) resizing — mirrors the panel (vertical) resizer pattern
// ---------------------------------------------------------------------------

function colStorageKey(colId) {
  return `mat_col_width_${state.userId || "anon"}_${colId}`;
}
function filesColOpenKey() {
  return `mat_files_col_open_${state.userId || "anon"}`;
}
function isFilesColOpen() {
  return localStorage.getItem(filesColOpenKey()) === "true";
}
function setFilesColOpen(open) {
  localStorage.setItem(filesColOpenKey(), String(open));
}
function getColWidth(colEl) {
  return Math.round(colEl.getBoundingClientRect().width);
}
function applyColWidth(colEl, widthPx) {
  const bounds = COL_WIDTH_BOUNDS[colEl.id];
  if (!bounds) return;
  colEl.style.width = `${clamp(widthPx, bounds.min, bounds.max)}px`;
}
function persistColWidth(colEl) {
  localStorage.setItem(colStorageKey(colEl.id), String(getColWidth(colEl)));
}
function applyStoredColWidths() {
  for (const colId of ["graph-column", "side-panel"]) {
    const el = document.getElementById(colId);
    if (!el) continue;
    if (isMobileLayout()) { el.style.removeProperty("width"); continue; }
    const raw = localStorage.getItem(colStorageKey(colId));
    const w = raw ? Number(raw) : COL_WIDTH_DEFAULTS[colId];
    applyColWidth(el, Number.isFinite(w) ? w : COL_WIDTH_DEFAULTS[colId]);
  }
}
function applyFilesColState(open) {
  if (!fileExplorerCol) return;
  if (isMobileLayout()) {
    fileExplorerCol.style.removeProperty("width");
    fileExplorerCol.classList.remove("is-open");
    colResizerFiles?.classList.add("hidden");
    filesColToggleBtn?.classList.remove("is-active");
    return;
  }
  if (open) {
    fileExplorerCol.classList.add("is-open");
    const raw = localStorage.getItem(colStorageKey("file-explorer-col"));
    const w = raw ? Number(raw) : COL_WIDTH_DEFAULTS["file-explorer-col"];
    applyColWidth(fileExplorerCol, w);
    colResizerFiles?.classList.remove("hidden");
    filesColToggleBtn?.classList.add("is-active");
  } else {
    fileExplorerCol.classList.remove("is-open");
    fileExplorerCol.style.width = "0";
    colResizerFiles?.classList.add("hidden");
    filesColToggleBtn?.classList.remove("is-active");
  }
}
function toggleFilesCol() {
  const willOpen = !isFilesColOpen();
  setFilesColOpen(willOpen);
  applyFilesColState(willOpen);
  if (willOpen) refreshSessionFiles();
}
function syncColResizerVisibility() {
  const mobile = isMobileLayout();
  colResizerGraph?.classList.toggle("hidden", mobile);
  colResizerSide?.classList.toggle("hidden", mobile);
  colResizerFiles?.classList.toggle("hidden", mobile || !isFilesColOpen());
}

/**
 * initColResizer — horizontal mirror of initPanelResizer.
 * direction: +1 = drag-right widens targetEl (left col), -1 = drag-right narrows it (right col).
 */
function initColResizer(handleEl, targetEl, direction = 1) {
  if (!handleEl || !targetEl) return;
  const keyStep = 16;
  const commit = () => {
    persistColWidth(targetEl);
    refreshGraphAndStructureLayout();
  };
  handleEl.addEventListener("pointerdown", (e) => {
    if (isMobileLayout() || handleEl.classList.contains("hidden")) return;
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = getColWidth(targetEl);
    handleEl.classList.add("resizing");
    handleEl.setPointerCapture(e.pointerId);
    const onMove = (moveEvt) => {
      applyColWidth(targetEl, startWidth + direction * (moveEvt.clientX - startX));
      refreshGraphAndStructureLayout();
    };
    const onUp = () => {
      handleEl.classList.remove("resizing");
      handleEl.removeEventListener("pointermove", onMove);
      handleEl.removeEventListener("pointerup", onUp);
      handleEl.removeEventListener("pointercancel", onUp);
      commit();
    };
    handleEl.addEventListener("pointermove", onMove);
    handleEl.addEventListener("pointerup", onUp);
    handleEl.addEventListener("pointercancel", onUp);
  });
  handleEl.addEventListener("keydown", (e) => {
    if (isMobileLayout() || handleEl.classList.contains("hidden")) return;
    if (e.key === "ArrowLeft")  { e.preventDefault(); applyColWidth(targetEl, getColWidth(targetEl) + direction * -keyStep); commit(); }
    if (e.key === "ArrowRight") { e.preventDefault(); applyColWidth(targetEl, getColWidth(targetEl) + direction *  keyStep); commit(); }
  });
}

function initColResizers() {
  applyStoredColWidths();
  applyFilesColState(isFilesColOpen());
  syncColResizerVisibility();
  initColResizer(colResizerGraph, graphColumn, 1);
  initColResizer(colResizerSide, sidePanel, -1);
  initColResizer(colResizerFiles, fileExplorerCol, -1);
  filesColToggleBtn?.addEventListener("click", toggleFilesCol);
  MOBILE_LAYOUT_QUERY.addEventListener("change", () => {
    applyStoredColWidths();
    applyFilesColState(isFilesColOpen());
    syncColResizerVisibility();
    refreshGraphAndStructureLayout();
  });
}

function initPanelResizers() {
  applyStoredPanelHeights();
  initPanelResizer(graphResizer, graphViewport);
  initPanelResizer(detailResizer, graphDetail);
  initPanelResizer(structureResizer, structureViewer);
  syncPanelResizerVisibility();

  MOBILE_LAYOUT_QUERY.addEventListener("change", () => {
    applyStoredPanelHeights();
    syncPanelResizerVisibility();
    refreshGraphAndStructureLayout();
  });
}

// ---------------------------------------------------------------------------
// Login / username management
// ---------------------------------------------------------------------------

function _isUuid(s) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s);
}

function _isValidIdentity(s) {
  return s === "user" || _isUuid(s);
}

function showLoginModal() {
  loginModal.classList.remove("hidden");
  loginView.classList.remove("hidden");
  registerView.classList.add("hidden");
  loginInput.value = state.displayName || "";
  loginPassword.value = "";
  loginError.textContent = "";
  loginUuidDisplay.textContent = state.userId ? `UUID: ${state.userId}` : "";
  // Hide register link when already logged in — log out first to register a new account.
  const registerLink = document.getElementById("switch-to-register")?.parentElement;
  if (registerLink) registerLink.style.display = state.userId ? "none" : "";
  loginInput.focus();
}

function logout() {
  state.userId = "";
  state.displayName = "";
  state.activeSessionUserId = "";
  state.isAdmin = false;
  state.sessionReady = false;
  localStorage.removeItem("mat_userId");
  localStorage.removeItem("mat_displayName");
  localStorage.removeItem("mat_sessionId");
  userDisplay.textContent = "—";
  chatArea.innerHTML = "";
  sessionListEl.innerHTML = '<li class="empty">Sign in to see sessions</li>';
  renderSessionFilesTree([]);
  clearCurrentUploads();
  agentGraph.reset();
  planGraph.reset();
  hidePlanGraph();
  closeSettingsModal();
  showLoginModal();
}

function showRegisterModal() {
  loginModal.classList.remove("hidden");
  loginView.classList.add("hidden");
  registerView.classList.remove("hidden");
  regInput.value = "";
  regPassword.value = "";
  regConfirm.value = "";
  regError.textContent = "";
  regInput.focus();
}

function hideLoginModal() {
  loginModal.classList.add("hidden");
}

function renderUserDisplay() {
  const label = state.displayName || state.userId;
  userDisplay.textContent = state.isAdmin ? `${label} (admin)` : label;
}

async function refreshAccess() {
  state.isAdmin = false;
  if (!state.userId) return;
  try {
    const resp = await fetch(`/api/session-access/${encodeURIComponent(state.userId)}`);
    if (!resp.ok) return;
    const access = await resp.json();
    state.isAdmin = Boolean(access.is_admin);
  } catch (_) {
    state.isAdmin = false;
  }
}

function _applySession(result) {
  state.userId = result.user_id;
  state.displayName = result.display_name;
  state.activeSessionUserId = result.user_id;
  state.sessionId = `session-${Math.floor(Date.now() / 1000)}`;
  state.sessionReady = false;
  state.isAdmin = Boolean(result.is_admin);
  loginUuidDisplay.textContent = `UUID: ${result.user_id}`;
  localStorage.setItem("mat_userId", result.user_id);
  localStorage.setItem("mat_displayName", result.display_name);
  localStorage.setItem("mat_sessionId", state.sessionId);
  sessionIdEl.textContent = state.sessionId;
  chatArea.innerHTML = "";
  renderSessionFilesTree([]);
  clearCurrentUploads();
  agentGraph.reset();
  planGraph.reset();
  hidePlanGraph();
  renderUserDisplay();
  hideLoginModal();
  applyStoredPanelHeights();
  applyStoredColWidths();
  applyFilesColState(isFilesColOpen());
  syncColResizerVisibility();
  loadSessions();
}

async function applyLogin(displayName, password = null) {
  loginError.textContent = "";
  let result;
  try {
    const resp = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: displayName, password }),
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      loginError.textContent = body.detail || `Login failed (${resp.status})`;
      return;
    }
    result = body;
  } catch (err) {
    loginError.textContent = `Login failed: ${err.message}`;
    return;
  }
  _applySession(result);
}

async function applyRegister(displayName, password, confirm) {
  regError.textContent = "";
  if (password !== confirm) {
    regError.textContent = "Passwords do not match.";
    return;
  }
  let result;
  try {
    const resp = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: displayName, password }),
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      regError.textContent = body.detail || `Registration failed (${resp.status})`;
      return;
    }
    result = body;
  } catch (err) {
    regError.textContent = `Registration failed: ${err.message}`;
    return;
  }
  _applySession(result);
}

loginSubmit.addEventListener("click", () => {
  const name = loginInput.value.trim();
  if (name) applyLogin(name, loginPassword.value || null);
});

loginInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loginPassword.focus();
});

loginPassword.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const name = loginInput.value.trim();
    if (name) applyLogin(name, loginPassword.value || null);
  }
});

regSubmit.addEventListener("click", () => {
  const name = regInput.value.trim();
  if (name) applyRegister(name, regPassword.value, regConfirm.value);
});

regInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") regPassword.focus();
});

regPassword.addEventListener("keydown", (e) => {
  if (e.key === "Enter") regConfirm.focus();
});

regConfirm.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const name = regInput.value.trim();
    if (name) applyRegister(name, regPassword.value, regConfirm.value);
  }
});

switchToRegister.addEventListener("click", () => showRegisterModal());
switchToLogin.addEventListener("click", () => showLoginModal());

editUserBtn.addEventListener("click", () => showLoginModal());
logoutBtn.addEventListener("click", () => logout());
settingsLogoutBtn.addEventListener("click", () => logout());

const savePasswordBtn = document.getElementById("settings-save-password-btn");
const passwordMsg = document.getElementById("settings-password-msg");

async function savePassword() {
  const oldPw = document.getElementById("settings-current-password").value || null;
  const newPw = document.getElementById("settings-new-password").value;
  const confirmPw = document.getElementById("settings-confirm-password").value;
  passwordMsg.style.color = "#f87171";
  if (!newPw) { passwordMsg.textContent = "New password cannot be empty."; return; }
  if (newPw !== confirmPw) { passwordMsg.textContent = "Passwords do not match."; return; }
  try {
    const res = await fetch("/api/auth/set-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: state.userId, old_password: oldPw, new_password: newPw }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      passwordMsg.textContent = data.detail || "Failed to update password.";
      return;
    }
    passwordMsg.style.color = "#4ade80";
    passwordMsg.textContent = "Password updated.";
    document.getElementById("settings-current-password").value = "";
    document.getElementById("settings-new-password").value = "";
    document.getElementById("settings-confirm-password").value = "";
    setTimeout(() => { passwordMsg.textContent = ""; }, 3000);
  } catch (e) {
    passwordMsg.textContent = "Network error.";
  }
}

savePasswordBtn.addEventListener("click", savePassword);

// On load: detect legacy localStorage (display name instead of UUID) and migrate,
// or proceed normally if already a valid identity.
(async () => {
  const storedId = localStorage.getItem("mat_userId") || "";
  if (!storedId) {
    showLoginModal();
  } else if (!_isValidIdentity(storedId)) {
    // Legacy: localStorage contains a raw display name (non-"user"). Show login modal.
    showLoginModal();
  } else {
    sessionIdEl.textContent = state.sessionId;
    await refreshAccess();
    renderUserDisplay();
    await loadSessions();
    if (localStorage.getItem("mat_sessionId")) {
      state.sessionReady = true;
      await loadSession(state.sessionId);
      agentGraph.startPolling(state.sessionId);
      planGraph.startPolling(state.sessionId);
    }
  }
})();

// ---------------------------------------------------------------------------
// Session list management
// ---------------------------------------------------------------------------

async function loadSessions() {
  if (!state.userId) return;
  try {
    const resp = state.isAdmin
      ? await fetch(`/api/admin/sessions?user_id=${encodeURIComponent(state.userId)}`)
      : await fetch(`/api/users/${encodeURIComponent(state.userId)}/sessions`);
    if (!resp.ok) return;
    const sessions = await resp.json();
    renderSessionList(sessions);
  } catch (_) {
    // silently ignore — server may not be running yet
  }
}

function renderSessionList(sessions) {
  sessionListEl.innerHTML = "";
  if (!Array.isArray(sessions) || !sessions.length) {
    sessionListEl.innerHTML = '<li class="empty">No sessions yet</li>';
    return;
  }
  sessions
    .slice()
    .sort((a, b) => (b.lastUpdateTime || 0) - (a.lastUpdateTime || 0))
    .forEach((s) => {
      const li = document.createElement("li");
      const owner = s.userId || state.userId;
      const isActive = s.id === state.sessionId && owner === state.activeSessionUserId;
      li.className = "session-item" + (isActive ? " active" : "");
      li.dataset.owner = owner;

      const content = document.createElement("div");
      content.className = "session-item-content";
      content.textContent = state.isAdmin ? `${owner} / ${s.id}` : s.id;
      li.appendChild(content);

      const delBtn = document.createElement("button");
      delBtn.className = "session-item-delete";
      delBtn.textContent = "×";
      delBtn.title = "Delete session";
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteSession(s.id);
      });
      li.appendChild(delBtn);

      li.title = state.isAdmin ? `${owner} / ${s.id}` : s.id;
      li.addEventListener("click", () => switchSession(s.id, owner));
      sessionListEl.appendChild(li);
    });
}

async function switchSession(sessionId, owner = state.userId) {
  state.sessionId = sessionId;
  state.activeSessionUserId = owner;
  state.sessionReady = true;
  localStorage.setItem("mat_sessionId", sessionId);
  sessionIdEl.textContent = sessionId;
  renderSessionFilesTree([]);
  clearCurrentUploads();
  agentGraph.reset();
  planGraph.reset();
  hidePlanGraph();
  await loadSession(sessionId);
  await loadSessions();
  agentGraph.startPolling(sessionId);
  planGraph.startPolling(sessionId);
}

// ---------------------------------------------------------------------------
// Confirm dialog & session delete
// ---------------------------------------------------------------------------

function showConfirmDialog(message) {
  const existing = document.querySelector(".confirm-overlay");
  if (existing) existing.remove();

  return new Promise((resolve) => {
    let settled = false;
    const done = (result) => { if (settled) return; settled = true; overlay.remove(); resolve(result); };

    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    const msg = document.createElement("p");
    msg.className = "confirm-message";
    msg.innerHTML = message;

    const actions = document.createElement("div");
    actions.className = "confirm-actions";
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "confirm-cancel";
    cancelBtn.textContent = "Cancel";
    cancelBtn.onclick = () => done(false);
    const okBtn = document.createElement("button");
    okBtn.className = "confirm-ok";
    okBtn.textContent = "Delete";
    okBtn.onclick = () => done(true);
    actions.append(cancelBtn, okBtn);

    const card = document.createElement("div");
    card.className = "confirm-card";
    card.append(msg, actions);
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    overlay.addEventListener("click", (e) => { if (e.target === overlay) done(false); });
    overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") done(false); });
    okBtn.focus();
  });
}

async function deleteSession(sessionId) {
  if (state.isSending) return;
  if (!await showConfirmDialog(`Delete session ${sessionId}? This cannot be undone.`)) return;
  try {
    const resp = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    if (!resp.ok) return;
    if (sessionId === state.sessionId) {
      state.sessionId = `session-${Math.floor(Date.now() / 1000)}`;
      state.activeSessionUserId = state.userId;
      state.sessionReady = false;
      localStorage.setItem("mat_sessionId", state.sessionId);
      sessionIdEl.textContent = state.sessionId;
      chatArea.innerHTML = "";
      renderSessionFilesTree([]);
      clearCurrentUploads();
      agentGraph.reset();
      planGraph.reset();
      hidePlanGraph();
    }
    await loadSessions();
  } catch (_) {
    // silently ignore
  }
}

refreshSessionsBtn.addEventListener("click", (e) => { e.stopPropagation(); loadSessions(); });

document.getElementById("refresh-files").addEventListener("click", (e) => { e.stopPropagation(); refreshSessionFiles(); });

// ---------------------------------------------------------------------------
// File path → API URL conversion
// ---------------------------------------------------------------------------

function pathToApiUrl(path) {
  return `/api/workspace/files?path=${encodeURIComponent(path)}`;
}

// ---------------------------------------------------------------------------
// Chat helpers
// ---------------------------------------------------------------------------

const AGENT_AVATAR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="rgba(125,211,252,0.9)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="8" width="18" height="11" rx="2"/>
  <path d="M8 8V6a4 4 0 0 1 8 0v2"/>
  <circle cx="9" cy="14" r="1" fill="rgba(125,211,252,0.9)" stroke="none"/>
  <circle cx="15" cy="14" r="1" fill="rgba(125,211,252,0.9)" stroke="none"/>
  <path d="M7 19v2M17 19v2"/>
</svg>`;

const USER_AVATAR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="rgba(168,85,247,0.9)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="8" r="4"/>
  <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
</svg>`;

function getUserAvatar() {
  return localStorage.getItem("user-avatar-url") || null;
}

function setUserAvatar(dataUrl) {
  localStorage.setItem("user-avatar-url", dataUrl);
  document.querySelectorAll(".user-avatar").forEach(applyUserAvatarToEl);
}

function applyUserAvatarToEl(el) {
  const url = getUserAvatar();
  el.innerHTML = url ? `<img src="${url}" alt="User">` : USER_AVATAR_SVG;
}

function createAgentAvatarEl() {
  const el = document.createElement("div");
  el.className = "message-avatar agent-avatar";
  el.innerHTML = AGENT_AVATAR_SVG;
  return el;
}

function createUserAvatarEl() {
  const el = document.createElement("div");
  el.className = "message-avatar user-avatar";
  applyUserAvatarToEl(el);
  return el;
}

function scrollToBottom() {
  chatArea.scrollTop = chatArea.scrollHeight;
}

function addMessage(role, content) {
  const div = document.createElement("div");
  div.className = `message ${role}-message`;

  const avatar = role === "agent" ? createAgentAvatarEl() : createUserAvatarEl();
  div.appendChild(avatar);

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  const inner = document.createElement("div");
  inner.className = "markdown-content";
  inner.innerHTML = marked.parse(content || "");
  bubble.appendChild(inner);
  div.appendChild(bubble);

  chatArea.appendChild(div);
  scrollToBottom();
  return div;
}

function getFunctionCall(part) {
  return part?.functionCall || part?.function_call || null;
}

function getFunctionResponse(part) {
  return part?.functionResponse || part?.function_response || null;
}

function getPlotPaths(response) {
  const paths = [];
  const add = (path) => {
    if (typeof path === "string" && path && !paths.includes(path)) paths.push(path);
  };
  add(response?.plot_path);
  if (Array.isArray(response?.plot_paths)) {
    response.plot_paths.forEach(add);
  }
  return paths;
}

// Render a typed timeline array into a container element, mirroring
// Streamlit's render_stream_timeline: thoughts and tool calls go into
// collapsible <details> blocks; text parts render as markdown;
// plot_path responses render as inline images.
function renderTimeline(container, timeline, shownPlotPaths = null) {
  container.innerHTML = "";
  const containerPlotPaths = container._plotPaths || new Set();
  const visiblePlotPaths = new Set();
  for (const item of timeline) {
    if (item.type === "thought") {
      const details = document.createElement("details");
      details.className = "timeline-thought";
      const summary = document.createElement("summary");
      summary.textContent = "🤔 Thinking...";
      details.appendChild(summary);
      const body = document.createElement("div");
      body.className = "markdown-content";
      body.innerHTML = marked.parse(item.text || "");
      details.appendChild(body);
      container.appendChild(details);
    } else if (item.type === "function_call") {
      const details = document.createElement("details");
      details.className = "timeline-function-call";
      const summary = document.createElement("summary");
      summary.textContent = `🔧 ${item.name}`;
      details.appendChild(summary);
      const pre = document.createElement("pre");
      pre.className = "json-block";
      pre.textContent = JSON.stringify(item.args, null, 2);
      details.appendChild(pre);
      container.appendChild(details);
    } else if (item.type === "function_response") {
      const details = document.createElement("details");
      details.className = "timeline-function-response";
      const summary = document.createElement("summary");
      summary.textContent = `📥 ${item.name}`;
      details.appendChild(summary);
      const pre = document.createElement("pre");
      pre.className = "json-block";
      pre.textContent = JSON.stringify(item.response, null, 2);
      details.appendChild(pre);
      container.appendChild(details);
      for (const plotPath of getPlotPaths(item.response)) {
        if (
          visiblePlotPaths.has(plotPath) ||
          (shownPlotPaths && shownPlotPaths.has(plotPath) && !containerPlotPaths.has(plotPath))
        ) {
          continue;
        }
        visiblePlotPaths.add(plotPath);
        const img = document.createElement("img");
        img.src = pathToApiUrl(plotPath);
        img.className = "timeline-image";
        img.alt = plotPath.split("/").pop();
        container.appendChild(img);
      }
      // Render inline "View Structure" button for structure tool responses
      if (item.response && item.response.structure_path) {
        const btn = document.createElement("button");
        btn.className = "ghost structure-view-btn";
        btn.textContent = `🔬 View: ${item.response.structure_path.split("/").pop()}`;
        btn.addEventListener("click", () => openViewer({
          path: item.response.structure_path,
          url: pathToApiUrl(item.response.structure_path),
        }));
        container.appendChild(btn);
      }
    } else if (item.type === "text") {
      const div = document.createElement("div");
      div.className = "markdown-content";
      div.innerHTML = marked.parse(item.text || "");
      container.appendChild(div);
    }
  }
  container._plotPaths = visiblePlotPaths;
  visiblePlotPaths.forEach((path) => shownPlotPaths?.add(path));
  scrollToBottom();
}

// Create an agent message div with an inner timeline container, append to
// chatArea, and return the inner container for live updates.
function addAgentTimelineMessage(timeline, shownPlotPaths = null) {
  const outer = document.createElement("div");
  outer.className = "message agent-message";
  outer.appendChild(createAgentAvatarEl());
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  const inner = document.createElement("div");
  inner.className = "timeline-container";
  bubble.appendChild(inner);
  outer.appendChild(bubble);
  chatArea.appendChild(outer);
  renderTimeline(inner, timeline, shownPlotPaths);
  return inner;
}

// Classify a file path as "structure", "image", or "artifact" by extension/name.
const STRUCTURE_EXTS = new Set([".cif", ".xyz", ".extxyz", ".vasp"]);
const STRUCTURE_NAMES = new Set(["poscar", "contcar"]);
const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg"]);

function classifyPath(p) {
  const name = p.split("/").pop();
  const dotIdx = name.lastIndexOf(".");
  const ext = dotIdx >= 0 ? name.slice(dotIdx).toLowerCase() : "";
  if (STRUCTURE_EXTS.has(ext) || STRUCTURE_NAMES.has(name.toLowerCase())) return "structure";
  if (IMAGE_EXTS.has(ext)) return "image";
  return "artifact";
}

// ---------------------------------------------------------------------------
// Session files tree
// ---------------------------------------------------------------------------

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function _createFileItem(f) {
  const li = document.createElement("li");
  li.className = "tree-file";

  const nameSpan = document.createElement("span");
  nameSpan.className = "tree-filename";
  nameSpan.textContent = f.relname;
  li.appendChild(nameSpan);

  const sizeSpan = document.createElement("span");
  sizeSpan.className = "tree-filesize";
  sizeSpan.textContent = formatFileSize(f.size);
  li.appendChild(sizeSpan);

  const actions = document.createElement("div");
  actions.className = "tree-actions";

  const dlLink = document.createElement("a");
  dlLink.href = `/api/workspace/files?path=${encodeURIComponent(f.path)}`;
  dlLink.download = f.relname;
  dlLink.className = "tree-btn";
  dlLink.title = "Download";
  dlLink.textContent = "↓";
  actions.appendChild(dlLink);

  if (classifyPath(f.path) === "structure") {
    const viewBtn = document.createElement("button");
    viewBtn.className = "tree-btn";
    viewBtn.title = "View 3D";
    viewBtn.textContent = "⬡";
    viewBtn.addEventListener("click", () =>
      openViewer({ path: f.path, name: f.relname, url: `/api/workspace/files?path=${encodeURIComponent(f.path)}` })
    );
    actions.appendChild(viewBtn);
  }

  li.appendChild(actions);
  return li;
}

function _buildFileTree(files, prefix) {
  const root = { children: {}, files: [] };
  for (const file of files) {
    const rel = file.path.slice(prefix.length).replace(/^\//, "");
    const parts = rel.split("/");
    const filename = parts[parts.length - 1];
    const dirs = parts.slice(0, -1);
    let node = root;
    for (const dir of dirs) {
      if (!node.children[dir]) {
        node.children[dir] = { name: dir, children: {}, files: [] };
      }
      node = node.children[dir];
    }
    node.files.push({ ...file, relname: filename, relpath: rel });
  }
  return root;
}

function _renderTreeNode(node, container, depth) {
  const sortedDirs = Object.keys(node.children).sort();
  const sortedFiles = node.files.slice().sort((a, b) => a.relname.localeCompare(b.relname));

  for (const dirName of sortedDirs) {
    const child = node.children[dirName];
    const li = document.createElement("li");
    li.className = "tree-dir-node";

    const details = document.createElement("details");

    const summary = document.createElement("summary");
    summary.className = "tree-dir-summary";
    summary.textContent = dirName + "/";
    details.appendChild(summary);

    const childUl = document.createElement("ul");
    childUl.className = "tree-dir-children";
    _renderTreeNode(child, childUl, depth + 1);
    details.appendChild(childUl);

    li.appendChild(details);
    container.appendChild(li);
  }

  for (const f of sortedFiles) {
    container.appendChild(_createFileItem(f));
  }
}

function renderSessionFilesTree(files) {
  const ul = document.getElementById("session-files-tree");
  ul.innerHTML = "";
  if (!files.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "No files yet";
    ul.appendChild(li);
    return;
  }

  let prefix = "";
  const sidIdx = files[0].path.indexOf(state.sessionId);
  if (sidIdx >= 0) {
    prefix = files[0].path.slice(0, sidIdx + state.sessionId.length);
  } else {
    let common = files[0].path;
    for (const f of files) {
      let i = 0;
      while (i < common.length && i < f.path.length && common[i] === f.path[i]) i++;
      common = common.slice(0, i);
    }
    prefix = common.slice(0, common.lastIndexOf("/") + 1);
  }

  const root = _buildFileTree(files, prefix);
  _renderTreeNode(root, ul, 0);
}

async function refreshSessionFiles() {
  if (!state.sessionId || !state.sessionReady) return;
  try {
    const resp = await fetch(`/api/sessions/${state.sessionId}/files`);
    if (!resp.ok) return;
    const data = await resp.json();
    renderSessionFilesTree(data.files || []);
  } catch (_) {}
}

function setUploadStatus(message, tone = "idle") {
  if (!uploadStatus) return;
  uploadStatus.textContent = message || "";
  uploadStatus.className = `upload-status upload-status-${tone}`;
}

function renderCurrentUploadChips() {
  if (!uploadStatus) return;
  uploadStatus.innerHTML = "";
  uploadStatus.className = "upload-status upload-file-list";
  if (!state.currentUploads.length) return;

  state.currentUploads.forEach((file) => {
    const chip = document.createElement("span");
    chip.className = "upload-file-chip";

    const name = document.createElement("span");
    name.className = "upload-file-name";
    name.textContent = file.name;
    name.title = file.path;
    chip.appendChild(name);

    const removeBtn = document.createElement("button");
    removeBtn.className = "upload-file-remove";
    removeBtn.type = "button";
    removeBtn.title = "Delete uploaded file";
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => deleteUploadedFile(file));
    chip.appendChild(removeBtn);

    uploadStatus.appendChild(chip);
  });
}

function clearCurrentUploads() {
  state.currentUploads = [];
  renderCurrentUploadChips();
}

function mergeUploadedFiles(existingFiles, newFiles) {
  const merged = [...existingFiles];
  const seenPaths = new Set(existingFiles.map((file) => file?.path).filter(Boolean));

  newFiles.forEach((file) => {
    const path = file?.path;
    if (path && seenPaths.has(path)) return;
    if (path) seenPaths.add(path);
    merged.push(file);
  });

  return merged;
}

function sessionRelativeUploadPath(file) {
  const normalized = String(file?.path || "").replaceAll("\\", "/");
  const marker = `/${state.sessionId}/`;
  const markerIdx = normalized.indexOf(marker);
  if (markerIdx >= 0) return normalized.slice(markerIdx + marker.length);
  return file?.name ? `uploads/${file.name}` : normalized;
}

function messageWithUploadContext(message, uploads) {
  if (!uploads.length) return message;
  const fileLines = uploads.map((file) => {
    const relPath = sessionRelativeUploadPath(file);
    return `- ${file.name}: ${relPath} (absolute path: ${file.path})`;
  });
  return [
    message,
    "",
    "The user uploaded the following file(s) for this message. They are saved in the current session workspace. Use these paths when inspecting or processing the files:",
    ...fileLines,
  ].join("\n");
}

function formatUploadNames(uploadNames) {
  if (!uploadNames.length) return "";
  return `Attached: ${uploadNames.map((name) => `\`${name}\``).join(", ")}`;
}

function messageWithUploadNames(message, uploads) {
  const uploadNames = uploads.map((file) => file.name).filter(Boolean);
  const suffix = formatUploadNames(uploadNames);
  return suffix ? `${message}\n\n${suffix}` : message;
}

function displayMessageFromStoredUserText(message) {
  const marker = "\n\nThe user uploaded the following file(s) for this message.";
  const rawMessage = String(message || "");
  const markerIdx = rawMessage.indexOf(marker);
  if (markerIdx < 0) return rawMessage;

  const visibleMessage = rawMessage.slice(0, markerIdx);
  const hiddenContext = rawMessage.slice(markerIdx);
  const uploadNames = hiddenContext
    .split("\n")
    .map((line) => line.match(/^-\s+([^:]+):/)?.[1]?.trim())
    .filter(Boolean);
  const suffix = formatUploadNames(uploadNames);
  return suffix ? `${visibleMessage}\n\n${suffix}` : visibleMessage;
}

async function deleteUploadedFile(file) {
  if (!file?.path || !state.sessionId) return;
  try {
    const resp = await fetch(
      `/api/sessions/${encodeURIComponent(state.sessionId)}/files?path=${encodeURIComponent(file.path)}`,
      { method: "DELETE" }
    );
    if (!resp.ok) {
      const detail = await resp.text();
      throw new Error(detail || `HTTP ${resp.status}`);
    }
    state.currentUploads = state.currentUploads.filter((item) => item.path !== file.path);
    renderCurrentUploadChips();
    await refreshSessionFiles();
  } catch (err) {
    setUploadStatus(`Delete failed: ${err.message || err}`, "error");
  }
}

async function uploadFilesToSession(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  if (!state.userId) { showLoginModal(); return; }
  if (state.activeSessionUserId && state.activeSessionUserId !== state.userId) {
    addMessage("agent", `Admin view is read-only for ${state.activeSessionUserId}'s session.`);
    return;
  }

  if (!state.sessionReady) await createSession();
  if (!state.sessionReady) {
    setUploadStatus("Could not create session.", "error");
    return;
  }

  if (fileUploadBtn) fileUploadBtn.disabled = true;
  const uploaded = [];
  try {
    for (const file of files) {
      setUploadStatus(`Uploading ${file.name}...`, "busy");
      const formData = new FormData();
      formData.append("file", file);
      const resp = await fetch(`/api/sessions/${encodeURIComponent(state.sessionId)}/files`, {
        method: "POST",
        body: formData,
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || `HTTP ${resp.status}`);
      }
      uploaded.push(await resp.json());
    }

    await refreshSessionFiles();
    state.currentUploads = mergeUploadedFiles(state.currentUploads, uploaded);
    renderCurrentUploadChips();
  } catch (err) {
    setUploadStatus(`Upload failed: ${err.message || err}`, "error");
  } finally {
    if (fileUploadBtn) fileUploadBtn.disabled = false;
    fileUploadInput.value = "";
  }
}

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

async function createSession() {
  state.activeSessionUserId = state.userId;
  const url = `/apps/${APP_NAME}/users/${state.userId}/sessions/${state.sessionId}`;
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        state.agentMode === "normal"
          ? {}
          : { agent_mode: state.agentMode, ...(state.agentMode === "bench" ? { benchmark_mode: true } : {}) }
      ),
    });
    if (!resp.ok) {
      console.error(`Failed to create session: HTTP ${resp.status}`, await resp.text());
      return;
    }
    state.sessionReady = true;
    await startKnowledgeReview();
    await loadSessions();
  } catch (err) {
    console.error("Failed to create session:", err);
  }
}

function renderKnowledgeReviewStatus(review) {
  const status = review?.status || "idle";
  const running = status === "running";
  const progress = review?.progress || {};
  const phase = review?.phase || "memory";
  const completed = progress.completed || 0;
  const total = progress.total || 0;
  const results = Array.isArray(review?.results) ? review.results : [];
  const errors = Array.isArray(review?.errors) ? review.errors : [];
  if (knowledgeReviewBanner) {
    knowledgeReviewBanner.disabled = running;
    knowledgeReviewBanner.className = `knowledge-review-banner status-${status}`;
    const detail = review?.summary || errors[0];
    knowledgeReviewBanner.title = detail
      ? `${detail}${running ? "" : " Click to review memory and graph nodes."}`
      : running
        ? "Knowledge review is running"
        : "Click to review memory and graph nodes";
  }
  knowledgeReviewSpinner?.classList.toggle("hidden", !running);
  if (knowledgeReviewText) {
    if (running) {
      const phaseLabel = phase === "graph" ? "graph nodes" : "memory";
      knowledgeReviewText.textContent = total
        ? `Reviewing ${phaseLabel}: ${completed}/${total} (${progress.percent || 0}%)`
        : `Starting ${phaseLabel} review`;
    } else if (status === "failed") {
      knowledgeReviewText.textContent = `Review failed: ${errors[0] || "unknown error"} · click to retry`;
    } else if (status === "completed" || status === "completed_with_errors") {
      const memoryCount = results.filter((item) => item.phase === "memory").length;
      const graphCount = results.filter((item) => item.phase === "graph").length;
      const warning = errors.length ? `, ${errors.length} errors` : "";
      knowledgeReviewText.textContent = `Review complete: ${memoryCount} memory, ${graphCount} graph actions${warning} · click to run again`;
    } else {
      knowledgeReviewText.textContent = "Review memory and graph · click to start";
    }
  }
  if (!running && knowledgeReviewPoll) {
    clearInterval(knowledgeReviewPoll);
    knowledgeReviewPoll = null;
  }
}

async function refreshKnowledgeReviewStatus() {
  try {
    const resp = await fetch("/api/knowledge-review/status");
    if (!resp.ok) return;
    const review = await resp.json();
    renderKnowledgeReviewStatus(review);
    if (review.status === "running" && !knowledgeReviewPoll) {
      knowledgeReviewPoll = setInterval(refreshKnowledgeReviewStatus, 2000);
    }
  } catch (_) {
    // The banner is informational; session work should continue if polling fails.
  }
}

async function startKnowledgeReview() {
  renderKnowledgeReviewStatus({
    status: "running",
    phase: "memory",
    message: "Starting Know-Do Graph review.",
  });
  try {
    const resp = await fetch("/api/knowledge-review/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    const review = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      renderKnowledgeReviewStatus({
        status: "failed",
        errors: [review.detail || `HTTP ${resp.status}`],
      });
      return;
    }
    renderKnowledgeReviewStatus(review);
    if (!knowledgeReviewPoll) {
      knowledgeReviewPoll = setInterval(refreshKnowledgeReviewStatus, 2000);
    }
  } catch (_) {
    renderKnowledgeReviewStatus({
      status: "failed",
      errors: ["Could not reach the review service"],
    });
  }
}

knowledgeReviewBanner?.addEventListener("click", () => {
  if (!knowledgeReviewBanner.disabled) startKnowledgeReview();
});

async function patchSessionAgentMode(mode) {
  if (!state.sessionReady || !state.sessionId) return;
  const url = `/apps/${APP_NAME}/users/${encodeURIComponent(state.userId)}/sessions/${encodeURIComponent(state.sessionId)}`;
  try {
    const delta = { agent_mode: mode, benchmark_mode: mode === "bench" };
    const resp = await fetch(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state_delta: delta }),
    });
    if (!resp.ok) console.error(`Failed to patch agent mode: HTTP ${resp.status}`);
  } catch (err) {
    console.error("Failed to patch agent mode:", err);
  }
}

// Reload full session history from the ADK server and re-render the chat,
// mirroring Streamlit's load_session() called after send_message_sse().
async function loadSession(sessionId) {
  try {
    const owner = state.activeSessionUserId || state.userId;
    const resp = await fetch(
      `/api/users/${encodeURIComponent(owner)}/sessions/${encodeURIComponent(sessionId)}`,
      { headers: { "Content-Type": "application/json" } }
    );
    if (!resp.ok) return;
    const sessionData = await resp.json();
    const events = sessionData.events || [];
    let shownPlotPaths = new Set();

    // Rebuild chat from server-canonical state
    chatArea.innerHTML = "";

    // First pass: collect all functionResponses keyed by ID for cross-event matching
    const frById = {};
    for (const event of events) {
      for (const p of (event.content?.parts || [])) {
        const fr = getFunctionResponse(p);
        if (fr?.id) {
          frById[fr.id] = fr;
        }
      }
    }

    for (const event of events) {
      const role = event.author === "user" ? "user" : "agent";
      const parts = event.content?.parts || [];

      if (role === "user") {
        const text = displayMessageFromStoredUserText(parts.map((p) => p.text || "").join(""));
        if (text) addMessage("user", text);
        shownPlotPaths = new Set();
        continue;
      }

      const timeline = [];
      let accText = "";

      for (const p of parts) {
        if (p.thought) {
          timeline.push({ type: "thought", text: p.text || "" });
        } else if (getFunctionCall(p)) {
          const fc = getFunctionCall(p);
          const matchedFr = frById[fc.id];
          timeline.push({
            type: "function_call",
            id: fc.id,
            name: fc.name || "Unknown",
            args: fc.args || {},
          });
          if (matchedFr) {
            timeline.push({
              type: "function_response",
              id: matchedFr.id,
              name: matchedFr.name || "Unknown",
              response: matchedFr.response || {},
            });
          }
        } else if (getFunctionResponse(p)) {
          const fr = getFunctionResponse(p);
          const alreadyMatched = timeline.some(
            (t) => t.type === "function_response" && t.id === fr.id
          );
          if (!alreadyMatched) {
            timeline.push({
              type: "function_response",
              id: fr.id,
              name: fr.name || "Unknown",
              response: fr.response || {},
            });
          }
        } else if (p.text && !p.thought) {
          accText += p.text;
          const last = timeline[timeline.length - 1];
          if (last?.type === "text") {
            last.text = accText;
          } else {
            timeline.push({ type: "text", text: accText });
          }
        }
      }

      if (timeline.length > 0) {
        addAgentTimelineMessage(timeline, shownPlotPaths);
      }
    }

    await refreshSessionFiles();
  } catch (err) {
    console.error("Failed to load session:", err);
  }
}

// ---------------------------------------------------------------------------
// Streaming deduplication helpers (ported from streamlit_app.py)
// ---------------------------------------------------------------------------

function mergeReplayedText(current, incoming) {
  if (!incoming) return current;
  if (!current) return incoming;
  if (incoming.startsWith(current)) return incoming;
  if (current.endsWith(incoming)) return current;
  const maxOverlap = Math.min(current.length, incoming.length);
  for (let overlap = maxOverlap; overlap > 0; overlap--) {
    if (current.endsWith(incoming.slice(0, overlap))) {
      return current + incoming.slice(overlap);
    }
  }
  return current + incoming;
}

function compactRepeatedPrefixSnapshots(text) {
  if (!text) return text;
  let compacted = text;
  let changed = true;
  while (changed) {
    changed = false;
    const maxPrefix = Math.floor(compacted.length / 2);
    for (let size = maxPrefix; size > 3; size--) {
      const prefix = compacted.slice(0, size);
      const rest = compacted.slice(size);
      if (rest.startsWith(prefix)) {
        compacted = rest;
        changed = true;
        break;
      }
    }
  }
  return compacted;
}

function upsertTimelineThought(timeline, text) {
  if (!text) return;
  const compacted = compactRepeatedPrefixSnapshots(text);
  const last = timeline[timeline.length - 1];
  if (last?.type === "thought") {
    last.text = compactRepeatedPrefixSnapshots(mergeReplayedText(last.text || "", compacted));
    return;
  }
  timeline.push({ type: "thought", text: compacted });
}

function upsertTimelineText(timeline, text) {
  for (let i = timeline.length - 1; i >= 0; i--) {
    if (timeline[i].type === "text") timeline.splice(i, 1);
  }
  if (text) timeline.push({ type: "text", text });
}

function upsertTimelineEvent(timeline, event) {
  const { id: eventId, type: eventType } = event;
  if (eventId) {
    for (let i = 0; i < timeline.length; i++) {
      if (timeline[i].type === eventType && timeline[i].id === eventId) {
        timeline[i] = event;
        return;
      }
    }
  }
  const last = timeline[timeline.length - 1];
  if (last && JSON.stringify(last) === JSON.stringify(event)) return;
  timeline.push(event);
}

// ---------------------------------------------------------------------------
// Message sending + SSE streaming
// ---------------------------------------------------------------------------

function setSendingState(isSending, controller = null) {
  state.isSending = isSending;
  state.sendController = controller;
  if (!sendBtn) return;
  sendBtn.textContent = isSending ? "■" : "➜";
  sendBtn.title = isSending ? "Stop" : "Send";
  sendBtn.classList.toggle("is-stopping", isSending);
}

function stopCurrentMessage() {
  if (!state.isSending || !state.sendController) return;
  fetch(`/api/sessions/${state.sessionId}/cancel`, { method: "POST" }).catch(() => {});
  state.sendController.abort();
  pollCancellationConfirmed(state.sessionId);
}

function pollCancellationConfirmed(sessionId, attempts = 0) {
  const MAX_ATTEMPTS = 20;  // 20 × 2s = 40s timeout
  const INTERVAL_MS = 2000;

  if (attempts >= MAX_ATTEMPTS) {
    addMessage("agent", "⚠️ Stop requested but execution may still be running in the background.");
    return;
  }

  setTimeout(async () => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}/cancel`);
      const data = await res.json();
      if (!data.cancellation_requested) {
        addMessage("agent", "✓ Execution stopped.");
        return;
      }
    } catch (_) { /* ignore transient network errors */ }
    pollCancellationConfirmed(sessionId, attempts + 1);
  }, INTERVAL_MS);
}

async function sendMessage(message) {
  if (!message.trim()) return;
  if (state.isSending) return;
  if (!state.userId) { showLoginModal(); return; }
  if (state.activeSessionUserId && state.activeSessionUserId !== state.userId) {
    addMessage("agent", `Admin view is read-only for ${state.activeSessionUserId}'s session.`);
    return;
  }

  const uploadsForMessage = state.currentUploads.slice();
  addMessage("user", messageWithUploadNames(message, uploadsForMessage));
  const backendMessage = messageWithUploadContext(message, uploadsForMessage);
  textInput.value = "";
  clearCurrentUploads();
  autoResizeTextInput();

  if (!state.sessionReady) await createSession();
  agentGraph.reset();
  planGraph.reset();
  agentGraph.startPolling(state.sessionId);
  planGraph.startPolling(state.sessionId);

  const controller = new AbortController();
  setSendingState(true, controller);
  const payload = {
    app_name: APP_NAME,
    user_id: state.userId,
    session_id: state.sessionId,
    new_message: {
      role: "user",
      parts: [{ text: backendMessage }],
    },
  };

  const timeline = [];
  let timelineContainer = null;
  let accText = "";
  const shownPlotPaths = new Set();

  try {
    const resp = await fetch("/run_sse", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      const lines = chunk.split("\n");
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const dataStr = line.slice(6);
        if (dataStr === "[DONE]") continue;
        try {
          const evt = JSON.parse(dataStr);
          const parts = evt?.content?.parts || [];
          for (const p of parts) {
            if (p.thought) {
              upsertTimelineThought(timeline, p.text || "");
            } else if (p.functionCall) {
              const fc = p.functionCall;
              upsertTimelineEvent(timeline, {
                type: "function_call",
                id: fc.id,
                name: fc.name || "Unknown",
                args: fc.args || {},
              });
            } else if (p.functionResponse) {
              const fr = p.functionResponse;
              upsertTimelineEvent(timeline, {
                type: "function_response",
                id: fr.id,
                name: fr.name || "Unknown",
                response: fr.response || {},
              });
            } else if (p.text) {
              accText = mergeReplayedText(accText, p.text);
              upsertTimelineText(timeline, compactRepeatedPrefixSnapshots(accText));
            }

            if (timeline.length > 0 && !timelineContainer) {
              timelineContainer = addAgentTimelineMessage(timeline, shownPlotPaths);
            } else if (timelineContainer) {
              renderTimeline(timelineContainer, timeline, shownPlotPaths);
            }
          }
        } catch (_) {
          // ignore malformed lines
        }
      }
    }
  } catch (err) {
    if (err?.name === "AbortError") {
      addMessage("agent", "Stopping execution…");
    } else {
      addMessage("agent", `Backend error: ${err}`);
    }
  } finally {
    await agentGraph._poll(state.sessionId);
    agentGraph.stopPolling();
    await planGraph._poll(state.sessionId);
    planGraph.stopPolling();
    await refreshSessionFiles();
    setSendingState(false);
  }
}

// ---------------------------------------------------------------------------
// Structure viewer
// ---------------------------------------------------------------------------

async function openViewer(item) {
  graphDetail.classList.add("hidden");
  structureViewer.classList.remove("hidden");
  syncPanelResizerVisibility();
  svCanvas.innerHTML = '<div style="color:var(--muted);padding:16px;font-size:13px">Loading…</div>';
  svMeta.textContent = "";

  try {
    const resp = await fetch(`/api/structure/view?path=${encodeURIComponent(item.path)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    svCanvas.innerHTML = "";

    const viewer = $3Dmol.createViewer(svCanvas, { backgroundColor: "0x06080f" });
    state.structure3dViewer = viewer;
    viewer.addModel(data.xyz, "xyz");
    viewer.setStyle({}, { sphere: { scale: 0.3 }, stick: { radius: 0.15 } });

    if (data.periodic && data.cell) {
      const [a, b, c] = data.cell;
      const add = (u, v) => [u[0] + v[0], u[1] + v[1], u[2] + v[2]];
      const corners = [
        [0, 0, 0], a, b, c,
        add(a, b), add(a, c), add(b, c), add(add(a, b), c),
      ];
      const edges = [[0,1],[0,2],[0,3],[1,4],[1,5],[2,4],[2,6],[3,5],[3,6],[4,7],[5,7],[6,7]];
      for (const [i, j] of edges) {
        viewer.addLine({
          start: { x: corners[i][0], y: corners[i][1], z: corners[i][2] },
          end:   { x: corners[j][0], y: corners[j][1], z: corners[j][2] },
          color: "0x7dd3fc",
          linewidth: 2,
        });
      }
    }

    viewer.zoomTo();
    viewer.render();
    refreshGraphAndStructureLayout();

    svMeta.textContent =
      `${data.formula}  ·  ${data.n_atoms} atoms${data.periodic ? "  ·  periodic" : ""}`;
  } catch (err) {
    svCanvas.innerHTML =
      `<div style="color:#f87171;padding:16px;font-size:13px">Failed to load structure: ${err}</div>`;
  }
}

svClose.addEventListener("click", () => {
  structureViewer.classList.add("hidden");
  syncPanelResizerVisibility();
  state.structure3dViewer = null;
  svCanvas.innerHTML = "";
});

initPanelResizers();
initColResizers();

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------

sendBtn.addEventListener("click", () => {
  if (state.isSending) {
    stopCurrentMessage();
    return;
  }
  sendMessage(textInput.value);
});
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (state.isSending) return;
    sendMessage(textInput.value);
  }
});

if (fileUploadBtn && fileUploadInput) {
  fileUploadBtn.addEventListener("click", () => fileUploadInput.click());
  fileUploadInput.addEventListener("change", (e) => uploadFilesToSession(e.target.files));
}

// Avatar upload
const avatarUploadInput = document.getElementById("avatar-upload-input");
const avatarUploadBtn = document.getElementById("avatar-upload-btn");
if (avatarUploadBtn && avatarUploadInput) {
  applyUserAvatarToEl(avatarUploadBtn);
  avatarUploadBtn.addEventListener("click", () => avatarUploadInput.click());
  avatarUploadInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setUserAvatar(ev.target.result);
      applyUserAvatarToEl(avatarUploadBtn);
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  });
}

Array.from(document.querySelectorAll("[data-quick]"))
  .forEach((btn) => btn.addEventListener("click", () => sendMessage(btn.dataset.quick || "")));

// Agent mode selector
function updateAgentModeChip(mode) {
  if (!agentModeChip) return;
  const labels = { flash: "⚡ Flash Mode", bench: "⚡ Bench Mode" };
  const label = labels[mode];
  if (label) {
    agentModeChip.textContent = label;
    agentModeChip.dataset.mode = mode;
    agentModeChip.classList.remove("hidden");
  } else {
    agentModeChip.classList.add("hidden");
  }
}

if (modeSelector) {
  modeSelector.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.classList.toggle("mode-btn-active", btn.dataset.mode === state.agentMode);
  });
  updateAgentModeChip(state.agentMode);
  modeSelector.addEventListener("click", (e) => {
    const btn = e.target.closest(".mode-btn");
    if (!btn) return;
    const mode = btn.dataset.mode;
    state.agentMode = mode;
    localStorage.setItem(AGENT_MODE_KEY, mode);
    modeSelector.querySelectorAll(".mode-btn").forEach((b) =>
      b.classList.toggle("mode-btn-active", b.dataset.mode === mode)
    );
    updateAgentModeChip(mode);
    patchSessionAgentMode(mode);
  });
}

resetBtn.addEventListener("click", async () => {
  state.sessionId = `session-${Math.floor(Date.now() / 1000)}`;
  state.activeSessionUserId = state.userId;
  state.sessionReady = false;
  localStorage.setItem("mat_sessionId", state.sessionId);
  sessionIdEl.textContent = state.sessionId;
  chatArea.innerHTML = "";
  renderSessionFilesTree([]);
  clearCurrentUploads();
  agentGraph.reset();
  planGraph.reset();
  hidePlanGraph();
  await createSession();
});

// ---------------------------------------------------------------------------
// Settings panel
// ---------------------------------------------------------------------------

const settingsModal = document.getElementById("settings-modal");
const settingsBtn = document.getElementById("settings-btn");
const settingsClose = document.getElementById("settings-close");
const settingsSave = document.getElementById("settings-save");
const settingsStatus = document.getElementById("settings-status");
const settingsUsername = document.getElementById("settings-username");
const settingsUuid = document.getElementById("settings-uuid");
const skillsChecklist = document.getElementById("skills-checklist");
const settingsRestartBtn = document.getElementById("settings-restart-btn");

// Env config input refs
const envInputs = {
  LLM_MODEL:              () => document.getElementById("settings-llm-model"),
  LLM_API_KEY:            () => document.getElementById("settings-llm-apikey"),
  LLM_BASE_URL:           () => document.getElementById("settings-llm-baseurl"),
  EMBEDDING_MODEL:        () => document.getElementById("settings-llm-embed"),
  BOHRIUM_EMAIL:          () => document.getElementById("settings-bohr-email"),
  BOHRIUM_PASSWORD:       () => document.getElementById("settings-bohr-password"),
  BOHRIUM_PROJECT_ID:     () => document.getElementById("settings-bohr-project"),
  BOHRIUM_VASP_IMAGE:     () => document.getElementById("settings-bohr-vasp-image"),
  BOHRIUM_VASP_MACHINE:   () => document.getElementById("settings-bohr-vasp-machine"),
  BOHRIUM_DEEPMD_IMAGE:   () => document.getElementById("settings-bohr-deepmd-image"),
  BOHRIUM_DEEPMD_MACHINE: () => document.getElementById("settings-bohr-deepmd-machine"),
  DEEPMD_MODEL_PATH:      () => document.getElementById("settings-bohr-deepmd-model"),
};

function openSettingsModal() {
  settingsModal.classList.remove("hidden");
  settingsUsername.value = state.displayName || "";
  settingsUuid.value = state.userId || "";
  loadSettingsData();
}

function closeSettingsModal() {
  settingsModal.classList.add("hidden");
}

// ---- tree helpers ----------------------------------------------------------

function _buildSkillTree(skills) {
  const byName = new Map(skills.map((s) => [s.name, { ...s, children: [] }]));
  const roots = [];
  for (const s of skills) {
    const node = byName.get(s.name);
    if (s.parent && byName.has(s.parent)) {
      byName.get(s.parent).children.push(node);
    } else {
      roots.push(node);
    }
  }
  const cmp = (a, b) => {
    const ak = a.children.length > 0 ? 0 : 1;
    const bk = b.children.length > 0 ? 0 : 1;
    return ak !== bk ? ak - bk : a.name.localeCompare(b.name);
  };
  roots.sort(cmp);
  roots.forEach((r) => r.children.sort(cmp));
  return roots;
}

function _syncParent(parentCb, childWrap) {
  const childCbs = Array.from(
    childWrap.querySelectorAll(":scope > .st-item > .st-row > .skill-checkbox")
  ).filter((c) => !c.disabled);
  if (!childCbs.length) return;
  const checkedCount = childCbs.filter((c) => c.checked).length;
  if (checkedCount === childCbs.length) {
    parentCb.indeterminate = false;
    parentCb.checked = true;
  } else if (checkedCount === 0) {
    parentCb.indeterminate = false;
    parentCb.checked = false;
  } else {
    parentCb.indeterminate = true;
  }
}

function _renderSkillNode(node, extraSkills, depth) {
  const hasChildren = node.children.length > 0;
  const isBuiltIn = node.planning_enabled && !extraSkills.has(node.name);

  const item = document.createElement("div");
  item.className = "st-item";

  const row = document.createElement("div");
  row.className = "st-row";
  if (depth > 0) row.style.paddingLeft = `${depth * 18}px`;

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "st-toggle";
  toggle.innerHTML = hasChildren ? "&#9654;" : "";
  toggle.disabled = !hasChildren;
  if (!hasChildren) toggle.style.visibility = "hidden";

  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.className = "skill-checkbox";
  cb.dataset.name = node.name;
  cb.checked = node.planning_enabled;
  cb.disabled = isBuiltIn;
  if (isBuiltIn) cb.title = "Enabled by built-in category";

  const enabledCb = document.createElement("input");
  enabledCb.type = "checkbox";
  enabledCb.className = "skill-enabled-checkbox";
  enabledCb.dataset.name = node.name;
  enabledCb.checked = node.enabled !== false;
  enabledCb.title = "Enable skill for graph search";

  const nameEl = document.createElement("span");
  nameEl.className = "st-name";
  nameEl.textContent = node.name;

  if (node.is_custom) {
    const badge = document.createElement("span");
    badge.className = "skill-badge-custom";
    badge.textContent = "Custom";
    nameEl.appendChild(badge);
  }

  const descEl = document.createElement("span");
  descEl.className = "st-desc";
  descEl.textContent = node.description;

  row.append(toggle, enabledCb, cb, nameEl, descEl);

  if (node.is_custom) {
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "skill-delete-btn";
    delBtn.title = "Delete custom skill";
    delBtn.textContent = "✕";
    delBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete custom skill "${node.name}"?`)) return;
      await deleteCustomSkill(node.name);
    });
    row.appendChild(delBtn);
  }

  item.appendChild(row);

  if (hasChildren) {
    const childWrap = document.createElement("div");
    childWrap.className = "st-children st-collapsed";

    for (const child of node.children) {
      childWrap.appendChild(_renderSkillNode(child, extraSkills, depth + 1));
    }
    item.appendChild(childWrap);

    // Expand / collapse
    toggle.addEventListener("click", () => {
      const collapsed = childWrap.classList.toggle("st-collapsed");
      toggle.innerHTML = collapsed ? "&#9654;" : "&#9660;";
    });

    // Parent → children propagation
    cb.addEventListener("change", () => {
      childWrap
        .querySelectorAll(".skill-checkbox:not(:disabled)")
        .forEach((c) => {
          c.checked = cb.checked;
          c.indeterminate = false;
        });
    });

    // Children → parent tri-state
    childWrap.addEventListener("change", () => _syncParent(cb, childWrap));

    // Initial tri-state
    queueMicrotask(() => _syncParent(cb, childWrap));
  }

  return item;
}

// ---- custom skill upload / delete ------------------------------------------

async function uploadCustomSkill() {
  const nameInput = document.getElementById("custom-skill-name");
  const mdInput = document.getElementById("custom-skill-md");
  const refsInput = document.getElementById("custom-skill-refs");
  const scriptsInput = document.getElementById("custom-skill-scripts");
  const errorEl = document.getElementById("custom-skill-error");
  const uploadBtn = document.getElementById("custom-skill-upload-btn");

  if (!nameInput || !mdInput) return;
  errorEl.textContent = "";

  const name = nameInput.value.trim();
  if (!name) { errorEl.textContent = "Skill name is required."; return; }
  if (!/^[a-z0-9][a-z0-9_-]*$/.test(name)) {
    errorEl.textContent = "Name must be lowercase alphanumeric with hyphens/underscores.";
    return;
  }
  if (!mdInput.files.length) { errorEl.textContent = "SKILL.md file is required."; return; }

  const formData = new FormData();
  formData.append("name", name);
  formData.append("skill_md", mdInput.files[0]);
  for (const ref of Array.from(refsInput?.files || [])) {
    formData.append("references", ref);
  }
  for (const script of Array.from(scriptsInput?.files || [])) {
    formData.append("scripts", script);
  }

  uploadBtn.disabled = true;
  uploadBtn.textContent = "Uploading…";
  try {
    const resp = await fetch("/api/skills/custom", { method: "POST", body: formData });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      errorEl.textContent = body.detail || `Upload failed (${resp.status})`;
      return;
    }
    nameInput.value = "";
    mdInput.value = "";
    if (refsInput) refsInput.value = "";
    if (scriptsInput) scriptsInput.value = "";
    settingsStatus.textContent = `Custom skill "${name}" uploaded ✓`;
    setTimeout(() => { settingsStatus.textContent = ""; }, 3000);
    await loadSettingsData();
  } catch (err) {
    errorEl.textContent = `Upload failed: ${err.message}`;
  } finally {
    uploadBtn.disabled = false;
    uploadBtn.textContent = "Upload Skill";
  }
}

async function deleteCustomSkill(skillName) {
  try {
    const resp = await fetch(`/api/skills/custom/${encodeURIComponent(skillName)}`, { method: "DELETE" });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      settingsStatus.textContent = body.detail || `Delete failed (${resp.status})`;
      return;
    }
    settingsStatus.textContent = `Custom skill "${skillName}" deleted ✓`;
    setTimeout(() => { settingsStatus.textContent = ""; }, 3000);
    await loadSettingsData();
  } catch (err) {
    settingsStatus.textContent = `Delete failed: ${err.message}`;
  }
}

// ---- load / save -----------------------------------------------------------

async function loadSettingsData() {
  skillsChecklist.innerHTML =
    '<p class="settings-hint" style="opacity:0.6">Loading…</p>';
  try {
    const [skillsRes, settingsRes, envRes] = await Promise.all([
      fetch("/api/skills"),
      fetch("/api/settings"),
      fetch("/api/env-config"),
    ]);
    const skills = await skillsRes.json();
    const cfg = await settingsRes.json();
    const envCfg = envRes.ok ? await envRes.json() : {};
    const extraSkills = new Set((cfg.planning || {}).extra_skills || []);

    const roots = _buildSkillTree(skills);
    skillsChecklist.innerHTML = "";

    const header = document.createElement("div");
    header.className = "st-header";
    header.innerHTML = '<span></span><span class="st-col-label" title="Skill is visible to graph search">Enabled</span><span class="st-col-label" title="Full SKILL.md available to planning agent">Planning</span><span></span>';
    skillsChecklist.appendChild(header);

    for (const node of roots) {
      skillsChecklist.appendChild(_renderSkillNode(node, extraSkills, 0));
    }

    // Custom skill upload section
    const uploadSection = document.createElement("div");
    uploadSection.className = "skill-upload-section";
    uploadSection.innerHTML = `
      <details class="skill-upload-details">
        <summary class="skill-upload-summary">+ Add Custom Skill</summary>
        <div class="skill-upload-form">
          <label class="settings-label">Skill Name <span style="font-weight:400;text-transform:none;letter-spacing:0">(lowercase, hyphens/underscores only)</span></label>
          <input id="custom-skill-name" class="text-input settings-env-input" placeholder="e.g. my-custom-skill" autocomplete="off" />
          <label class="settings-label" style="margin-top:8px">SKILL.md file <span style="color:#f87171">*</span></label>
          <input id="custom-skill-md" type="file" accept=".md,text/markdown,text/plain" class="skill-file-input" />
          <label class="settings-label" style="margin-top:8px">Reference files <span style="font-weight:400;text-transform:none;letter-spacing:0">(optional, multiple)</span></label>
          <input id="custom-skill-refs" type="file" multiple class="skill-file-input" />
          <label class="settings-label" style="margin-top:8px">Script files <span style="font-weight:400;text-transform:none;letter-spacing:0">(optional, .py/.sh/.js)</span></label>
          <input id="custom-skill-scripts" type="file" multiple accept=".py,.sh,.bash,.js" class="skill-file-input" />
          <p id="custom-skill-error" class="skill-upload-error"></p>
          <button id="custom-skill-upload-btn" type="button" class="ghost" style="margin-top:8px;width:100%;justify-content:center">Upload Skill</button>
        </div>
      </details>
    `;
    skillsChecklist.appendChild(uploadSection);

    document.getElementById("custom-skill-upload-btn")?.addEventListener("click", uploadCustomSkill);

    // Populate env config inputs
    for (const [key, getEl] of Object.entries(envInputs)) {
      const el = getEl();
      if (el && envCfg[key] !== undefined) {
        el.value = envCfg[key];
      }
    }
  } catch (err) {
    skillsChecklist.innerHTML = `<p class="settings-hint" style="color:#f87171">Failed to load: ${err.message}</p>`;
  }
}

async function saveSettings() {
  const username = settingsUsername.value.trim();
  const extraSkills = Array.from(
    skillsChecklist.querySelectorAll(".skill-checkbox:not(:disabled)")
  )
    .filter((cb) => cb.checked && !cb.indeterminate)
    .map((cb) => cb.dataset.name);

  const disabledSkills = Array.from(
    skillsChecklist.querySelectorAll(".skill-enabled-checkbox")
  )
    .filter((cb) => !cb.checked)
    .map((cb) => cb.dataset.name);

  // Collect env config values (skip empty sensitive fields with "***")
  const envValues = {};
  const sensitiveKeys = new Set(["LLM_API_KEY", "BOHRIUM_PASSWORD"]);
  for (const [key, getEl] of Object.entries(envInputs)) {
    const el = getEl();
    if (!el) continue;
    const val = el.value;
    if (sensitiveKeys.has(key) && (!val || val === "***")) continue;
    envValues[key] = val;
  }

  try {
    settingsSave.disabled = true;
    settingsStatus.textContent = "Saving…";

    const requests = [
      fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          planning: { extra_skills: extraSkills },
          skills: { disabled: disabledSkills },
          user: username ? { name: username } : undefined,
        }),
      }),
    ];
    if (Object.keys(envValues).length > 0) {
      requests.push(
        fetch("/api/env-config", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ values: envValues }),
        })
      );
    }

    const results = await Promise.all(requests);
    for (const res of results) {
      if (!res.ok) throw new Error(await res.text());
    }

    if (username && username !== state.displayName) {
      closeSettingsModal();
      await applyLogin(username, null);
    }
    settingsStatus.textContent = "Saved ✓";
    setTimeout(() => { settingsStatus.textContent = ""; }, 2000);
  } catch (err) {
    settingsStatus.textContent = `Error: ${err.message}`;
  } finally {
    settingsSave.disabled = false;
  }
}

// ---- restart backend -------------------------------------------------------

async function _pollBackendReady(maxAttempts = 30, intervalMs = 2000) {
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    try {
      const res = await fetch("/api/backend-status");
      if (res.ok) {
        const data = await res.json();
        if (data.ready) return;
      }
    } catch (_) {}
  }
  throw new Error("Backend did not come back online in time");
}

async function restartBackend() {
  if (!settingsRestartBtn) return;
  settingsRestartBtn.disabled = true;
  settingsRestartBtn.textContent = "Restarting…";
  settingsStatus.textContent = "Restarting backend…";
  try {
    const res = await fetch("/api/restart-backend", { method: "POST" });
    if (!res.ok) throw new Error(await res.text());
    await _pollBackendReady();
    settingsStatus.textContent = "Backend restarted ✓";
    setTimeout(() => { settingsStatus.textContent = ""; }, 3000);
  } catch (err) {
    settingsStatus.textContent = `Restart failed: ${err.message}`;
  } finally {
    settingsRestartBtn.disabled = false;
    settingsRestartBtn.textContent = "↺ Restart Backend";
  }
}

// Tab switching
document.querySelectorAll(".settings-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".settings-tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".settings-pane").forEach((p) => p.classList.add("hidden"));
    tab.classList.add("active");
    const pane = document.getElementById(`tab-${tab.dataset.tab}`);
    if (pane) pane.classList.remove("hidden");
  });
});

if (settingsBtn) settingsBtn.addEventListener("click", openSettingsModal);
if (settingsClose) settingsClose.addEventListener("click", closeSettingsModal);
if (settingsSave) settingsSave.addEventListener("click", saveSettings);
if (settingsRestartBtn) settingsRestartBtn.addEventListener("click", restartBackend);
settingsModal?.addEventListener("click", (e) => {
  if (e.target === settingsModal) closeSettingsModal();
});
