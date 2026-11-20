"""Minimum-cost maximum flow for the token and shop stock allocators."""
from collections import deque


def min_cost_flow(n, edges, source, sink):
    """Successive shortest paths (Bellman-Ford as SPFA, so costs may be anything) on a small graph: edges
    [(u, v, capacity, cost)]. Returns the flow on each edge, in edges' order; the flow is maximal,
    and of least cost among maximal flows."""
    graph = [[] for _ in range(n)]
    arcs = []           # [to, capacity left, cost, index of the reverse arc]
    for u, v, cap, cost in edges:
        graph[u].append(len(arcs))
        arcs.append([v, cap, cost, len(arcs) + 1])
        graph[v].append(len(arcs))
        arcs.append([u, 0, -cost, len(arcs) - 1])
    while True:
        dist, back, queued = [None] * n, [None] * n, [False] * n
        dist[source] = 0
        queue = deque([source])
        while queue:
            u = queue.popleft()
            queued[u] = False
            for a in graph[u]:
                v, cap, cost, _ = arcs[a]
                if cap > 0 and (dist[v] is None or dist[u] + cost < dist[v]):
                    dist[v], back[v] = dist[u] + cost, a
                    if not queued[v]:
                        queued[v] = True
                        queue.append(v)
        if dist[sink] is None:
            break
        push, v = None, sink
        while v != source:
            a = back[v]
            push = arcs[a][1] if push is None else min(push, arcs[a][1])
            v = arcs[arcs[a][3]][0]
        v = sink
        while v != source:
            a = back[v]
            arcs[a][1] -= push
            arcs[arcs[a][3]][1] += push
            v = arcs[arcs[a][3]][0]
    return [arcs[2 * i + 1][1] for i in range(len(edges))]
