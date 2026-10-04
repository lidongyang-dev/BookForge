/* BookForge 目录树操作（纯逻辑，无 DOM 依赖，供 node 测试与页面共用） */
"use strict";

var MAX_TREE_DEPTH = 8;   // 与后端 MAX_DEPTH 一致

/* 按 id 查找节点，返回 {node, parent(数组引用), idx} */
function findNodeIn(nodes, id) {
  for (var i = 0; i < nodes.length; i++) {
    if (nodes[i].id === id) return { node: nodes[i], parent: nodes, idx: i };
    var hit = findNodeIn(nodes[i].children, id);
    if (hit) return hit;
  }
  return null;
}

/* 查找数组 arr 在树中的位置（arr 是某个节点的 children），返回 {holder, idx} */
function findArrayIn(nodes, arr) {
  for (var i = 0; i < nodes.length; i++) {
    if (nodes[i].children === arr) return { holder: nodes[i], idx: i };
    var hit = findArrayIn(nodes[i].children, arr);
    if (hit) return hit;
  }
  return null;
}

/* 节点在树中的深度（根=1） */
function depthOf(nodes, target, d) {
  for (var i = 0; i < nodes.length; i++) {
    if (nodes[i] === target) return d;
    var r = depthOf(nodes[i].children, target, d + 1);
    if (r) return r;
  }
  return 0;
}

/* 节点子树的最深相对深度（节点自身=1） */
function maxSubDepth(node) {
  var max = 1;
  (function walk(n, d) {
    max = Math.max(max, d);
    (n.children || []).forEach(function (c) { walk(c, d + 1); });
  })(node, 1);
  return max;
}

/* 查找节点 target 在树中所在的数组与下标（顶层数组 = treeArr 本身） */
function findInArrays(nodes, target) {
  for (var i = 0; i < nodes.length; i++) {
    if (nodes[i] === target) return { arr: nodes, idx: i };
    var hit = findInArrays(nodes[i].children, target);
    if (hit) return hit;
  }
  return null;
}

/* 提升层级：节点变为其父级的同级，紧跟原父级之后（深度 -1；顶层不可提升） */
function treePromote(treeArr, id) {
  var hit = findNodeIn(treeArr, id);
  if (!hit) return { ok: false, msg: "节点不存在" };
  var node = hit.node, parent = hit.parent, idx = hit.idx;
  if (parent === treeArr) return { ok: false, msg: "已是顶层目录，无法提升层级" };
  var info = findArrayIn(treeArr, parent);
  if (!info) return { ok: false, msg: "节点结构异常" };
  var pos = findInArrays(treeArr, info.holder);   // 原父级所在数组
  if (!pos) return { ok: false, msg: "节点结构异常" };
  parent.splice(idx, 1);
  pos.arr.splice(pos.idx + 1, 0, node);           // 插到原父级之后（同级）
  return { ok: true };
}

/* 降低层级：节点成为前一个同级条目的子级（深度 +1；首个条目不可降低；受深度上限约束） */
function treeDemote(treeArr, id) {
  var hit = findNodeIn(treeArr, id);
  if (!hit) return { ok: false, msg: "节点不存在" };
  var node = hit.node, parent = hit.parent, idx = hit.idx;
  if (idx === 0) return { ok: false, msg: "没有前一个同级条目可归入，无法降低层级" };
  var prev = parent[idx - 1];
  var nd = depthOf(treeArr, node, 1);
  if (nd + maxSubDepth(node) > MAX_TREE_DEPTH) {
    return { ok: false, msg: "降低层级后超过目录深度上限（" + MAX_TREE_DEPTH + " 层）" };
  }
  parent.splice(idx, 1);
  prev.children.push(node);
  return { ok: true };
}
